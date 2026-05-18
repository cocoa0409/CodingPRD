"""Architectural Review (ACC) — PRD §3.4.

Covers: submission, begin-review, voting, withdrawal, owner ownership.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_acc_request,
    begin_review_acc_request,
    create_acc_request_payload,
    create_member,
    create_unit,
    get_acc_request,
    make_member_headers,
    setup_single_unit_roster,
    setup_two_acc_requests_in_review,
    submit_acc_request,
    TEST_USERS,
    validate_error,
    validate_success,
    version_payload,
)


class TestACCRequestSubmission:

    def test_owner_submits_request_returns_submitted(self, api):
        """PRD §3.4: "A Member initiates the request by submitting
        unit_id, category, and description. The submitter's X-User-ID
        MUST equal the unit's owner_member_id at submission time."

        Claim: an owner submitting an ACC request gets back the request
        in SUBMITTED status with yes_votes=0 and no_votes=0.
        """
        member, unit = setup_single_unit_roster()
        resp = api.create_acc_request(
            create_acc_request_payload(
                unit_id=unit["id"], category="LANDSCAPING",
                description="install raised beds",
            ),
            make_member_headers(member["id"]),
        )
        body = validate_success(resp, expected_status=201)
        assert_acc_request(body)
        assert body["status"] == "SUBMITTED"
        assert body["yes_votes"] == 0
        assert body["no_votes"] == 0
        assert body["unit_id"] == unit["id"]
        assert body["submitted_by_member_id"] == member["id"]

    def test_non_owner_submitting_rejected(self, api):
        """PRD §3.4: "The submitter's X-User-ID MUST equal the unit's
        owner_member_id at submission time."

        Claim: an X-User-ID that does not match the unit's
        owner_member_id is rejected. PRD §2.1 frames this as forbidden
        on entity-backed roles.
        """
        owner, unit = setup_single_unit_roster()
        # Some other member tries to submit on the unit.
        impostor = create_member()
        resp = api.create_acc_request(
            create_acc_request_payload(
                unit_id=unit["id"], category="LANDSCAPING",
            ),
            make_member_headers(impostor["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


class TestACCRequestBeginReview:

    def test_begin_review_with_overdue_owner_returns_owner_delinquent(self, api):
        """PRD §3.4: "the unit's owner — identified by
        submitted_by_member_id — MUST currently have
        Member.total_overdue_amount_cents equal to zero; a delinquent
        owner is barred with ERR_OWNER_DELINQUENT (HTTP 409)."

        Claim: when the owner has total_overdue > 0 at begin-review
        time, the transition fails with ERR_OWNER_DELINQUENT.
        """
        from test_helpers import (
            setup_issued_cycle, advance_clock_to, parse_iso,
        )
        member, unit, cycle = setup_issued_cycle(total_levy_cents=100_000)
        # Submit ACC request BEFORE cycle goes overdue (owner total
        # overdue is still 0 at submission — submission only requires
        # ownership, not overdue == 0).
        req = submit_acc_request(unit["id"], member["id"])
        # Now push the charge into OVERDUE so the owner accrues overdue.
        due = parse_iso(cycle["due_date"])
        advance_clock_to(due + timedelta(days=1, seconds=1))
        # Attempt to begin review — owner is now delinquent.
        resp = api.begin_review_acc_request(
            req["id"], version_payload(req.get("version", 1)),
            TEST_USERS["secretary_role_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_OWNER_DELINQUENT.value)

    def test_begin_review_with_special_assessment_posture_blocked(self, api):
        """PRD §3.4: "the most recently adopted ReserveStudy MUST NOT
        have posture == SPECIAL_ASSESSMENT_REQUIRED; if the community
        is under a special-assessment posture, discretionary
        modifications are paused for everyone and begin-review is
        rejected with ERR_RESERVE_POSTURE_BLOCKS_ACC (HTTP 409)."

        Claim: when latest ADOPTED ReserveStudy has posture
        SPECIAL_ASSESSMENT_REQUIRED, begin-review is rejected with
        ERR_RESERVE_POSTURE_BLOCKS_ACC.
        """
        from test_helpers import setup_adopted_special_assessment_study
        owner, unit = setup_single_unit_roster()
        req = submit_acc_request(unit["id"], owner["id"])
        # Adopt a SPECIAL_ASSESSMENT_REQUIRED study.
        study = setup_adopted_special_assessment_study()
        assert study["posture"] == "SPECIAL_ASSESSMENT_REQUIRED"
        resp = api.begin_review_acc_request(
            req["id"], version_payload(req.get("version", 1)),
            TEST_USERS["secretary_role_headers"],
        )
        validate_error(
            resp, ApiErrorId.ERR_RESERVE_POSTURE_BLOCKS_ACC.value,
        )

    def test_begin_review_happy_path_returns_under_review(self, api):
        """PRD §3.4: "A SecretaryRole then begins review, advancing the
        request from SUBMITTED to UNDER_REVIEW."

        Claim: begin-review on a SUBMITTED request whose owner has 0
        overdue and no SPECIAL_ASSESSMENT posture in effect returns
        status=UNDER_REVIEW.
        """
        owner, unit = setup_single_unit_roster()
        req = submit_acc_request(unit["id"], owner["id"])
        resp = api.begin_review_acc_request(
            req["id"], version_payload(req.get("version", 1)),
            TEST_USERS["secretary_role_headers"],
        )
        body = validate_success(resp, expected_status=200)
        assert body["status"] == "UNDER_REVIEW"

    def test_begin_review_on_non_submitted_returns_invalid_state(self, api):
        """PRD §2.10: "Beginning review on an ACCRequest that is
        already UNDER_REVIEW (because the deemed-decision deadline
        assignment is idempotent) is treated as a state-transition no-
        op only if the prior status was SUBMITTED; calling it on any
        other status returns ERR_INVALID_STATE."

        Claim: begin-review on a WITHDRAWN request returns
        ERR_INVALID_STATE.
        """
        owner, unit = setup_single_unit_roster()
        req = submit_acc_request(unit["id"], owner["id"])
        # Withdraw the request.
        api.withdraw_acc_request(req["id"], make_member_headers(owner["id"]))
        # Attempt begin-review on the WITHDRAWN one.
        resp = api.begin_review_acc_request(
            req["id"], version_payload(req.get("version", 1)),
            TEST_USERS["secretary_role_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


class TestACCWithdrawal:

    def test_owner_withdraws_submitted_request(self, api):
        """PRD §3.4: "From SUBMITTED the withdrawal needs only the
        caller-identity check ... A successful withdrawal transitions
        the request to WITHDRAWN".

        Claim: DELETE /hoa/acc-requests/{id} by the owner of a
        SUBMITTED request returns status=WITHDRAWN.
        """
        owner, unit = setup_single_unit_roster()
        req = submit_acc_request(unit["id"], owner["id"])
        resp = api.withdraw_acc_request(
            req["id"], make_member_headers(owner["id"]),
        )
        body = validate_success(resp, expected_status=200)
        assert body["status"] == "WITHDRAWN"

    def test_non_owner_withdrawal_returns_forbidden(self, api):
        """PRD §3.4: "Withdrawal is the Member's prerogative — the
        caller's X-User-ID MUST equal submitted_by_member_id."

        Claim: DELETE by someone other than the submitter fails (PRD
        §2.1 forbids; specific error_id not named beyond identity rule).
        """
        owner, unit = setup_single_unit_roster()
        req = submit_acc_request(unit["id"], owner["id"])
        impostor = create_member()
        resp = api.withdraw_acc_request(
            req["id"], make_member_headers(impostor["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)
