"""Election lifecycle and precinct creation.

PRD §3.1 (Setting Up an Election), §3.2 (Election Lifecycle and
System-Driven Rollovers).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    DEFAULT_RECOUNT_THRESHOLD_PCT,
    TEST_USERS,
    advance_clock_iso,
    advance_clock_to,
    advance_past_ballot_return,
    advance_to_early_voting,
    advance_to_election_day,
    api_client,
    assert_election,
    assert_precinct,
    create_election,
    create_election_payload,
    create_precinct,
    create_precinct_payload,
    get_election,
    initiate_tally,
    iso_utc,
    open_registration,
    parse_iso,
    setup_election_with_precinct,
    setup_open_registration,
    state_transition_payload,
    transition_election,
    validate_error,
    validate_success,
)


class TestElectionCreation:

    def test_create_election_starts_in_draft(self, api,
                                             election_board_headers):
        """PRD §3.1: 'A new election is in DRAFT.'

        Claim: POST /elections creates an Election with state='DRAFT'.
        """
        resp = api.create_election(
            create_election_payload(), election_board_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert_election(data)
        assert data["state"] == "DRAFT", (
            f"new election must start in DRAFT, got {data['state']!r}"
        )

    def test_create_election_default_recount_threshold(
            self, api, election_board_headers):
        """PRD §3.1: 'The optional recount_threshold_pct ... when not
        supplied, it defaults to 0.005, that is, half of one percent.'

        Claim: creating an election without recount_threshold_pct
        produces recount_threshold_pct == 0.005.
        """
        payload = create_election_payload()
        # Ensure no override.
        payload.pop("recount_threshold_pct", None)
        resp = api.create_election(payload, election_board_headers)
        data = validate_success(resp, expected_status=201)
        assert float(data["recount_threshold_pct"]) == pytest.approx(
            DEFAULT_RECOUNT_THRESHOLD_PCT, abs=1e-9,
        ), (
            f"default recount_threshold_pct must be 0.005, "
            f"got {data['recount_threshold_pct']!r}"
        )


class TestOpenRegistrationGuards:

    def test_open_registration_requires_precinct(
            self, api, election_board_headers):
        """PRD §3.1: 'an attempt to transition the election from
        DRAFT to OPEN_REGISTRATION while no precinct exists for that
        election is rejected with ERR_NO_PRECINCTS.'
        """
        election = create_election()
        # No precinct created yet.
        resp = api.transition_election(
            election["id"],
            state_transition_payload("OPEN_REGISTRATION"),
            election_board_headers,
        )
        validate_error(resp, ApiErrorId.ERR_NO_PRECINCTS.value)

    def test_open_registration_requires_deadline_in_future(
            self, api, election_board_headers):
        """PRD §3.1: 'The same transition also enforces that
        registration_deadline is still in the future relative to the
        server clock; if the deadline has already passed, the
        transition is rejected with ERR_DEADLINE_PASSED.'
        """
        election, _precinct = setup_election_with_precinct()
        # Advance the clock past registration_deadline (which is 30 days
        # before election_date by default).
        target = parse_iso(election["registration_deadline"])
        from datetime import timedelta
        advance_clock_to(target + timedelta(seconds=1))
        resp = api.transition_election(
            election["id"],
            state_transition_payload("OPEN_REGISTRATION"),
            election_board_headers,
        )
        validate_error(resp, ApiErrorId.ERR_DEADLINE_PASSED.value)


class TestPrecinctCreation:

    def test_create_precinct_returns_computed_fields(
            self, api, election_board_headers):
        """PRD §3.1: 'A precinct response also exposes the computed
        provisional_ballot_count ... and the computed
        machine_failure_active boolean, which is true if and only if
        at least one VotingMachine at the precinct currently has
        status=DOWN.'

        Claim: a freshly created precinct returns
        provisional_ballot_count=0 and machine_failure_active=False.
        """
        election = create_election()
        resp = api.create_precinct(
            election["id"],
            create_precinct_payload(),
            election_board_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert_precinct(data)
        assert data["provisional_ballot_count"] == 0
        assert data["machine_failure_active"] is False


class TestSystemDrivenRollovers:

    def test_open_registration_to_early_voting_on_clock_advance(self, api):
        """PRD §3.2: 'The rollover from OPEN_REGISTRATION to
        EARLY_VOTING is system-driven: when the server clock reaches
        or surpasses early_voting_starts_at and the clock-advance
        capability runs the relevant sweep, the election advances
        automatically.'
        """
        election, _ = setup_open_registration()
        advance_clock_iso(election["early_voting_starts_at"])
        refreshed = get_election(election["id"])
        assert refreshed["state"] == "EARLY_VOTING", (
            f"expected EARLY_VOTING after clock reached "
            f"early_voting_starts_at, got {refreshed['state']!r}"
        )

    def test_early_voting_to_election_day_on_clock_advance(self, api):
        """PRD §3.2: 'The rollover from EARLY_VOTING to ELECTION_DAY
        is likewise system-driven once the clock reaches or surpasses
        early_voting_ends_at.'
        """
        election, _ = setup_open_registration()
        election = advance_to_early_voting(election)
        assert election["state"] == "EARLY_VOTING"
        election = advance_to_election_day(election)
        assert election["state"] == "ELECTION_DAY", (
            f"expected ELECTION_DAY after clock reached "
            f"early_voting_ends_at, got {election['state']!r}"
        )


class TestTallyTransitionGuards:

    def test_tally_before_ballot_return_deadline_rejected(
            self, api, election_board_headers):
        """PRD §3.2: 'the server clock must have reached or surpassed
        ballot_return_deadline (an attempt before that point is
        rejected with ERR_TALLY_TOO_EARLY).'
        """
        election, _ = setup_open_registration()
        election = advance_to_early_voting(election)
        election = advance_to_election_day(election)
        # Clock is at early_voting_ends_at, before ballot_return_deadline.
        resp = api.transition_election(
            election["id"],
            state_transition_payload("TALLY"),
            election_board_headers,
        )
        validate_error(resp, ApiErrorId.ERR_TALLY_TOO_EARLY.value)


class TestTransitionAuthorization:

    def test_voter_cannot_transition_election(self, api, voter_headers):
        """PRD §4: 'POST /elections/{electionId}/state ... Authorized
        Role(s): ElectionBoard.'

        Claim: Voter cannot transition an election.
        """
        election, _ = setup_open_registration()
        resp = api.transition_election(
            election["id"],
            state_transition_payload("TALLY"),
            voter_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)
