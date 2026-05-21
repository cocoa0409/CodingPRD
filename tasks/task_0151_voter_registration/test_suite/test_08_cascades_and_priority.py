"""Multi-row cascades and validation-priority interactions.

PRD §2.6 (Hierarchical Consistency and Cascades), §2.9 (Validation
Priority), §3.3 (suspend cascade), §3.5 (curing cascade), §3.7
(machine-failure cascade).
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_clock_iso,
    advance_clock_to,
    advance_to_early_voting,
    api_client,
    create_voter,
    get_absentee_ballot,
    get_curing_case,
    issue_absentee,
    iso_utc,
    parse_iso,
    request_absentee,
    return_absentee,
    setup_active_voter,
    setup_curing_case_under_review,
    setup_open_registration,
    setup_returned_absentee_with_curing_case,
    state_transition_payload,
    submit_curing_payload,
    suspend_voter,
    make_voter_headers,
)


class TestVoterSuspendDepth3Cascade:

    def test_suspend_cascades_absentee_to_rejected(self, api):
        """PRD §2.6: 'Every AbsenteeBallot owned by that voter whose
        status is REQUESTED, ISSUED, or RETURNED is then driven to
        REJECTED with the reason "voter suspended" (link 2).'
        """
        election, _, voter, ballot, _case = (
            setup_returned_absentee_with_curing_case()
        )
        # Sanity: ballot is RETURNED.
        assert ballot["status"] == "RETURNED"
        suspend_voter(voter["id"])
        refreshed = get_absentee_ballot(ballot["id"])
        assert refreshed["status"] == "REJECTED", (
            f"AbsenteeBallot must cascade to REJECTED on voter "
            f"suspend, got {refreshed['status']!r}"
        )

    def test_suspend_cascades_curing_case_to_resolved_reject_via_ballot(
            self, api):
        """PRD §2.6: 'For each such ballot that had a
        linked_curing_case_id, the linked CuringCase ... is in turn
        driven to RESOLVED_REJECT (link 3). The curing-case transition
        at link 3 is caused by the ballot transition at link 2, not
        directly by the voter transition; it is a true transitive
        cascade.'
        """
        election, _, voter, ballot, case = (
            setup_returned_absentee_with_curing_case()
        )
        # Sanity: case starts in OPEN_PENDING_VOTER (depth-3 trigger).
        assert case["status"] == "OPEN_PENDING_VOTER"
        suspend_voter(voter["id"])
        refreshed = get_curing_case(case["id"])
        assert refreshed["status"] == "RESOLVED_REJECT", (
            f"CuringCase must cascade to RESOLVED_REJECT via "
            f"AbsenteeBallot, got {refreshed['status']!r}"
        )

    def test_suspend_cascades_curing_case_from_under_review_via_ballot(
            self, api):
        """PRD §2.6: 'the linked CuringCase — provided it is in
        OPEN_PENDING_VOTER or UNDER_REVIEW — is in turn driven to
        RESOLVED_REJECT.'

        Drive the case to UNDER_REVIEW first, then suspend.
        """
        election, _, voter, _, case = setup_curing_case_under_review()
        assert case["status"] == "UNDER_REVIEW"
        suspend_voter(voter["id"])
        refreshed = get_curing_case(case["id"])
        assert refreshed["status"] == "RESOLVED_REJECT"


class TestCuringExpiryCascade:

    def test_expired_curing_case_cascades_ballot_to_rejected(self, api):
        """PRD §2.6: 'When a CuringCase is system-expired because now
        has crossed Election.cure_deadline, the linked AbsenteeBallot
        cascades from RETURNED to REJECTED, and no BallotCast is
        created.'
        """
        election, _, voter, ballot, case = (
            setup_returned_absentee_with_curing_case()
        )
        # Advance the clock past cure_deadline (1 second over).
        target = parse_iso(election["cure_deadline"]) + timedelta(seconds=1)
        advance_clock_to(target)
        # Re-read the case and ballot — the sweep should have fired.
        refreshed_case = get_curing_case(case["id"])
        refreshed_ballot = get_absentee_ballot(ballot["id"])
        assert refreshed_case["status"] == "EXPIRED", (
            f"CuringCase must EXPIRE when now > cure_deadline, "
            f"got {refreshed_case['status']!r}"
        )
        assert refreshed_ballot["status"] == "REJECTED", (
            f"AbsenteeBallot must cascade to REJECTED on case expiry, "
            f"got {refreshed_ballot['status']!r}"
        )


class TestTallyBlockedByCuring:

    def test_tally_blocked_while_curing_case_open(self, api):
        """PRD §3.2: 'no curing case may be in OPEN_PENDING_VOTER or
        UNDER_REVIEW (otherwise the transition is rejected with
        ERR_CURING_IN_PROGRESS).'
        """
        # Set up a case in OPEN_PENDING_VOTER and try to advance the
        # election to TALLY.
        election, _, voter, _ballot, _case = (
            setup_returned_absentee_with_curing_case()
        )
        # Advance clock past ballot_return_deadline (the TALLY temporal
        # gate), so the only blocker is ERR_CURING_IN_PROGRESS.
        advance_clock_to(
            parse_iso(election["ballot_return_deadline"])
            + timedelta(seconds=1),
        )
        resp = api.transition_election(
            election["id"], state_transition_payload("TALLY"),
            TEST_USERS["election_board_headers"],
        )
        from test_helpers import validate_error
        validate_error(resp, ApiErrorId.ERR_CURING_IN_PROGRESS.value)


class TestValidationPriorityPair:
    """PRD §2.9 — global validation order makes the returned error_id
    deterministic when multiple checks would otherwise fire.
    """

    def test_deadline_temporal_priority_beats_residency(self, api):
        """PRD §2.9: '(6) deadline-window checks, surfacing
        ERR_DEADLINE_PASSED' before '(9) eligibility checks at
        activation, surfacing ... ERR_RESIDENCY_INSUFFICIENT'.

        Activation attempted after registration_deadline AND with
        residency_days < 30: the deadline error must win.
        """
        election, _ = setup_open_registration()
        # Construct a voter whose residency_since is also too recent.
        ed = parse_iso(election["election_date"])
        short_residency = iso_utc(ed - timedelta(days=10))
        voter = create_voter(
            election["id"], residency_since=short_residency,
        )
        # Advance past registration_deadline.
        advance_clock_to(
            parse_iso(election["registration_deadline"])
            + timedelta(seconds=1),
        )
        resp = api.transition_voter(
            voter["id"], state_transition_payload("ACTIVE"),
            TEST_USERS["registrar_clerk_headers"],
        )
        from test_helpers import validate_error
        validate_error(resp, ApiErrorId.ERR_DEADLINE_PASSED.value)
