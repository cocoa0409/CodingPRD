"""Correction-notice lifecycle: issuance, resubmission, expiry,
max-rounds enforcement, deadline arithmetic.

Covers PRD §3.6 (correction loop), §2.9 (working-day arithmetic),
§2.14 (test clock + sweep).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock,
    api_client,
    assert_correction_notice,
    decide,
    deficiency_entry,
    drive_to_under_review,
    get_application,
    get_success_data,
    issue_correction_for_primary_material,
    issue_correction_notice,
    issue_correction_notice_payload,
    list_correction_notices,
    list_review_tasks,
    make_applicant_headers,
    parse_iso,
    resubmit_correction,
    resubmit_correction_payload,
    resubmit_primary_material,
    run_sweep,
    setup_application_at_correction_round,
    setup_application_under_review_single_dept,
    submit_application,
    submitted_material_entry,
    TEST_USERS,
    unique_applicant_id,
    validate_error,
    validate_success,
    WORKING_DAY_SECONDS,
)


# ===========================================================================
# Issuance shape (PRD §3.6)
# ===========================================================================
class TestCorrectionNoticeIssuance:
    def test_issue_correction_round_number_starts_at_one(self, api):
        """PRD §3.6: "On success, a new CorrectionNotice row is created
        with round_number equal to the application's correction_round
        plus one, the application's correction_round is incremented by
        one, the application's review_status flips to AWAITING_CORRECTION."

        Claim: first correction issuance creates a notice with
        round_number==1 and Application.correction_round==1.
        """
        ctx = setup_application_under_review_single_dept()
        notice = issue_correction_for_primary_material(ctx=ctx)
        assert_correction_notice(notice)
        assert notice["round_number"] == 1
        refreshed = get_application(ctx["application"]["id"])
        assert refreshed["correction_round"] == 1
        assert refreshed["review_status"] == "AWAITING_CORRECTION"

    def test_issue_correction_due_at_uses_working_day_arithmetic(self, api):
        """PRD §2.9: "correction_window_days (default 7, range 1-30) on
        each MatterVersion defines, in working days, how long an
        applicant has to resubmit a given CorrectionNotice. The resulting
        due_at is issued_at plus that many working days converted into
        seconds -- so a window of 7 working days is 201,600 seconds added
        to issued_at."

        Claim: due_at == issued_at + correction_window_days * 28800 s.
        """
        # Use correction_window_days=7 for the named 201,600s expectation.
        ctx = setup_application_under_review_single_dept(
            correction_window_days=7,
        )
        notice = issue_correction_for_primary_material(ctx=ctx)
        issued = parse_iso(notice["issued_at"])
        due = parse_iso(notice["due_at"])
        diff_seconds = int((due - issued).total_seconds())
        assert diff_seconds == 7 * WORKING_DAY_SECONDS, (
            f"due_at - issued_at expected {7 * WORKING_DAY_SECONDS}s, "
            f"got {diff_seconds}s"
        )

    def test_issue_with_empty_deficiencies_yields_err_deficiency_invalid(
        self, api,
    ):
        """PRD §3.6: "The issuance is rejected with ERR_DEFICIENCY_INVALID
        if deficiencies is empty or if any material_template_id is not
        present in the pinned version's required_material_template_ids."

        Claim: deficiencies=[] -> ERR_DEFICIENCY_INVALID.

        # difficulty: boundary_precision_check/empty_deficiency_list_rejection_on_correction_endpoint
        """
        ctx = setup_application_under_review_single_dept()
        task = ctx["review_tasks"][0]
        payload = issue_correction_notice_payload(
            deficiencies=[], issued_by_review_task_id=task["id"],
        )
        resp = api.issue_correction_notice(
            ctx["application"]["id"], payload, ctx["reviewer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_DEFICIENCY_INVALID)

    def test_issue_with_one_deficiency_succeeds(self, api):
        """PRD §3.6: "The issuance request takes a non-empty deficiencies
        array -- each entry naming a material_template_id and a reason
        -- and an issued_by_review_task_id identifying the reviewer's
        own task." PRD §3.6: "round_number equal to the application's
        correction_round plus one."

        Claim: a single-entry deficiencies array yields a 201 with
        round_number==1 (boundary partner of the empty-deficiency test).

        # difficulty: boundary_precision_check/empty_deficiency_list_rejection_on_correction_endpoint
        """
        ctx = setup_application_under_review_single_dept()
        task = ctx["review_tasks"][0]
        payload = issue_correction_notice_payload(
            deficiencies=[deficiency_entry(ctx["material_template"]["id"], "missing")],
            issued_by_review_task_id=task["id"],
        )
        resp = api.issue_correction_notice(
            ctx["application"]["id"], payload, ctx["reviewer_headers"],
        )
        data = validate_success(resp, expected_status=201)
        assert data["round_number"] == 1


# ===========================================================================
# Round budget (PRD §3.6)
# ===========================================================================
class TestMaxRounds:
    def test_third_correction_after_two_rounds_yields_err_max_rounds_reached(
        self, api,
    ):
        """PRD §3.6: "with ERR_MAX_ROUNDS_REACHED if correction_round
        already equals the pinned version's max_correction_rounds."

        Claim: with max_correction_rounds=2, after two complete
        round-trips, a third correction attempt is rejected with
        ERR_MAX_ROUNDS_REACHED.

        # difficulty: non_linear_state_machine/application_correction_revision_loop_cyclic
        """
        ctx = setup_application_at_correction_round(
            target_round=2,
            max_correction_rounds=2,
            fee_amount_cents=1000,
        )
        # Application should be back UNDER_REVIEW with correction_round==2.
        refreshed = get_application(ctx["application"]["id"])
        assert refreshed["review_status"] == "UNDER_REVIEW"
        assert refreshed["correction_round"] == 2
        # Third issuance attempt.
        tasks = list_review_tasks(
            ctx["application"]["id"], ctx["reviewer_headers"],
        )
        in_progress = next(t for t in tasks if t["status"] == "IN_PROGRESS")
        payload = issue_correction_notice_payload(
            deficiencies=[deficiency_entry(ctx["material_template"]["id"], "again")],
            issued_by_review_task_id=in_progress["id"],
        )
        resp = api.issue_correction_notice(
            ctx["application"]["id"], payload, ctx["reviewer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_MAX_ROUNDS_REACHED)


# ===========================================================================
# Correction-cycle revision loop (cyclic state) (PRD §3.6)
# ===========================================================================
class TestCorrectionCycleRevisionLoop:
    def test_two_round_trip_returns_to_under_review(self, api):
        """PRD §3.6: "every previously paused ReviewTask resumes at the
        same status it held when the notice was issued, and the
        application's review_status flips back to UNDER_REVIEW."

        Claim: after two complete (issue -> resubmit) round-trips with
        max_correction_rounds=2, Application returns to UNDER_REVIEW
        with correction_round==2.

        # difficulty: non_linear_state_machine/application_correction_revision_loop_cyclic
        """
        ctx = setup_application_at_correction_round(
            target_round=2,
            max_correction_rounds=2,
            fee_amount_cents=1000,
        )
        refreshed = get_application(ctx["application"]["id"])
        assert refreshed["review_status"] == "UNDER_REVIEW"
        assert refreshed["correction_round"] == 2


# ===========================================================================
# Resubmit guards (PRD §3.6)
# ===========================================================================
class TestResubmitGuards:
    def test_resubmit_after_due_at_yields_err_correction_expired(self, api):
        """PRD §3.6: "It is rejected with ERR_CORRECTION_EXPIRED if the
        current server time is past the notice's due_at." PRD §2.11:
        "When an applicant resubmits at the boundary while a system
        sweep marks the same CorrectionNotice EXPIRED, the resubmit
        succeeds only if its server-side now() is at or before due_at;
        otherwise it is rejected with ERR_CORRECTION_EXPIRED."

        Claim: advancing the clock past due_at + 1s, then resubmitting,
        yields ERR_CORRECTION_EXPIRED.
        """
        ctx = setup_application_under_review_single_dept(
            correction_window_days=1,
        )
        notice = issue_correction_for_primary_material(ctx=ctx)
        # Advance well past due_at (1 working day = 28,800s; +1s buffer).
        advance_clock(WORKING_DAY_SECONDS + 1)
        materials = [submitted_material_entry(ctx["material_template"]["id"])]
        payload = resubmit_correction_payload(submitted_materials=materials)
        resp = api.resubmit_correction(
            ctx["application"]["id"], notice["id"], payload,
            ctx["applicant_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_CORRECTION_EXPIRED)

    def test_resubmit_missing_deficiency_yields_err_deficiency_unresolved(
        self, api,
    ):
        """PRD §3.6: "with ERR_DEFICIENCY_UNRESOLVED if any deficiency
        listed on the notice is not addressed by a matching entry in the
        new submitted_materials."

        Claim: a notice with one deficiency, and a resubmit whose
        submitted_materials does NOT cover it -> ERR_DEFICIENCY_UNRESOLVED.
        """
        ctx = setup_application_under_review_single_dept()
        notice = issue_correction_for_primary_material(ctx=ctx)
        payload = resubmit_correction_payload(submitted_materials=[])
        resp = api.resubmit_correction(
            ctx["application"]["id"], notice["id"], payload,
            ctx["applicant_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_DEFICIENCY_UNRESOLVED)


# ===========================================================================
# Sweep + correction expiry cascade (depth 3) (PRD §3.6, §2.14)
# ===========================================================================
class TestCorrectionExpirySweep:
    def test_sweep_after_due_at_cascades_to_rejected_and_skipped(self, api):
        """PRD §3.6: "A notice that is left OPEN past its due_at is swept
        to EXPIRED ... Expiration cascades the application from
        AWAITING_CORRECTION to REJECTED, every non-terminal ReviewTask
        is flipped to SKIPPED."

        Claim: clock-advance + sweep transforms (CorrectionNotice OPEN
        -> EXPIRED), (Application AWAITING_CORRECTION -> REJECTED), and
        (every non-terminal ReviewTask -> SKIPPED). Three-hop cascade
        from a single clock-driven trigger.

        # difficulty: transitive_cascade/correction_expiry_cascade_depth_three
        """
        ctx = setup_application_under_review_single_dept(
            correction_window_days=1,
        )
        notice = issue_correction_for_primary_material(ctx=ctx)
        # Advance clock past due_at and sweep.
        advance_clock(WORKING_DAY_SECONDS + 1)
        run_sweep()
        # Hop 1: notice EXPIRED.
        notices = list_correction_notices(
            ctx["application"]["id"], ctx["reviewer_headers"]
        )
        target_notice = next(n for n in notices if n["id"] == notice["id"])
        assert target_notice["status"] == "EXPIRED"
        # Hop 2: application REJECTED.
        refreshed = get_application(ctx["application"]["id"])
        assert refreshed["review_status"] == "REJECTED"
        # Hop 3: every non-terminal ReviewTask flipped to SKIPPED.
        tasks = list_review_tasks(
            ctx["application"]["id"], TEST_USERS["platform_admin_headers"],
        )
        non_terminal = [
            t for t in tasks
            if t["status"] not in {"AGREED", "DISAGREED", "SKIPPED"}
        ]
        assert non_terminal == []


# ===========================================================================
# Successful resubmit side effects (PRD §3.6, §3.7)
# ===========================================================================
class TestResubmitSuccessSideEffects:
    def test_resubmit_resolves_notice_and_returns_to_under_review(self, api):
        """PRD §3.6: "On success, the notice's status becomes RESOLVED,
        its resolved_at is set, the application's total_paused_seconds
        is increased by the integer number of seconds elapsed between
        issued_at and the current server time ... and the application's
        review_status flips back to UNDER_REVIEW."

        Claim: resubmit at exactly issued_at sets notice.status==RESOLVED,
        notice.resolved_at!=null, and review_status==UNDER_REVIEW.
        """
        ctx = setup_application_under_review_single_dept()
        notice = issue_correction_for_primary_material(ctx=ctx)
        resubmit_primary_material(
            ctx=ctx, correction_notice_id=notice["id"],
        )
        refreshed_notice = next(
            n for n in list_correction_notices(
                ctx["application"]["id"], ctx["reviewer_headers"]
            )
            if n["id"] == notice["id"]
        )
        assert refreshed_notice["status"] == "RESOLVED"
        assert refreshed_notice["resolved_at"] is not None
        refreshed_app = get_application(ctx["application"]["id"])
        assert refreshed_app["review_status"] == "UNDER_REVIEW"
