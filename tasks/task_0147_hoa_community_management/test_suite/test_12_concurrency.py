"""Concurrency — races where the PRD explicitly defines an outcome.

Per the Testing Philosophy "concurrency-error_id" silence pattern: we
assert exactly-one-succeeds whenever PRD declares it, and only assert
a specific loser error_id when the PRD explicitly names it.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_exactly_one_succeeds,
    create_acc_request_payload,
    create_ballot_payload,
    cure_violation,
    make_member_headers,
    nominate_candidate,
    open_election,
    open_violation,
    parse_iso,
    run_race,
    setup_single_unit_roster,
    submit_acc_request,
    TEST_USERS,
    validate_error,
    version_payload,
)
from datetime import timedelta


class TestACCBeginReviewRace:

    def test_two_secretaries_begin_review_only_one_succeeds(self, api):
        """PRD §3.4: "Concurrent begin-review attempts on the same
        SUBMITTED request serialize first-writer-wins on
        ACCRequest.status: exactly one transition to UNDER_REVIEW
        succeeds, and the loser receives ERR_INVALID_STATE (HTTP 409)."

        Claim: two parallel POST /begin-review on the same SUBMITTED
        request → exactly one succeeds, loser sees ERR_INVALID_STATE.
        """
        owner, unit = setup_single_unit_roster()
        req = submit_acc_request(unit["id"], owner["id"])

        def begin_review():
            return api.begin_review_acc_request(
                req["id"], version_payload(req.get("version", 1)),
                TEST_USERS["secretary_role_headers"],
            )

        results = run_race(begin_review, begin_review)
        outcome = assert_exactly_one_succeeds(*results)
        loser = outcome["failures"][0]
        assert loser.json()["data"]["error_id"] == (
            ApiErrorId.ERR_INVALID_STATE.value
        ), (
            "PRD §3.4 explicitly names ERR_INVALID_STATE for the loser"
        )


class TestDuplicateBallotRace:

    def test_two_ballots_for_same_voter_one_succeeds(self, api):
        """PRD §3.7: "Two ballots cast for the same election by the
        same voter at the same instant serialize first-writer-wins on
        that uniqueness constraint, and the loser also receives
        ERR_DUPLICATE_BALLOT."

        Claim: two parallel POST /ballots with the same
        (election_id, voter_member_id) → exactly one succeeds; the
        loser sees ERR_DUPLICATE_BALLOT.
        """
        from test_helpers import advance_clock_to
        member, _unit = setup_single_unit_roster()
        election = open_election(
            seat="DIRECTOR",
            nomination_open_offset_seconds=0,
            voting_open_offset_seconds=60,
            voting_close_offset_seconds=600,
            quorum_pct=0.10,
        )
        candidate = nominate_candidate(election["id"], member["id"])
        advance_clock_to(parse_iso(election["voting_open_at"]))

        def cast():
            return api.create_ballot(
                election["id"],
                create_ballot_payload(
                    voter_member_id=member["id"],
                    candidate_id=candidate["id"],
                ),
                make_member_headers(member["id"]),
            )

        results = run_race(cast, cast)
        outcome = assert_exactly_one_succeeds(*results)
        loser = outcome["failures"][0]
        assert loser.json()["data"]["error_id"] == (
            ApiErrorId.ERR_DUPLICATE_BALLOT.value
        ), (
            "PRD §3.7 explicitly names ERR_DUPLICATE_BALLOT for the loser"
        )
