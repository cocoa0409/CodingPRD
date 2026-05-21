"""Concurrency and optimistic-concurrency-control tests.

PRD §2.8 (Optimistic Concurrency Control), §2.11 (Concurrency
Guarantees).
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_to_early_voting,
    advance_to_election_day,
    api_client,
    assert_at_least_one_succeeds,
    assert_exactly_one_succeeds,
    cast_in_person,
    change_party_payload,
    create_ballot_payload,
    issue_absentee,
    make_voter_headers,
    parse_iso,
    request_absentee,
    return_absentee,
    return_absentee_payload,
    run_race,
    setup_active_voter,
    state_transition_payload,
    validate_error,
    validate_success,
)


class TestOptimisticConcurrencyControl:

    def test_voter_state_with_stale_version_rejected(self, api):
        """PRD §2.8: 'If version is supplied and does not match the
        row's current version, the request is rejected with
        ERR_VERSION_MISMATCH.'
        """
        election, _, voter = setup_active_voter()
        stale_version = voter["version"] - 1  # mutated by activation
        if stale_version < 1:
            stale_version = 0
        resp = api.transition_voter(
            voter["id"],
            state_transition_payload("SUSPENDED", version=stale_version),
            TEST_USERS["registrar_clerk_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_VERSION_MISMATCH.value)

    def test_unauthenticated_beats_version_mismatch(self, api):
        """PRD §2.9: 'An unauthenticated caller who also has a stale
        version always sees ERR_UNAUTHENTICATED, never
        ERR_VERSION_MISMATCH.'
        """
        # Build a real voter so the route exists, then drop headers.
        election, _, voter = setup_active_voter()
        resp = api._request(
            "POST", f"/voters/{voter['id']}/state",
            {"to_state": "SUSPENDED", "version": 999},
            headers={},
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


class TestDoubleVoteRace:

    def test_two_simultaneous_in_person_casts_serialise(self, api):
        """PRD §2.11: 'Two attempts by the same voter to cast a ballot
        ... serialise on the uniqueness of (voter_id, election_id) ...
        The first writer wins; the loser receives ERR_DOUBLE_VOTE with
        HTTP 409.'
        """
        election, precinct, voter = setup_active_voter()
        election = advance_to_early_voting(election)
        results = run_race(
            lambda: api.create_ballot(
                create_ballot_payload(
                    voter_id=voter["id"], precinct_id=precinct["id"],
                    method="EARLY_IN_PERSON", voter_choice="A",
                ),
                TEST_USERS["precinct_officer_headers"],
            ),
            lambda: api.create_ballot(
                create_ballot_payload(
                    voter_id=voter["id"], precinct_id=precinct["id"],
                    method="EARLY_IN_PERSON", voter_choice="B",
                ),
                TEST_USERS["precinct_officer_headers"],
            ),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        # The PRD pins the loser's error_id explicitly.
        loser = outcome["failures"][0]
        loser_body = loser.json().get("data", {}) or {}
        assert loser_body.get("error_id") == ApiErrorId.ERR_DOUBLE_VOTE.value, (
            f"loser must surface ERR_DOUBLE_VOTE per PRD §2.11, "
            f"got {loser_body!r}"
        )


class TestAbsenteeAlreadyIssuedRace:

    def test_two_simultaneous_absentee_issues_serialise(self, api):
        """PRD §2.11: 'Two RegistrarClerk calls that would issue an
        absentee ballot for the same (voter_id, election_id) serialise
        on the uniqueness of an AbsenteeBallot for that pair ... The
        first writer wins; the loser receives
        ERR_ABSENTEE_ALREADY_ISSUED with HTTP 409.'

        Two concurrent absentee-request creates for the same voter +
        election: one wins, one loses with ERR_ABSENTEE_ALREADY_ISSUED.
        """
        election, _, voter = setup_active_voter()
        results = run_race(
            lambda: api.request_absentee_ballot(
                voter["id"],
                {"election_id": voter["election_id"],
                 "reason_code": "ABSENT"},
                TEST_USERS["registrar_clerk_headers"],
            ),
            lambda: api.request_absentee_ballot(
                voter["id"],
                {"election_id": voter["election_id"],
                 "reason_code": "ABSENT"},
                TEST_USERS["registrar_clerk_headers"],
            ),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        loser_body = loser.json().get("data", {}) or {}
        assert loser_body.get("error_id") == (
            ApiErrorId.ERR_ABSENTEE_ALREADY_ISSUED.value
        ), (
            f"loser must surface ERR_ABSENTEE_ALREADY_ISSUED per "
            f"PRD §2.11, got {loser_body!r}"
        )
