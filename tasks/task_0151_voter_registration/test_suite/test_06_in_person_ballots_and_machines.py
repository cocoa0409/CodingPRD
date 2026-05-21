"""In-person ballot casting, voting-machine lifecycle, double-vote
prevention, machine-failure fallback.

PRD §3.7 (Voting Machines and the Provisional Fallback), §3.8
(Casting a Ballot In-Person).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_to_early_voting,
    advance_to_election_day,
    api_client,
    assert_ballot_cast,
    cast_in_person,
    create_ballot_payload,
    create_voter,
    get_precinct,
    get_voting_machine,
    machine_transition_payload,
    mark_machine_down,
    provision_machine,
    setup_active_voter,
    setup_open_registration,
    state_transition_payload,
    validate_error,
    validate_success,
    create_voting_machine_payload,
)


class TestInPersonBallotCreation:

    def test_create_early_in_person_ballot_during_early_voting(self, api):
        """PRD §3.8: 'A PrecinctOfficer records an in-person ballot ...
        The server creates a BallotCast in CAST with cast_at set to the
        server clock.'
        """
        election, precinct, voter = setup_active_voter()
        election = advance_to_early_voting(election)
        ballot = cast_in_person(
            voter_id=voter["id"], precinct_id=precinct["id"],
            method="EARLY_IN_PERSON", voter_choice="A",
        )
        assert_ballot_cast(ballot)
        assert ballot["status"] == "CAST"
        assert ballot["method"] == "EARLY_IN_PERSON"

    def test_election_day_machine_creates_in_use(self, api):
        """PRD §3.7: 'A machine moves from READY to IN_USE
        automatically the first time a ballot is cast on it with
        method=ELECTION_DAY_MACHINE and a matching machine_id; this
        transition is system-driven and gated on Election.state ==
        ELECTION_DAY.'
        """
        election, precinct, voter = setup_active_voter()
        machine = provision_machine(election["id"], precinct["id"])
        election = advance_to_early_voting(election)
        election = advance_to_election_day(election)
        cast_in_person(
            voter_id=voter["id"], precinct_id=precinct["id"],
            method="ELECTION_DAY_MACHINE", voter_choice="A",
            machine_id=machine["id"],
        )
        refreshed_machine = get_voting_machine(machine["id"])
        assert refreshed_machine["status"] == "IN_USE", (
            f"machine must auto-advance to IN_USE, "
            f"got {refreshed_machine['status']!r}"
        )


class TestDoubleVotePrevention:

    def test_second_in_person_cast_rejected_with_double_vote(self, api):
        """PRD §3.8: 'at most one non-INVALIDATED BallotCast may exist
        per (voter_id, election_id) pair. A second creation that would
        violate this is rejected with ERR_DOUBLE_VOTE.'
        """
        election, precinct, voter = setup_active_voter()
        election = advance_to_early_voting(election)
        cast_in_person(
            voter_id=voter["id"], precinct_id=precinct["id"],
            method="EARLY_IN_PERSON", voter_choice="A",
        )
        resp = api.create_ballot(
            create_ballot_payload(
                voter_id=voter["id"], precinct_id=precinct["id"],
                method="EARLY_IN_PERSON", voter_choice="B",
            ),
            TEST_USERS["precinct_officer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_DOUBLE_VOTE.value)


class TestMachineFailureFallback:

    def test_election_day_machine_blocked_when_machine_failure_active(
            self, api):
        """PRD §3.7: 'from that moment on any cast attempt at this
        precinct with method=ELECTION_DAY_MACHINE is rejected with
        ERR_MACHINE_FAILURE.'
        """
        # PRD §3.3: PENDING -> ACTIVE requires now <= registration_deadline,
        # so all voters must be activated before the clock advances past
        # registration_deadline (= early_voting_starts_at - days).
        election, precinct, voter = setup_active_voter()
        _e2, _p2, voter2 = setup_active_voter(
            election=election, precinct=precinct,
        )
        machine = provision_machine(election["id"], precinct["id"])
        election = advance_to_early_voting(election)
        election = advance_to_election_day(election)
        # Cast first to drive machine to IN_USE, then a second voter
        # tries on it after it goes DOWN.
        first_voter = voter
        cast_in_person(
            voter_id=first_voter["id"], precinct_id=precinct["id"],
            method="ELECTION_DAY_MACHINE", voter_choice="A",
            machine_id=machine["id"],
        )
        mark_machine_down(machine["id"], failure_reason="POWER")
        resp = api.create_ballot(
            create_ballot_payload(
                voter_id=voter2["id"], precinct_id=precinct["id"],
                method="ELECTION_DAY_MACHINE", voter_choice="B",
                machine_id=machine["id"],
            ),
            TEST_USERS["precinct_officer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_MACHINE_FAILURE.value)

    def test_provisional_allowed_after_machine_failure(self, api):
        """PRD §3.7: 'Officers must instead present
        method=ELECTION_DAY_PROVISIONAL.'
        """
        # PRD §3.3: voter2 must be activated before the clock advances
        # past registration_deadline.
        election, precinct, voter = setup_active_voter()
        _e2, _p2, voter2 = setup_active_voter(
            election=election, precinct=precinct,
        )
        machine = provision_machine(election["id"], precinct["id"])
        election = advance_to_early_voting(election)
        election = advance_to_election_day(election)
        cast_in_person(
            voter_id=voter["id"], precinct_id=precinct["id"],
            method="ELECTION_DAY_MACHINE", voter_choice="A",
            machine_id=machine["id"],
        )
        mark_machine_down(machine["id"], failure_reason="POWER")
        # A second voter casts PROVISIONAL — must succeed.
        ballot = cast_in_person(
            voter_id=voter2["id"], precinct_id=precinct["id"],
            method="ELECTION_DAY_PROVISIONAL", voter_choice="A",
        )
        assert ballot["method"] == "ELECTION_DAY_PROVISIONAL"
        assert ballot["status"] == "CAST"


class TestMachineDownInputValidation:

    def test_machine_down_requires_failure_reason(self, api):
        """PRD §3.7: 'The transition is rejected with ERR_BAD_REQUEST
        if no reason is supplied.'
        """
        election, precinct, voter = setup_active_voter()
        machine = provision_machine(election["id"], precinct["id"])
        election = advance_to_early_voting(election)
        election = advance_to_election_day(election)
        cast_in_person(
            voter_id=voter["id"], precinct_id=precinct["id"],
            method="ELECTION_DAY_MACHINE", voter_choice="A",
            machine_id=machine["id"],
        )
        resp = api.transition_voting_machine(
            machine["id"],
            machine_transition_payload("DOWN"),  # no failure_reason
            TEST_USERS["precinct_officer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_BAD_REQUEST.value)

    def test_machine_down_requires_election_day_state(self, api):
        """PRD §3.7: 'and with ERR_INVALID_STATE if the election is
        not in ELECTION_DAY.'
        """
        election, precinct, _ = setup_active_voter()
        machine = provision_machine(election["id"], precinct["id"])
        election = advance_to_early_voting(election)
        # Election is in EARLY_VOTING; machine still READY.
        resp = api.transition_voting_machine(
            machine["id"],
            machine_transition_payload("DOWN", failure_reason="POWER"),
            TEST_USERS["precinct_officer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


class TestMachineFailureFlag:

    def test_precinct_machine_failure_active_flips_on_down(self, api):
        """PRD §3.7: 'sets the parent precinct's computed
        machine_failure_active to true.'
        """
        election, precinct, voter = setup_active_voter()
        machine = provision_machine(election["id"], precinct["id"])
        election = advance_to_early_voting(election)
        election = advance_to_election_day(election)
        cast_in_person(
            voter_id=voter["id"], precinct_id=precinct["id"],
            method="ELECTION_DAY_MACHINE", voter_choice="A",
            machine_id=machine["id"],
        )
        mark_machine_down(machine["id"], failure_reason="POWER")
        refreshed_precinct = get_precinct(election["id"], precinct["id"])
        assert refreshed_precinct["machine_failure_active"] is True
