"""Voter onboarding, activation, suspension, reactivation, purge,
total_registered_active invariant.

PRD §3.3 (Voter Onboarding and Activation), §3.4 (Party Affiliation
and the Lock).
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    activate_voter,
    advance_clock_iso,
    advance_clock_to,
    advance_to_early_voting,
    api_client,
    assert_voter,
    cast_in_person,
    change_party_payload,
    create_voter,
    create_voter_payload,
    get_election,
    get_voter,
    iso_utc,
    make_voter_headers,
    open_registration,
    parse_iso,
    setup_active_voter,
    setup_election_with_precinct,
    setup_open_registration,
    state_transition_payload,
    suspend_voter,
    validate_error,
    validate_success,
)


class TestVoterCreation:

    def test_create_voter_starts_in_pending_unaffiliated(self, api):
        """PRD §3.3: 'The server creates a row in PENDING with
        party_affiliation=UNAFFILIATED.'
        """
        election, _ = setup_open_registration()
        voter = create_voter(election["id"])
        assert_voter(voter)
        assert voter["status"] == "PENDING", (
            f"new voter must be PENDING, got {voter['status']!r}"
        )
        assert voter["party_affiliation"] == "UNAFFILIATED", (
            f"new voter must be UNAFFILIATED, got "
            f"{voter['party_affiliation']!r}"
        )


class TestActivationSnapshots:

    def test_activation_snapshots_registered_by_user_id(self, api):
        """PRD §3.3: 'registered_by_user_id is set to the activating
        clerk's X-User-ID. The last snapshot is what the
        segregation-of-duties check later compares against on
        curing-case mutations.'
        """
        election, _ = setup_open_registration()
        voter = create_voter(election["id"])
        voter = activate_voter(voter["id"])
        assert voter["registered_by_user_id"] == (
            TEST_USERS["registrar_clerk_headers"]["X-User-ID"]
        ), (
            "expected registered_by_user_id == X-User-ID of activator, "
            f"got {voter['registered_by_user_id']!r}"
        )

    def test_activation_snapshots_party_locked_at(self, api):
        """PRD §3.3: 'party_locked_at on the voter is set to the
        election's registration_deadline.'
        """
        election, _ = setup_open_registration()
        voter = create_voter(election["id"])
        voter = activate_voter(voter["id"])
        # PRD §3.3 says it equals Election.registration_deadline.
        assert voter["party_locked_at"] == election["registration_deadline"], (
            "expected party_locked_at == Election.registration_deadline, "
            f"got {voter['party_locked_at']!r} vs "
            f"{election['registration_deadline']!r}"
        )

    def test_activation_increments_total_registered_active(self, api):
        """PRD §3.3: 'total_registered_active on the parent election
        is incremented by one (cascade-up).'
        """
        election, _ = setup_open_registration()
        before = get_election(election["id"])["total_registered_active"]
        voter = create_voter(election["id"])
        activate_voter(voter["id"])
        after = get_election(election["id"])["total_registered_active"]
        assert after == before + 1, (
            f"total_registered_active expected {before}+1, got {after}"
        )


class TestSuspendCascadesCounter:

    def test_suspend_decrements_total_registered_active(self, api):
        """PRD §3.3: 'Successful suspension decrements
        total_registered_active by one.'
        """
        election, _, voter = setup_active_voter()
        before = get_election(election["id"])["total_registered_active"]
        suspend_voter(voter["id"])
        after = get_election(election["id"])["total_registered_active"]
        assert after == before - 1, (
            f"total_registered_active expected {before}-1, got {after}"
        )

    def test_suspend_blocked_by_existing_ballot(self, api):
        """PRD §3.3: 'the transition is blocked if the voter already
        has a BallotCast in CAST or TALLIED for this election; the
        rejection code is ERR_VOTER_HAS_BALLOT.'
        """
        election, precinct, voter = setup_active_voter()
        election = advance_to_early_voting(election)
        # Cast EARLY_IN_PERSON.
        cast_in_person(
            voter_id=voter["id"], precinct_id=precinct["id"],
            method="EARLY_IN_PERSON", voter_choice="A",
        )
        resp = api.transition_voter(
            voter["id"], state_transition_payload("SUSPENDED"),
            TEST_USERS["registrar_clerk_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_VOTER_HAS_BALLOT.value)


class TestReactivation:

    def test_reactivate_restores_total_registered_active(self, api):
        """PRD §3.3: 'The successful re-activation increments
        total_registered_active by one.'

        Compensating-action invariant: suspend then reactivate restores
        the counter exactly.
        """
        election, _, voter = setup_active_voter()
        before = get_election(election["id"])["total_registered_active"]
        v = suspend_voter(voter["id"])
        mid = get_election(election["id"])["total_registered_active"]
        api.transition_voter(
            voter["id"],
            state_transition_payload("ACTIVE", version=v["version"]),
            TEST_USERS["registrar_clerk_headers"],
        )
        after = get_election(election["id"])["total_registered_active"]
        assert mid == before - 1
        assert after == before, (
            f"reactivation must restore total_registered_active to "
            f"{before}, got {after}"
        )


class TestPurgeRules:

    def test_purge_requires_certified_election(self, api):
        """PRD §3.3: 'Both transitions are gated on Election.state ==
        CERTIFIED (otherwise ERR_INVALID_STATE).'
        """
        _election, _, voter = setup_active_voter()
        resp = api.transition_voter(
            voter["id"], state_transition_payload("PURGED"),
            TEST_USERS["registrar_clerk_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


class TestPartyLock:

    def test_party_change_before_deadline_succeeds(self, api):
        """PRD §3.4: 'A successful change updates
        Voter.party_affiliation, refreshes Voter.updated_at, and
        writes a new PartyRegistration row.'

        Claim: a party change well before party_locked_at succeeds and
        updates Voter.party_affiliation.
        """
        election, _, voter = setup_active_voter()
        resp = api.change_party(
            voter["id"], change_party_payload("DEMOCRATIC"),
            make_voter_headers(voter["id"]),
        )
        # PartyRegistration is a new resource so 201.
        validate_success(resp, expected_status=201)
        refreshed = get_voter(voter["id"])
        assert refreshed["party_affiliation"] == "DEMOCRATIC"

    def test_party_change_after_party_locked_at_rejected(self, api):
        """PRD §3.4: 'The change is rejected with ERR_PARTY_LOCKED if
        the server clock is at or beyond the voter's snapshotted
        party_locked_at.'
        """
        election, _, voter = setup_active_voter()
        # Advance the clock to exactly party_locked_at (the
        # registration_deadline snapshot).
        advance_clock_iso(voter["party_locked_at"])
        resp = api.change_party(
            voter["id"], change_party_payload("REPUBLICAN"),
            make_voter_headers(voter["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PARTY_LOCKED.value)
