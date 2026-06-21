"""Difficulty queue: dual-variant calculations, combinatorial merit matrix,
round-then-sum ledger, boundary-precision checks.

Queue A (Difficulty) — rules dual_variant_calc, combinatorial_formula,
boundary_precision_check.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_cycle_payload, create_rating_band_payload, create_calibration_session_payload,
    create_comp_plan_payload,
    TEST_USERS,
    create_employee, create_open_cycle_single_band, create_review,
    drive_review_to_submitted, setup_calibrated_review_in_comp_planning,
    setup_comp_planning_with_n_calibrated_reviews, create_comp_plan_for, approve_plan,
    make_manager_headers, make_employee_headers, make_hrbp_headers,
    make_comp_approver_headers,
)

HR = TEST_USERS["hr_admin_headers"]


# ==========================================================================
# Rule: dual_variant_calc
# ==========================================================================
class TestCompositeScoreNoFeedbackVsWithFeedback:
    """Dual variant on the Review domain: identical goals, different composite
    depending on whether any feedback is SUBMITTED."""

    def test_no_feedback_fallback_collapses_to_goal_score(self, api):
        """PRD §3.5: "If there are no submitted feedback requests, the feedback
        component is set equal to the goal component, so the composite reduces to
        the goal score".

        Goal score 80, no feedback -> feedback_score = goal_score ->
        0.7*80 + 0.3*80 = 80.00.

        Design: Difficulty/dual_variant_calc/composite_score_no_feedback_vs_with_feedback
        """
        cyc = create_open_cycle_single_band()
        mgr = create_employee(full_name="Mgr", department="ENG")
        emp = create_employee(full_name="Emp", department="ENG", manager_id=mgr["id"])
        rev = create_review(cyc["id"], emp["id"], mgr["id"])
        review = drive_review_to_submitted(
            cyc["id"], rev["id"], emp["id"], mgr["id"],
            self_rating="MEETS", manager_rating="MEETS",
            goal_attainment=0.8, feedback_scores=None)
        assert review["composite_score"] == 80.00

    def test_with_feedback_blends_in(self, api):
        """PRD §3.5: "Otherwise, average the `score` values of the submitted
        requests (each on the one-to-five scale), subtract one, divide by four,
        and multiply by 100".

        Goal score 80, two SUBMITTED feedback scores 5 and 5 -> feedback_score
        100 -> 0.7*80 + 0.3*100 = 86.00, differing from the no-feedback variant.

        Design: Difficulty/dual_variant_calc/composite_score_no_feedback_vs_with_feedback
        """
        cyc = create_open_cycle_single_band()
        mgr = create_employee(full_name="Mgr", department="ENG")
        emp = create_employee(full_name="Emp", department="ENG", manager_id=mgr["id"])
        rev = create_review(cyc["id"], emp["id"], mgr["id"])
        review = drive_review_to_submitted(
            cyc["id"], rev["id"], emp["id"], mgr["id"],
            self_rating="MEETS", manager_rating="MEETS",
            goal_attainment=0.8, feedback_scores=[5, 5])
        assert review["composite_score"] == 86.00


class TestEquityTenureEligibleVsIneligible:
    """Dual variant on CompPlan/Employee: same band yields equity > 0 for a
    >=1yr-tenure employee but exactly 0 for a <1yr-tenure employee."""

    def test_tenured_employee_gets_equity(self, api):
        """PRD §3.8: "For an eligible employee, take the band-equity factor for
        the review's `final_rating` — four hundred share units for the top
        `EXCEEDS` band ... and scale it by a tenure bonus".

        EXCEEDS, tenure capped at 5yr -> raw 400*1.5 = 600, pool ample -> > 0.

        Design: Difficulty/dual_variant_calc/equity_tenure_eligible_vs_ineligible
        """
        ctx = setup_calibrated_review_in_comp_planning(
            band_label="EXCEEDS", band_merit_pct=0.10,
            equity_refresh_pool=100000, hire_date="2010-01-01T00:00:00.000Z")
        plan = create_comp_plan_for(ctx["cycle"]["id"], ctx["review"]["id"], ctx["manager"]["id"])
        assert plan["equity_refresh_units"] > 0

    def test_sub_one_year_tenure_gets_zero_equity(self, api):
        """PRD §3.8: "If that tenure is less than one year, the employee is
        ineligible and `equity_refresh_units` is zero regardless of band."

        Note: tenure < 1 year is rejected as ERR_TENURE_INELIGIBLE at create, so
        the zero-equity outcome is surfaced as that rejection.

        Design: Difficulty/dual_variant_calc/equity_tenure_eligible_vs_ineligible
        """
        ctx = setup_calibrated_review_in_comp_planning(
            band_label="EXCEEDS", band_merit_pct=0.10,
            equity_refresh_pool=100000, hire_date="2025-12-01T00:00:00.000Z")
        mgr_hdr = make_manager_headers(ctx["manager"]["id"])
        rev = get_success_data(api.get_review(ctx["review"]["id"], mgr_hdr))
        payload = create_comp_plan_payload(
            ctx["cycle"]["id"], ctx["review"]["id"], rev["version"], plan_type="MERIT_ONLY")
        res = api.create_comp_plan(payload, mgr_hdr)
        validate_error(res, "ERR_TENURE_INELIGIBLE")


# ==========================================================================
# Rule: combinatorial_formula
# ==========================================================================
class TestMeritMatrixNonlinear:
    """Mode (a): promo uplift added then clamped by min(.., MERIT_PCT_CAP)."""

    def test_promo_uplift_clamped_to_cap(self, api):
        """PRD §3.8: "add a promotion uplift of three hundredths for each band
        level jumped — that is, three hundredths multiplied by `promo_band_jump`
        — to the base fraction, and then cap the result at a maximum merit
        fraction of twenty-five hundredths."

        EXCEEDS base 0.24 + 0.03*2 = 0.30 -> clamped to 0.25; merit_amount
        0.25 * 200000 = 50000.00.

        Design: Difficulty/combinatorial_formula/merit_matrix_nonlinear_mode_a
        """
        ctx = setup_calibrated_review_in_comp_planning(
            band_label="EXCEEDS", band_merit_pct=0.24, base_salary=200000)
        plan = create_comp_plan_for(
            ctx["cycle"]["id"], ctx["review"]["id"], ctx["manager"]["id"],
            plan_type="MERIT_AND_PROMO", promo_band_jump=2)
        assert plan["merit_pct"] == 0.25
        assert plan["merit_amount"] == 50000.00

    def test_promo_uplift_below_cap_not_clamped(self, api):
        """PRD §3.8: "For a `MERIT_AND_PROMO` plan, add a promotion uplift of
        three hundredths for each band level jumped".

        MEETS base 0.04 + 0.03*1 = 0.07 (below the 0.25 cap, no clamp);
        merit_amount 0.07 * 100000 = 7000.00.

        Design: Difficulty/combinatorial_formula/merit_matrix_nonlinear_mode_a
        """
        ctx = setup_calibrated_review_in_comp_planning(
            band_label="MEETS", band_merit_pct=0.04, base_salary=100000)
        plan = create_comp_plan_for(
            ctx["cycle"]["id"], ctx["review"]["id"], ctx["manager"]["id"],
            plan_type="MERIT_AND_PROMO", promo_band_jump=1)
        assert plan["merit_pct"] == pytest.approx(0.07, abs=1e-9)
        assert plan["merit_amount"] == 7000.00


class TestMeritRoundThenSum:
    """Mode (b): each plan's merit_amount is rounded to 2dp BEFORE summing into
    merit_committed_total (round-then-sum)."""

    def _setup_two_plans_with_half_cent(self, api):
        # band merit_pct 0.01, base_salary 100000.50 -> merit_pct*salary = 1000.005,
        # which rounds half up to 1000.01 per plan.
        ctx = setup_comp_planning_with_n_calibrated_reviews(
            n=2, band_label="MEETS", band_merit_pct=0.01,
            merit_budget_pct=0.5, equity_refresh_pool=100000,
            base_salaries=[100000.50, 100000.50])
        return ctx

    def test_each_plan_rounds_half_up(self, api):
        """PRD §2.7: "each plan's `merit_amount` is rounded to two decimal places
        first". PRD §2.7: "All monetary computations are carried to two decimal
        places, rounded half up."

        merit_pct 0.01 * base_salary 100000.50 = 1000.005 -> rounds to 1000.01.

        Design: Difficulty/combinatorial_formula/merit_round_then_sum_mode_b
        """
        ctx = self._setup_two_plans_with_half_cent(api)
        cyc_id = ctx["cycle"]["id"]
        plan0 = create_comp_plan_for(cyc_id, ctx["reviews"][0]["id"], ctx["reviewers"][0]["id"])
        assert plan0["merit_amount"] == 1000.01

    def test_committed_total_is_round_then_sum(self, api):
        """PRD §2.7: "only the already-rounded amount is then added into the
        cycle's running `merit_committed_total`. This is a round-then-sum
        discipline, never a sum-then-round one".

        Two plans each 1000.01 -> merit_committed_total 2000.02 (not 2000.01 from
        sum-then-round of 1000.005 + 1000.005 = 2000.01).

        Design: Difficulty/combinatorial_formula/merit_round_then_sum_mode_b
        """
        ctx = self._setup_two_plans_with_half_cent(api)
        cyc_id = ctx["cycle"]["id"]
        appr_id = ctx["approver"]["id"]
        plan0 = create_comp_plan_for(cyc_id, ctx["reviews"][0]["id"], ctx["reviewers"][0]["id"])
        plan1 = create_comp_plan_for(cyc_id, ctx["reviews"][1]["id"], ctx["reviewers"][1]["id"])
        validate_success(api.propose_comp_plan(plan0["id"], make_manager_headers(ctx["reviewers"][0]["id"])), 200)
        validate_success(api.propose_comp_plan(plan1["id"], make_manager_headers(ctx["reviewers"][1]["id"])), 200)
        validate_success(approve_plan(plan0["id"], cyc_id, appr_id), 200)
        validate_success(approve_plan(plan1["id"], cyc_id, appr_id), 200)
        cyc = validate_success(api.get_cycle(cyc_id, HR), 200)
        assert cyc["merit_committed_total"] == 2000.02


# ==========================================================================
# Rule: boundary_precision_check
# ==========================================================================
class TestMeritBudgetExactEquality:
    """Threshold crossing on approve: merit_committed_total exactly equal to the
    budget is ALLOWED (<=), one cent over is rejected."""

    def test_exact_budget_equality_approves(self, api):
        """PRD §3.8: "the cycle's current `merit_committed_total` plus this plan's
        `merit_amount` must not exceed `merit_budget_pct` multiplied by the
        summed `base_salary` of the cycle's reviews that are `CALIBRATED` or
        later".

        merit_pct 0.10, base_salary 100000 -> merit_amount 10000.00; budget pct
        0.10 * 100000 = 10000.00 -> exactly equal, approve succeeds.

        Design: Difficulty/boundary_precision_check/merit_budget_exact_equality
        """
        ctx = setup_comp_planning_with_n_calibrated_reviews(
            n=1, band_label="MEETS", band_merit_pct=0.10,
            merit_budget_pct=0.10, equity_refresh_pool=100000,
            base_salaries=[100000])
        cyc_id = ctx["cycle"]["id"]
        plan = create_comp_plan_for(cyc_id, ctx["reviews"][0]["id"], ctx["reviewers"][0]["id"])
        assert plan["merit_amount"] == 10000.00
        validate_success(api.propose_comp_plan(plan["id"], make_manager_headers(ctx["reviewers"][0]["id"])), 200)
        approved = validate_success(approve_plan(plan["id"], cyc_id, ctx["approver"]["id"]), 200)
        assert approved["status"] == "APPROVED"

    def test_one_cent_over_budget_rejected(self, api):
        """PRD §3.8: "exceeding it is rejected with `ERR_MERIT_BUDGET_EXCEEDED`
        (HTTP 422)."

        merit_pct 0.10, base_salary 100000 -> merit_amount 10000.00; budget pct
        chosen so budget = 9999.99 (< merit_amount), so approval exceeds.

        Design: Difficulty/boundary_precision_check/merit_budget_exact_equality
        """
        ctx = setup_comp_planning_with_n_calibrated_reviews(
            n=1, band_label="MEETS", band_merit_pct=0.10,
            merit_budget_pct=0.0999999, equity_refresh_pool=100000,
            base_salaries=[100000])
        cyc_id = ctx["cycle"]["id"]
        plan = create_comp_plan_for(cyc_id, ctx["reviews"][0]["id"], ctx["reviewers"][0]["id"])
        assert plan["merit_amount"] == 10000.00
        validate_success(api.propose_comp_plan(plan["id"], make_manager_headers(ctx["reviewers"][0]["id"])), 200)
        res = approve_plan(plan["id"], cyc_id, ctx["approver"]["id"])
        validate_error(res, "ERR_MERIT_BUDGET_EXCEEDED")


class TestEmptyFeedbackSetBoundary:
    """Empty-collection edge on submit: zero SUBMITTED feedback triggers the
    fallback branch, not a div-by-zero."""

    def test_declined_feedback_uses_fallback(self, api):
        """PRD §3.5: "If there are no submitted feedback requests, the feedback
        component is set equal to the goal component, so the composite reduces to
        the goal score — declined or still-pending requests are never treated as
        zeros."

        One SCORED goal attainment 1.0 (goal score 100) + a DECLINED feedback ->
        composite 100.00.

        Design: Difficulty/boundary_precision_check/empty_feedback_set_boundary
        """
        cyc = create_open_cycle_single_band()
        mgr = create_employee(full_name="Mgr", department="ENG")
        emp = create_employee(full_name="Emp", department="ENG", manager_id=mgr["id"])
        rev = create_review(cyc["id"], emp["id"], mgr["id"])
        from test_helpers import create_goal_payload, create_feedback_request_payload
        mgr_hdr = make_manager_headers(mgr["id"])
        emp_hdr = make_employee_headers(emp["id"])
        goal = get_success_data(api.create_goal(rev["id"], create_goal_payload(weight=1.0), mgr_hdr))
        # A declined feedback request (so SUBMITTED set is empty).
        rater = create_employee(full_name="Rater", department="ENG")
        fr = get_success_data(api.create_feedback_request(
            rev["id"], create_feedback_request_payload(rater["id"], relationship="PEER"), mgr_hdr))
        api.decline_feedback(fr["id"], make_employee_headers(rater["id"]))

        api.begin_self_review(rev["id"], emp_hdr)
        api.patch_review(rev["id"], {"self_rating": "MEETS"}, emp_hdr)
        api.submit_self(rev["id"], emp_hdr)
        api.patch_review(rev["id"], {"manager_rating": "MEETS"}, mgr_hdr)
        api.score_goal(goal["id"], {"attainment_pct": 1.0}, mgr_hdr)
        review = validate_success(api.submit_review(rev["id"], mgr_hdr), 200)
        assert review["composite_score"] == 100.00

    def test_pending_feedback_uses_fallback(self, api):
        """PRD §3.5: "If there are no submitted feedback requests, the feedback
        component is set equal to the goal component, so the composite reduces to
        the goal score — declined or still-pending requests are never treated as
        zeros."

        One SCORED goal attainment 1.0 + a still-PENDING feedback request ->
        composite 100.00 (pending is not counted as a zero).

        Design: Difficulty/boundary_precision_check/empty_feedback_set_boundary
        """
        cyc = create_open_cycle_single_band()
        mgr = create_employee(full_name="Mgr", department="ENG")
        emp = create_employee(full_name="Emp", department="ENG", manager_id=mgr["id"])
        rev = create_review(cyc["id"], emp["id"], mgr["id"])
        from test_helpers import create_goal_payload, create_feedback_request_payload
        mgr_hdr = make_manager_headers(mgr["id"])
        emp_hdr = make_employee_headers(emp["id"])
        goal = get_success_data(api.create_goal(rev["id"], create_goal_payload(weight=1.0), mgr_hdr))
        rater = create_employee(full_name="Rater", department="ENG")
        api.create_feedback_request(
            rev["id"], create_feedback_request_payload(rater["id"], relationship="PEER"), mgr_hdr)
        # left PENDING on purpose
        api.begin_self_review(rev["id"], emp_hdr)
        api.patch_review(rev["id"], {"self_rating": "MEETS"}, emp_hdr)
        api.submit_self(rev["id"], emp_hdr)
        api.patch_review(rev["id"], {"manager_rating": "MEETS"}, mgr_hdr)
        api.score_goal(goal["id"], {"attainment_pct": 1.0}, mgr_hdr)
        review = validate_success(api.submit_review(rev["id"], mgr_hdr), 200)
        assert review["composite_score"] == 100.00
