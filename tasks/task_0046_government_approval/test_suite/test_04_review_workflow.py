"""Joint-review workflow: review-task decisions, opinion aggregation,
SERIAL stage ordering, withdrawal, and approval/rejection cascades.

Covers PRD §3.6 (Joint-Review Loop), §3.8 (Aggregation), parts of §3.4
(withdraw), §2.5 (cascades).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    APPLICATION_TERMINAL_STATES,
    ApiErrorId,
    api_client,
    decide,
    decide_review_task_payload,
    drive_to_under_review,
    get_application,
    get_success_data,
    issue_correction_for_primary_material,
    list_review_tasks,
    make_applicant_headers,
    setup_application_under_review_parallel,
    setup_application_under_review_serial,
    setup_application_under_review_single_dept,
    submit_application,
    TEST_USERS,
    unique_applicant_id,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


# ===========================================================================
# Single-stage SERIAL: AGREED -> APPROVED, DISAGREED -> REJECTED
# ===========================================================================
class TestSingleStageOutcomes:
    def test_single_stage_agreed_drives_application_to_approved(self, api):
        """PRD §3.8: "Under SERIAL routing ... If every task has reached
        AGREED, the result is AGREED." PRD §3.8: "When the aggregator
        returns AGREED, the application transitions from UNDER_REVIEW to
        APPROVED in the same request."

        Claim: an AGREED on the only SERIAL stage flips Application.review_status
        to APPROVED.
        """
        ctx = setup_application_under_review_single_dept()
        task = ctx["review_tasks"][0]
        decide(task["id"], "AGREED", ctx["reviewer_headers"])
        refreshed = get_application(ctx["application"]["id"])
        assert refreshed["review_status"] == "APPROVED"

    def test_single_stage_disagreed_drives_application_to_rejected(self, api):
        """PRD §3.8: "Under SERIAL routing, a single DISAGREED task
        short-circuits the result to DISAGREED immediately." PRD §3.8:
        "When the aggregator returns DISAGREED, the application
        transitions from UNDER_REVIEW to REJECTED."

        Claim: a DISAGREED on the only SERIAL stage flips
        Application.review_status to REJECTED.
        """
        ctx = setup_application_under_review_single_dept()
        task = ctx["review_tasks"][0]
        decide(task["id"], "DISAGREED", ctx["reviewer_headers"])
        refreshed = get_application(ctx["application"]["id"])
        assert refreshed["review_status"] == "REJECTED"


# ===========================================================================
# Multi-stage SERIAL ordering (PRD §3.2)
# ===========================================================================
class TestSerialStageOrdering:
    def test_serial_decide_later_stage_first_yields_review_out_of_order(
        self, api,
    ):
        """PRD §3.2: "For SERIAL routing only the stage_index 0 task
        transitions from PENDING to IN_PROGRESS immediately; later stages
        stay PENDING and become IN_PROGRESS one at a time as the
        predecessor stage transitions to AGREED. Any attempt to decide a
        later stage before its predecessor has agreed is rejected with
        ERR_REVIEW_OUT_OF_ORDER."

        PRD §2.7 priority places "target-resource state" strictly before
        "SERIAL-routing stage ordering for review-task decisions". Since
        a later-stage SERIAL task is in PENDING (not IN_PROGRESS), a
        faithful priority-respecting reader may surface ERR_INVALID_STATE
        on the state precondition before reaching the SERIAL-ordering
        check that names ERR_REVIEW_OUT_OF_ORDER. Both readings are
        PRD-faithful, so accept either.

        Claim: in a 2-stage SERIAL routing, deciding stage_index=1 while
        stage 0 is still IN_PROGRESS -> ERR_REVIEW_OUT_OF_ORDER (per §3.2)
        or ERR_INVALID_STATE (per §2.7 priority over PENDING task state).
        """
        ctx = setup_application_under_review_serial(department_count=2)
        tasks = ctx["review_tasks"]
        stage1 = next(t for t in tasks if t["stage_index"] == 1)
        # Reviewer for stage 1's department.
        reviewer_headers = ctx["reviewer_headers_by_dept_id"][stage1["department_id"]]
        resp = api.decide_review_task(
            stage1["id"],
            decide_review_task_payload("AGREED", "ok", include_opinion=True),
            reviewer_headers,
        )
        validate_error_is_one_of(
            resp,
            [ApiErrorId.ERR_REVIEW_OUT_OF_ORDER, ApiErrorId.ERR_INVALID_STATE],
        )

    def test_serial_agreed_promotes_next_stage_to_in_progress(self, api):
        """PRD §3.6: "For SERIAL routing, an AGREED decision on the
        current stage promotes the next stage's task from PENDING to
        IN_PROGRESS and arms its stage_due_at per §2.9."

        Claim: AGREED on stage 0 of a 2-stage SERIAL routing flips
        stage 1 from PENDING to IN_PROGRESS.
        """
        ctx = setup_application_under_review_serial(department_count=2)
        tasks = ctx["review_tasks"]
        stage0 = next(t for t in tasks if t["stage_index"] == 0)
        stage0_headers = ctx["reviewer_headers_by_dept_id"][stage0["department_id"]]
        decide(stage0["id"], "AGREED", stage0_headers)
        # Re-list and check stage 1.
        refreshed = list_review_tasks(
            ctx["application"]["id"],
            TEST_USERS["platform_admin_headers"],
        )
        stage1 = next(t for t in refreshed if t["stage_index"] == 1)
        assert stage1["status"] == "IN_PROGRESS"


# ===========================================================================
# PARALLEL aggregation rules (PRD §3.8)
# ===========================================================================
class TestParallelAggregationOutcomes:
    def test_parallel_all_agree_requires_all_agreed_for_approval(self, api):
        """PRD §3.8: "Under PARALLEL routing with aggregation_rule
        ALL_AGREE ... if every task has reached AGREED the result is
        AGREED."

        Claim: PARALLEL/ALL_AGREE on 2 stages requires both tasks
        AGREED for Application -> APPROVED.
        """
        ctx = setup_application_under_review_parallel(
            department_count=2, aggregation_rule="ALL_AGREE",
        )
        tasks = ctx["review_tasks"]
        # First AGREED -- still PENDING aggregator.
        first = tasks[0]
        first_headers = ctx["reviewer_headers_by_dept_id"][first["department_id"]]
        decide(first["id"], "AGREED", first_headers)
        mid = get_application(ctx["application"]["id"])
        assert mid["review_status"] == "UNDER_REVIEW"
        # Second AGREED -- aggregator returns AGREED.
        second = tasks[1]
        second_headers = ctx["reviewer_headers_by_dept_id"][second["department_id"]]
        decide(second["id"], "AGREED", second_headers)
        final = get_application(ctx["application"]["id"])
        assert final["review_status"] == "APPROVED"

    def test_parallel_all_agree_one_disagreed_short_circuits_to_rejected(
        self, api,
    ):
        """PRD §3.8: "Under PARALLEL routing with aggregation_rule
        ALL_AGREE, a single DISAGREED task short-circuits to DISAGREED."

        Claim: PARALLEL/ALL_AGREE: a DISAGREED on any stage immediately
        drives Application -> REJECTED, even if other stages are still
        IN_PROGRESS.
        """
        ctx = setup_application_under_review_parallel(
            department_count=2, aggregation_rule="ALL_AGREE",
        )
        first = ctx["review_tasks"][0]
        first_headers = ctx["reviewer_headers_by_dept_id"][first["department_id"]]
        decide(first["id"], "DISAGREED", first_headers)
        refreshed = get_application(ctx["application"]["id"])
        assert refreshed["review_status"] == "REJECTED"


# ===========================================================================
# Decision guards (PRD §3.6)
# ===========================================================================
class TestDecisionGuards:
    def test_decide_with_open_correction_yields_invalid_state(self, api):
        """PRD §3.6: "The decision is rejected with ERR_INVALID_STATE
        if the application is not currently UNDER_REVIEW, or if any OPEN
        CorrectionNotice exists for the application -- open corrections
        pause every IN_PROGRESS task."

        Claim: deciding an IN_PROGRESS task while a CorrectionNotice on
        the same application is OPEN -> ERR_INVALID_STATE.

        # difficulty: cross_entity_state_dependency/review_task_decide_blocked_by_open_correction_notice_pair
        """
        ctx = setup_application_under_review_single_dept()
        notice = issue_correction_for_primary_material(ctx=ctx)
        assert notice["status"] == "OPEN"
        task = ctx["review_tasks"][0]
        resp = api.decide_review_task(
            task["id"],
            decide_review_task_payload("AGREED", "ok", include_opinion=True),
            ctx["reviewer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_reviewer_from_other_department_cannot_decide(self, api):
        """PRD §2.1: "a reviewer may only act on a ReviewTask whose
        department_id equals X-User-ID."

        Claim: a Reviewer whose Department.id differs from the task's
        department_id is rejected with ERR_FORBIDDEN.
        """
        from test_helpers import (
            create_department,
            make_reviewer_headers,
        )
        ctx = setup_application_under_review_single_dept()
        other_dept = create_department()
        other_reviewer = make_reviewer_headers(other_dept["id"])
        task = ctx["review_tasks"][0]
        resp = api.decide_review_task(
            task["id"],
            decide_review_task_payload("AGREED", "ok", include_opinion=True),
            other_reviewer,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


# ===========================================================================
# Withdrawal (PRD §3.4)
# ===========================================================================
class TestWithdrawal:
    def test_withdraw_from_submitted_is_unconditional(self, api):
        """PRD §3.4: "withdrawal from SUBMITTED is unconditional."

        Claim: an Applicant withdrawing while review_status==SUBMITTED
        flips it to WITHDRAWN.
        """
        from test_helpers import setup_single_department_published_version
        ctx = setup_single_department_published_version(fee_amount_cents=0)
        application, applicant_headers, _id = submit_application(ctx=ctx)
        # Application is in SUBMITTED (no IDENTITY/PAYMENT events yet).
        resp = api.withdraw_application(application["id"], applicant_headers)
        validate_success(resp)
        refreshed = get_application(application["id"])
        assert refreshed["review_status"] == "WITHDRAWN"

    def test_withdraw_from_under_review_with_no_disagreed_succeeds(self, api):
        """PRD §3.4: "withdrawal from UNDER_REVIEW requires that no
        ReviewTask has yet reached DISAGREED -- this prevents an
        applicant from dodging an imminent rejection. Both withdrawal
        paths flip the application's review_status to WITHDRAWN, cascade
        every non-terminal ReviewTask to SKIPPED."

        Claim: a withdraw while UNDER_REVIEW with no DISAGREED tasks
        flips review_status to WITHDRAWN and cascades every non-terminal
        ReviewTask to SKIPPED.

        # difficulty: compensating_invariant/review_task_capacity_invariant_on_application_terminal
        """
        ctx = setup_application_under_review_parallel(
            department_count=3, aggregation_rule="ALL_AGREE",
        )
        # All three tasks IN_PROGRESS, none DISAGREED.
        resp = api.withdraw_application(
            ctx["application"]["id"], ctx["applicant_headers"],
        )
        validate_success(resp)
        refreshed = get_application(ctx["application"]["id"])
        assert refreshed["review_status"] == "WITHDRAWN"
        # Conservation invariant: count of non-terminal ReviewTasks == 0.
        tasks = list_review_tasks(
            ctx["application"]["id"], TEST_USERS["platform_admin_headers"],
        )
        non_terminal = [t for t in tasks if t["status"]
                        not in {"AGREED", "DISAGREED", "SKIPPED"}]
        assert non_terminal == [], (
            f"Non-terminal tasks remain after WITHDRAWN: {non_terminal}"
        )
        # Specifically each was IN_PROGRESS -> SKIPPED.
        skipped_count = sum(1 for t in tasks if t["status"] == "SKIPPED")
        assert skipped_count == 3

    def test_withdraw_after_disagreed_is_rejected(self, api):
        """PRD §3.4: "withdrawal from UNDER_REVIEW requires that no
        ReviewTask has yet reached DISAGREED -- this prevents an
        applicant from dodging an imminent rejection."

        Claim: an Applicant attempting to withdraw after a stage has
        DISAGREED is rejected with ERR_INVALID_STATE.
        """
        ctx = setup_application_under_review_parallel(
            department_count=2, aggregation_rule="MAJORITY",
        )
        # Cause one DISAGREED but not enough to terminate (MAJORITY waits
        # for both decisions).
        first = ctx["review_tasks"][0]
        first_headers = ctx["reviewer_headers_by_dept_id"][first["department_id"]]
        decide(first["id"], "DISAGREED", first_headers)
        # Application should still be UNDER_REVIEW under MAJORITY rule.
        mid = get_application(ctx["application"]["id"])
        assert mid["review_status"] == "UNDER_REVIEW"
        resp = api.withdraw_application(
            ctx["application"]["id"], ctx["applicant_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_withdraw_terminal_application_yields_invalid_state(self, api):
        """PRD §3.4: "Withdrawal of an application that has already
        reached a terminal state is rejected with ERR_INVALID_STATE."

        Claim: withdrawing an APPROVED Application -> ERR_INVALID_STATE.
        """
        ctx = setup_application_under_review_single_dept()
        decide(ctx["review_tasks"][0]["id"], "AGREED", ctx["reviewer_headers"])
        refreshed = get_application(ctx["application"]["id"])
        assert refreshed["review_status"] == "APPROVED"
        resp = api.withdraw_application(
            ctx["application"]["id"], ctx["applicant_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


# ===========================================================================
# Refund cascade (PRD §3.4, §3.8)
# ===========================================================================
class TestRefundCascade:
    def test_rejected_paid_application_is_refunded(self, api):
        """PRD §3.8: "When the aggregator returns DISAGREED, the
        application transitions from UNDER_REVIEW to REJECTED; if
        payment_status is PAID and the pinned fee_amount_cents is greater
        than 0, the payment is refunded by setting payment_status to
        REFUNDED."

        Claim: a fee>0 application that is rejected ends with
        payment_status=='REFUNDED'.

        # difficulty: compensating_invariant/payment_refund_invariant_on_application_rejection
        """
        ctx = setup_application_under_review_single_dept(fee_amount_cents=1000)
        decide(ctx["review_tasks"][0]["id"], "DISAGREED", ctx["reviewer_headers"])
        refreshed = get_application(ctx["application"]["id"])
        assert refreshed["review_status"] == "REJECTED"
        assert refreshed["payment_status"] == "REFUNDED"

    def test_withdrawn_paid_application_is_refunded(self, api):
        """PRD §3.4: "Both withdrawal paths flip the application's
        review_status to WITHDRAWN, cascade every non-terminal ReviewTask
        to SKIPPED, and -- when payment_status is PAID and the pinned
        version's fee_amount_cents is greater than 0 -- refund the
        payment by setting payment_status to REFUNDED."

        Claim: a fee>0 withdrawn application ends with
        payment_status=='REFUNDED'.
        """
        ctx = setup_application_under_review_single_dept(fee_amount_cents=1000)
        resp = api.withdraw_application(
            ctx["application"]["id"], ctx["applicant_headers"],
        )
        validate_success(resp)
        refreshed = get_application(ctx["application"]["id"])
        assert refreshed["review_status"] == "WITHDRAWN"
        assert refreshed["payment_status"] == "REFUNDED"
