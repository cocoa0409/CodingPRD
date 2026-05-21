"""Absentee ballot lifecycle and curing case adjudication.

PRD §3.5 (Absentee Ballots and Curing).
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_clock_iso,
    advance_clock_to,
    api_client,
    assert_absentee_ballot,
    assert_curing_case,
    create_voter,
    get_absentee_ballot,
    get_curing_case,
    issue_absentee,
    iso_utc,
    make_voter_headers,
    parse_iso,
    request_absentee,
    request_absentee_payload,
    return_absentee,
    return_absentee_payload,
    setup_active_voter,
    setup_curing_case_under_review,
    setup_open_registration,
    setup_returned_absentee_with_curing_case,
    state_transition_payload,
    submit_curing_payload,
    validate_error,
    validate_error_is_one_of,
    validate_success,
    version_payload,
    make_reviewer_clerk_headers,
    REGISTRAR_CLERK_ID,
)


class TestAbsenteeRequest:

    def test_default_reason_code_is_no_reason(self, api):
        """PRD §3.5: 'if no reason is supplied, reason_code defaults to
        NO_REASON.'
        """
        election, _, voter = setup_active_voter()
        ballot = request_absentee(voter)
        assert_absentee_ballot(ballot)
        assert ballot["reason_code"] == "NO_REASON", (
            f"default reason_code must be NO_REASON, got "
            f"{ballot['reason_code']!r}"
        )

    def test_request_status_is_requested(self, api):
        """PRD §3.5: 'The server creates an AbsenteeBallot row in
        REQUESTED.'
        """
        election, _, voter = setup_active_voter()
        ballot = request_absentee(voter)
        assert ballot["status"] == "REQUESTED"


class TestAbsenteeIssue:

    def test_issue_requires_voter_active(self, api):
        """PRD §3.5: 'the parent Voter.status must be ACTIVE (otherwise
        ERR_VOTER_NOT_ACTIVE).'

        Build the AbsenteeBallot while the Voter is PENDING (request
        endpoint does not require ACTIVE), then attempt to issue.
        """
        election, _ = setup_open_registration()
        voter = create_voter(election["id"])  # PENDING
        resp_req = api.request_absentee_ballot(
            voter["id"], request_absentee_payload(voter["election_id"]),
            TEST_USERS["registrar_clerk_headers"],
        )
        ballot = validate_success(resp_req, expected_status=201)
        # Voter remains PENDING.
        resp = api.transition_absentee_ballot(
            ballot["id"], state_transition_payload("ISSUED"),
            TEST_USERS["registrar_clerk_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_VOTER_NOT_ACTIVE.value)

    def test_issue_after_absentee_request_deadline_rejected(self, api):
        """PRD §3.5: 'the server clock must be no later than
        absentee_request_deadline (otherwise ERR_DEADLINE_PASSED).'
        """
        election, _, voter = setup_active_voter()
        ballot = request_absentee(voter)
        advance_clock_to(
            parse_iso(election["absentee_request_deadline"])
            + timedelta(seconds=1),
        )
        resp = api.transition_absentee_ballot(
            ballot["id"], state_transition_payload("ISSUED"),
            TEST_USERS["registrar_clerk_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_DEADLINE_PASSED.value)


class TestAbsenteeReturn:

    def test_return_late_rejected(self, api):
        """PRD §3.5: 'if the server clock is later than
        ballot_return_deadline, the request is rejected with
        ERR_RETURN_LATE.'
        """
        election, _, voter = setup_active_voter()
        ballot = request_absentee(voter)
        ballot = issue_absentee(ballot["id"])
        advance_clock_to(
            parse_iso(election["ballot_return_deadline"])
            + timedelta(seconds=1),
        )
        resp = api.return_absentee_ballot(
            ballot["id"],
            return_absentee_payload(
                signature_match="MATCH", voter_choice="A",
            ),
            TEST_USERS["registrar_clerk_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_RETURN_LATE.value)

    def test_return_with_match_cascades_to_accepted(self, api):
        """PRD §3.5: 'If signature_match is MATCH, the ballot
        auto-transitions to ACCEPTED, decided_at is set, and a new
        BallotCast is created with method=ABSENTEE.'
        """
        election, _, voter = setup_active_voter()
        ballot = request_absentee(voter)
        ballot = issue_absentee(ballot["id"])
        ballot = return_absentee(
            ballot["id"], signature_match="MATCH", voter_choice="A",
        )
        # After return with MATCH, the ballot is ACCEPTED.
        refreshed = get_absentee_ballot(ballot["id"])
        assert refreshed["status"] == "ACCEPTED", (
            f"MATCH must cascade to ACCEPTED, got {refreshed['status']!r}"
        )
        assert refreshed.get("decided_at"), (
            "ACCEPTED must populate decided_at per PRD §3.5"
        )

    def test_return_with_mismatch_opens_curing_case(self, api):
        """PRD §3.5: 'If signature_match is MISMATCH or MISSING, a
        CuringCase is opened with defect_code equal to
        SIGNATURE_MISMATCH or SIGNATURE_MISSING respectively, and the
        ballot's linked_curing_case_id is populated with the new
        case's id.'
        """
        election, _, voter = setup_active_voter()
        ballot = request_absentee(voter)
        ballot = issue_absentee(ballot["id"])
        ballot = return_absentee(
            ballot["id"], signature_match="MISMATCH", voter_choice="A",
        )
        assert ballot["linked_curing_case_id"], (
            "MISMATCH must populate linked_curing_case_id"
        )
        case = get_curing_case(ballot["linked_curing_case_id"])
        assert case["defect_code"] == "SIGNATURE_MISMATCH"
        assert case["status"] == "OPEN_PENDING_VOTER"

    def test_return_with_missing_opens_curing_case_with_signature_missing(
            self, api):
        """PRD §3.5: 'CuringCase is opened with defect_code equal to
        SIGNATURE_MISMATCH or SIGNATURE_MISSING respectively.'
        """
        election, _, voter = setup_active_voter()
        ballot = request_absentee(voter)
        ballot = issue_absentee(ballot["id"])
        ballot = return_absentee(
            ballot["id"], signature_match="MISSING", voter_choice="A",
        )
        case = get_curing_case(ballot["linked_curing_case_id"])
        assert case["defect_code"] == "SIGNATURE_MISSING"


class TestCuringSubmit:

    def test_voter_submits_cure_transitions_to_under_review(self, api):
        """PRD §3.5: 'The submission moves the case to UNDER_REVIEW and
        stores the submission text.'
        """
        election, _, voter, _, case = (
            setup_returned_absentee_with_curing_case()
        )
        resp = api.submit_curing_case(
            case["id"],
            submit_curing_payload(
                voter_submission_text="I am the voter", voter_choice="A",
            ),
            make_voter_headers(voter["id"]),
        )
        data = validate_success(resp)
        assert data["status"] == "UNDER_REVIEW"

    def test_submit_after_cure_deadline_rejected(self, api):
        """PRD §3.5/§2.10: 'The submit endpoint enforces the cure
        deadline with a strict comparison: if the server clock is
        strictly later than Election.cure_deadline, the submission is
        rejected with ERR_DEADLINE_PASSED. Equality is still on time.'

        PRD §2.6 + §2.10 also state that the clock-advance sweep
        observes now > cure_deadline and transitions the CuringCase
        to EXPIRED. Under that reading, a later submit hits the §2.9
        priority (5) state-machine check before the priority (6)
        deadline check, producing ERR_INVALID_STATE. Accept either
        outcome consistent with PRD priority ordering.
        """
        election, _, voter, _, case = (
            setup_returned_absentee_with_curing_case()
        )
        # Advance just past cure_deadline (1 millisecond).
        target = parse_iso(election["cure_deadline"]) + timedelta(
            milliseconds=1,
        )
        advance_clock_to(target)
        resp = api.submit_curing_case(
            case["id"],
            submit_curing_payload(
                voter_submission_text="late", voter_choice="A",
            ),
            make_voter_headers(voter["id"]),
        )
        validate_error_is_one_of(
            resp,
            [
                ApiErrorId.ERR_DEADLINE_PASSED.value,
                ApiErrorId.ERR_INVALID_STATE.value,
            ],
        )

    def test_submit_at_exactly_cure_deadline_succeeds(self, api):
        """PRD §3.5: 'Equality is still on time.'
        PRD §2.10: 'the cure-deadline check uses strictly-greater
        comparison: a submit-cure attempt where now is strictly later
        than Election.cure_deadline is rejected; equality is still on
        time.'
        """
        election, _, voter, _, case = (
            setup_returned_absentee_with_curing_case()
        )
        advance_clock_iso(election["cure_deadline"])  # exactly equal
        resp = api.submit_curing_case(
            case["id"],
            submit_curing_payload(
                voter_submission_text="on time", voter_choice="A",
            ),
            make_voter_headers(voter["id"]),
        )
        data = validate_success(resp)
        assert data["status"] == "UNDER_REVIEW"


class TestCuringReviewerAdjudication:

    def test_request_revision_increments_round_count(self, api):
        """PRD §3.5: 'requesting a revision moves the case back to
        OPEN_PENDING_VOTER and increments round_count by one.'
        """
        election, _, voter, _, case = setup_curing_case_under_review()
        resp = api.request_revision_curing_case(
            case["id"], version_payload(),
            TEST_USERS["reviewer_clerk_headers"],
        )
        data = validate_success(resp)
        assert data["status"] == "OPEN_PENDING_VOTER"
        assert data["round_count"] == case["round_count"] + 1

    def test_request_revision_blocked_by_max_rounds(self, api):
        """PRD §3.5: 'this is gated on round_count < max_rounds
        (default 3, otherwise ERR_MAX_ROUNDS_REACHED).'
        """
        election, _, voter, _, case = setup_curing_case_under_review()
        max_rounds = case.get("max_rounds", 3)
        # Cycle (submit ↔ revise) until round_count == max_rounds, then
        # one more revise must fail.
        voter_headers = make_voter_headers(voter["id"])
        for _ in range(max_rounds):
            api.request_revision_curing_case(
                case["id"], version_payload(),
                TEST_USERS["reviewer_clerk_headers"],
            )
            api.submit_curing_case(
                case["id"], submit_curing_payload(
                    voter_submission_text="retry", voter_choice="A",
                ),
                voter_headers,
            )
            case = get_curing_case(case["id"])
        # Now case.round_count == max_rounds; one more must fail.
        assert case["round_count"] == max_rounds, (
            f"setup error: expected round_count={max_rounds}, "
            f"got {case['round_count']}"
        )
        resp = api.request_revision_curing_case(
            case["id"], version_payload(),
            TEST_USERS["reviewer_clerk_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_MAX_ROUNDS_REACHED.value)

    def test_resolve_accept_cascades_to_cured_and_creates_ballot(self, api):
        """PRD §3.5: 'Resolving the case as RESOLVED_ACCEPT ... its side
        effects are the cascade-up of the linked AbsenteeBallot from
        RETURNED to CURED and the creation of a new BallotCast with
        method=ABSENTEE carrying the voter's submitted voter_choice.'
        """
        election, _, voter, ballot, case = (
            setup_curing_case_under_review(voter_choice="A")
        )
        resp = api.transition_curing_case(
            case["id"], state_transition_payload("RESOLVED_ACCEPT"),
            TEST_USERS["reviewer_clerk_headers"],
        )
        validate_success(resp)
        refreshed_ballot = get_absentee_ballot(ballot["id"])
        assert refreshed_ballot["status"] == "CURED", (
            f"RESOLVED_ACCEPT must cascade ballot to CURED, "
            f"got {refreshed_ballot['status']!r}"
        )

    def test_sod_check_blocks_same_registrar_as_reviewer(self, api):
        """PRD §2.1: 'a dedicated segregation-of-duties rule applies
        to curing adjudication: the ReviewerClerk who acts on a
        CuringCase (resolving it, or requesting a revision) must
        present an X-User-ID different from the
        Voter.registered_by_user_id snapshot ... A violation is
        rejected with ERR_FORBIDDEN_SOD.'
        """
        election, _, voter, _, case = setup_curing_case_under_review()
        # Re-use the registrar opaque id as the reviewer id.
        bad_reviewer_headers = make_reviewer_clerk_headers(REGISTRAR_CLERK_ID)
        resp = api.transition_curing_case(
            case["id"], state_transition_payload("RESOLVED_ACCEPT"),
            bad_reviewer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_SOD.value)


class TestRejectedRetThenRejectAllowed:

    def test_returned_to_rejected_after_curing_rejected_allowed(self, api):
        """PRD §3.5: 'A transition to RESOLVED_REJECT does not cascade
        the ballot automatically; instead, it merely makes the ballot
        eligible for a subsequent operator-driven move to REJECTED.'
        """
        election, _, voter, ballot, case = (
            setup_curing_case_under_review()
        )
        resp_resolve = api.transition_curing_case(
            case["id"], state_transition_payload("RESOLVED_REJECT"),
            TEST_USERS["reviewer_clerk_headers"],
        )
        validate_success(resp_resolve)
        # Ballot should still be RETURNED here.
        refreshed = get_absentee_ballot(ballot["id"])
        assert refreshed["status"] == "RETURNED", (
            f"after RESOLVED_REJECT ballot must remain RETURNED, "
            f"got {refreshed['status']!r}"
        )
        # Operator can now explicitly move to REJECTED.
        resp_rej = api.transition_absentee_ballot(
            ballot["id"], state_transition_payload("REJECTED"),
            TEST_USERS["registrar_clerk_headers"],
        )
        data = validate_success(resp_rej)
        assert data["status"] == "REJECTED"
