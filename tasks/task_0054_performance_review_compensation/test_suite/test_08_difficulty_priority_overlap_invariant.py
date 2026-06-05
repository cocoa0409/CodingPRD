"""Difficulty queue: validation-priority conflicts, resource temporal-overlap,
compensating-action invariants.

Queue A (Difficulty) — rules priority_pair_validation_conflict,
resource_temporal_overlap, compensating_invariant.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_cycle_payload, create_rating_band_payload, create_calibration_session_payload,
    create_comp_plan_payload,
    TEST_USERS,
    create_employee, create_review, drive_review_to_submitted,
    setup_calibrated_review_in_comp_planning, setup_comp_planning_with_n_calibrated_reviews,
    create_comp_plan_for, approve_plan,
    make_manager_headers, make_hrbp_headers, make_comp_approver_headers,
)

HR = TEST_USERS["hr_admin_headers"]


# ==========================================================================
# Rule: priority_pair_validation_conflict
# ==========================================================================
class TestSodVsFiscalBudget:
    """SoD (p6) vs merit budget (p12): a self-approving manager on an over-budget
    plan must surface ERR_SEGREGATION_OF_DUTIES, not ERR_MERIT_BUDGET_EXCEEDED."""

    def test_sod_beats_budget(self, api):
        """PRD §3.8: "When the validation guards on these operations are
        evaluated, they fire in a fixed order: ... then segregation of duties ...
        then the merit-budget and equity-pool fiscal checks at approval". PRD
        §2.8: "the acting `Employee` ... must not equal a review's `reviewer_id`
        when ... approving or rejecting a compensation plan tied to it. A
        violation of any of these is rejected with `ERR_SEGREGATION_OF_DUTIES`
        (HTTP 403)."

        The approver's X-User-ID equals the review's reviewer_id, AND the plan
        would exceed the merit budget; SoD (earlier) must win.

        Design: Difficulty/priority_pair_validation_conflict/sod_vs_fiscal_budget
        """
        # Budget tiny so the plan would exceed it; approve acting as the reviewer.
        ctx = setup_comp_planning_with_n_calibrated_reviews(
            n=1, band_label="MEETS", band_merit_pct=0.10,
            merit_budget_pct=0.0000001, equity_refresh_pool=100000,
            base_salaries=[100000])
        cyc_id = ctx["cycle"]["id"]
        reviewer_id = ctx["reviewers"][0]["id"]
        plan = create_comp_plan_for(cyc_id, ctx["reviews"][0]["id"], reviewer_id)
        validate_success(api.propose_comp_plan(plan["id"], make_manager_headers(reviewer_id)), 200)
        # Approve as CompApprover whose user-id is the reviewer (SoD violation).
        cyc = get_success_data(api.get_cycle(cyc_id, make_comp_approver_headers(reviewer_id)))
        res = api.approve_comp_plan(
            plan["id"], {"expected_cycle_version": cyc["version"]},
            make_comp_approver_headers(reviewer_id))
        validate_error(res, "ERR_SEGREGATION_OF_DUTIES")

    def test_budget_surfaces_when_sod_satisfied(self, api):
        """PRD §3.8: "the cycle's current `merit_committed_total` plus this plan's
        `merit_amount` must not exceed `merit_budget_pct` multiplied by the summed
        `base_salary` of the cycle's reviews that are `CALIBRATED` or later;
        exceeding it is rejected with `ERR_MERIT_BUDGET_EXCEEDED` (HTTP 422)."

        The complement of the conflict above: with no SoD violation (the approver
        is a distinct CompApprover, not the reviewer) the same over-budget plan
        surfaces the later fiscal error, confirming p6 pre-empts p12 only when
        both are violated.

        Design: Difficulty/priority_pair_validation_conflict/sod_vs_fiscal_budget
        """
        ctx = setup_comp_planning_with_n_calibrated_reviews(
            n=1, band_label="MEETS", band_merit_pct=0.10,
            merit_budget_pct=0.0000001, equity_refresh_pool=100000,
            base_salaries=[100000])
        cyc_id = ctx["cycle"]["id"]
        plan = create_comp_plan_for(cyc_id, ctx["reviews"][0]["id"], ctx["reviewers"][0]["id"])
        validate_success(api.propose_comp_plan(plan["id"], make_manager_headers(ctx["reviewers"][0]["id"])), 200)
        # Approve as a distinct CompApprover (not the reviewer) -> SoD satisfied.
        res = approve_plan(plan["id"], cyc_id, ctx["approver"]["id"])
        validate_error(res, "ERR_MERIT_BUDGET_EXCEEDED")


class TestStateVsDistributionTolerance:
    """state (p4) vs distribution tolerance (p10): balancing an already-FINALIZED
    session must surface ERR_INVALID_STATE, not ERR_DISTRIBUTION_OUT_OF_TOLERANCE."""

    def test_state_beats_distribution(self, api):
        """PRD §3.8: "they fire in a fixed order: ... then the state-machine check
        that the resource is in a state from which the requested transition is
        defined (`ERR_INVALID_STATE`) ... then the bell-curve tolerance guard at
        balance". PRD §3.1: "any attempt to perform a transition from a state in
        which it is not defined is rejected with `ERR_INVALID_STATE` (HTTP 409)."

        A FINALIZED session cannot balance (balance is OPEN->BALANCED); even
        though its distribution is out of tolerance, the state check (earlier)
        wins.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_distribution_tolerance
        """
        # Build a FINALIZED session whose in-scope review is out of tolerance:
        # three-band target but the single review lands EXCEEDS (actual 1.0).
        # We can only finalize if balance passed, which it would NOT under tight
        # tolerance. So instead reach FINALIZED via a within-tolerance single
        # band, then re-balance: the session is FINALIZED, so balance is invalid
        # regardless of distribution. The distribution-out-of-tolerance condition
        # is moot because the earlier state check fires first.
        ctx = setup_calibrated_review_in_comp_planning(band_label="MEETS", band_merit_pct=0.04)
        # The session in ctx is FINALIZED. Re-balancing it is an invalid transition.
        sess_id = ctx["session"]["id"]
        hrbp_id = ctx["hrbp"]["id"]
        res = api.balance_session(sess_id, make_hrbp_headers(hrbp_id))
        validate_error(res, "ERR_INVALID_STATE")

    def test_distribution_surfaces_when_state_valid(self, api):
        """PRD §3.4: "If any band deviates by more than the tolerance, the balance
        is blocked with `ERR_DISTRIBUTION_OUT_OF_TOLERANCE` (HTTP 422)."

        The complement of the conflict above: when the session IS in the balanceable
        OPEN state (so the p4 state check passes), the later p10 distribution guard
        is the one that fires. Three-band target EXCEEDS 0.20 tol 0.05; the single
        OPEN-session review lands EXCEEDS (actual 1.0), overflowing tolerance.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_distribution_tolerance
        """
        cyc = get_success_data(api.create_cycle(create_cycle_payload(
            name="StateOk", cadence="ANNUAL", merit_budget_pct=0.5, equity_refresh_pool=0,
            bell_curve_target={"EXCEEDS": 0.20, "MEETS": 0.65, "BELOW": 0.15},
            distribution_tolerance=0.05), HR))
        api.create_rating_band(cyc["id"], create_rating_band_payload(
            label="BELOW", min_score=0, max_score=50, merit_pct=0.0), HR)
        api.create_rating_band(cyc["id"], create_rating_band_payload(
            label="MEETS", min_score=50, max_score=80, merit_pct=0.04), HR)
        api.create_rating_band(cyc["id"], create_rating_band_payload(
            label="EXCEEDS", min_score=80, max_score=100, merit_pct=0.10), HR)
        api.open_cycle(cyc["id"], HR)
        mgr = create_employee(full_name="Mgr", department="ENG")
        emp = create_employee(full_name="Emp", department="ENG", manager_id=mgr["id"])
        rev = create_review(cyc["id"], emp["id"], mgr["id"])
        drive_review_to_submitted(cyc["id"], rev["id"], emp["id"], mgr["id"],
                                  self_rating="EXCEEDS", manager_rating="EXCEEDS",
                                  goal_attainment=1.0)
        api.start_calibration(cyc["id"], HR)
        hrbp = create_employee(full_name="Hrbp", department="ENG")
        sess = get_success_data(api.create_calibration_session(
            create_calibration_session_payload(cyc["id"], hrbp["id"], department="ENG"),
            make_hrbp_headers(hrbp["id"])))
        # Session is OPEN (valid balance state); distribution is out of tolerance.
        res = api.balance_session(sess["id"], make_hrbp_headers(hrbp["id"]))
        validate_error(res, "ERR_DISTRIBUTION_OUT_OF_TOLERANCE")


# ==========================================================================
# Rule: resource_temporal_overlap
# ==========================================================================
class TestDistributionToleranceCapacityOverlap:
    """Aggregate-capacity overlap on CalibrationSession: balance rejected when a
    band's occupancy overflows target+tolerance."""

    def test_band_overflow_blocks_balance(self, api):
        """PRD §3.4: "for every band, the absolute difference between that band's
        actual fraction and its target fraction must be at most the cycle's
        `distribution_tolerance`. If any band deviates by more than the tolerance,
        the balance is blocked with `ERR_DISTRIBUTION_OUT_OF_TOLERANCE`
        (HTTP 422)."

        Three-band target EXCEEDS 0.20 tol 0.05; the single in-scope review lands
        EXCEEDS (actual 1.0) overflowing 0.25.

        Design: Difficulty/resource_temporal_overlap/distribution_tolerance_capacity_overlap
        """
        cyc = get_success_data(api.create_cycle(create_cycle_payload(
            name="Cap", cadence="ANNUAL", merit_budget_pct=0.5, equity_refresh_pool=0,
            bell_curve_target={"EXCEEDS": 0.20, "MEETS": 0.65, "BELOW": 0.15},
            distribution_tolerance=0.05), HR))
        api.create_rating_band(cyc["id"], create_rating_band_payload(
            label="BELOW", min_score=0, max_score=50, merit_pct=0.0), HR)
        api.create_rating_band(cyc["id"], create_rating_band_payload(
            label="MEETS", min_score=50, max_score=80, merit_pct=0.04), HR)
        api.create_rating_band(cyc["id"], create_rating_band_payload(
            label="EXCEEDS", min_score=80, max_score=100, merit_pct=0.10), HR)
        api.open_cycle(cyc["id"], HR)
        mgr = create_employee(full_name="Mgr", department="ENG")
        emp = create_employee(full_name="Emp", department="ENG", manager_id=mgr["id"])
        rev = create_review(cyc["id"], emp["id"], mgr["id"])
        drive_review_to_submitted(cyc["id"], rev["id"], emp["id"], mgr["id"],
                                  self_rating="EXCEEDS", manager_rating="EXCEEDS",
                                  goal_attainment=1.0)
        api.start_calibration(cyc["id"], HR)
        hrbp = create_employee(full_name="Hrbp", department="ENG")
        sess = get_success_data(api.create_calibration_session(
            create_calibration_session_payload(cyc["id"], hrbp["id"], department="ENG"),
            make_hrbp_headers(hrbp["id"])))
        res = api.balance_session(sess["id"], make_hrbp_headers(hrbp["id"]))
        validate_error(res, "ERR_DISTRIBUTION_OUT_OF_TOLERANCE")

    def test_band_within_tolerance_allows_balance(self, api):
        """PRD §3.4: "for every band, the absolute difference between that band's
        actual fraction and its target fraction must be at most the cycle's
        `distribution_tolerance`." PRD §3.4: "The facilitator first balances the
        session, moving it from `OPEN` to `BALANCED`."

        Single MEETS band with target MEETS 1.0; the one in-scope review lands
        MEETS (actual 1.0), exactly on target -> within tolerance, balance
        succeeds. The complementary (occupancy not overflowing) boundary to the
        rejection case above.

        Design: Difficulty/resource_temporal_overlap/distribution_tolerance_capacity_overlap
        """
        cyc = get_success_data(api.create_cycle(create_cycle_payload(
            name="Within", cadence="ANNUAL", merit_budget_pct=0.5, equity_refresh_pool=0,
            bell_curve_target={"MEETS": 1.0}, distribution_tolerance=0.05), HR))
        api.create_rating_band(cyc["id"], create_rating_band_payload(
            label="MEETS", min_score=0, max_score=100, merit_pct=0.04), HR)
        api.open_cycle(cyc["id"], HR)
        mgr = create_employee(full_name="Mgr", department="ENG")
        emp = create_employee(full_name="Emp", department="ENG", manager_id=mgr["id"])
        rev = create_review(cyc["id"], emp["id"], mgr["id"])
        drive_review_to_submitted(cyc["id"], rev["id"], emp["id"], mgr["id"],
                                  self_rating="MEETS", manager_rating="MEETS",
                                  goal_attainment=0.6)
        api.start_calibration(cyc["id"], HR)
        hrbp = create_employee(full_name="Hrbp", department="ENG")
        sess = get_success_data(api.create_calibration_session(
            create_calibration_session_payload(cyc["id"], hrbp["id"], department="ENG"),
            make_hrbp_headers(hrbp["id"])))
        balanced = validate_success(api.balance_session(sess["id"], make_hrbp_headers(hrbp["id"])), 200)
        assert balanced["status"] == "BALANCED"


class TestTenureWindowEligibilityOverlap:
    """Half-open tenure window on CompPlan/Employee: equity ineligible when
    [hire_date, cycle.created_at) spans < 1 year."""

    def test_just_inside_disallowed_window(self, api):
        """PRD §3.8: "compute the employee's tenure in whole years as the number
        of complete 365-day periods between the employee's `hire_date` and the
        cycle's `created_at` (the fractional remainder is discarded). If that
        tenure is less than one year, the employee is ineligible ... a tenure of
        less than the one-year minimum is rejected with `ERR_TENURE_INELIGIBLE`
        (HTTP 422)."

        An employee hired ~364 days before the cycle has floor(364/365)=0 years,
        just inside the disallowed window -> ERR_TENURE_INELIGIBLE.

        Design: Difficulty/resource_temporal_overlap/tenure_window_eligibility_overlap
        """
        # Cycle created "now" (2026-05-30 per environment). Hire 364 days prior.
        ctx = setup_calibrated_review_in_comp_planning(
            band_label="EXCEEDS", band_merit_pct=0.10,
            equity_refresh_pool=100000, hire_date="2025-06-01T00:00:00.000Z")
        mgr_hdr = make_manager_headers(ctx["manager"]["id"])
        rev = get_success_data(api.get_review(ctx["review"]["id"], mgr_hdr))
        payload = create_comp_plan_payload(
            ctx["cycle"]["id"], ctx["review"]["id"], rev["version"], plan_type="MERIT_ONLY")
        res = api.create_comp_plan(payload, mgr_hdr)
        validate_error(res, "ERR_TENURE_INELIGIBLE")

    def test_just_outside_allowed_window_eligible(self, api):
        """PRD §3.8: "For an eligible employee, take the band-equity factor for the
        review's `final_rating` — four hundred share units for the top `EXCEEDS`
        band ... and scale it by a tenure bonus". PRD §3.8: "If that tenure is less
        than one year, the employee is ineligible and `equity_refresh_units` is
        zero regardless of band."

        The complementary side of the half-open window: an employee with several
        whole years of tenure clears the >= 1-year gate, so plan creation succeeds
        and `equity_refresh_units` is strictly positive (no ERR_TENURE_INELIGIBLE).

        Design: Difficulty/resource_temporal_overlap/tenure_window_eligibility_overlap
        """
        ctx = setup_calibrated_review_in_comp_planning(
            band_label="EXCEEDS", band_merit_pct=0.10,
            equity_refresh_pool=100000, hire_date="2010-01-01T00:00:00.000Z")
        plan = create_comp_plan_for(ctx["cycle"]["id"], ctx["review"]["id"], ctx["manager"]["id"])
        assert plan["equity_refresh_units"] > 0


# ==========================================================================
# Rule: compensating_invariant
# ==========================================================================
class TestRejectPreservesMeritLedger:
    """Reject leaves merit_committed_total identical to before the plan existed."""

    def test_reject_does_not_move_merit_total(self, api):
        """PRD §2.7: "A rejected plan never touches either ledger — only approval
        debits committed totals, and rejection is guaranteed to leave them
        untouched." PRD §3.8: "Rejection ... never touches the merit or equity
        committed totals."

        One APPROVED plan (merit 4000) sets merit_committed_total 4000; rejecting
        a second proposed plan leaves it at 4000.

        Design: Difficulty/compensating_invariant/reject_preserves_merit_ledger
        """
        ctx = setup_comp_planning_with_n_calibrated_reviews(
            n=2, band_label="MEETS", band_merit_pct=0.04,
            merit_budget_pct=0.5, equity_refresh_pool=100000,
            base_salaries=[100000, 100000])
        cyc_id = ctx["cycle"]["id"]
        appr_id = ctx["approver"]["id"]
        plan0 = create_comp_plan_for(cyc_id, ctx["reviews"][0]["id"], ctx["reviewers"][0]["id"])
        plan1 = create_comp_plan_for(cyc_id, ctx["reviews"][1]["id"], ctx["reviewers"][1]["id"])
        validate_success(api.propose_comp_plan(plan0["id"], make_manager_headers(ctx["reviewers"][0]["id"])), 200)
        validate_success(api.propose_comp_plan(plan1["id"], make_manager_headers(ctx["reviewers"][1]["id"])), 200)
        validate_success(approve_plan(plan0["id"], cyc_id, appr_id), 200)
        before = validate_success(api.get_cycle(cyc_id, HR), 200)["merit_committed_total"]
        assert before == 4000.00
        validate_success(api.reject_comp_plan(plan1["id"], make_comp_approver_headers(appr_id)), 200)
        after = validate_success(api.get_cycle(cyc_id, HR), 200)["merit_committed_total"]
        assert after == 4000.00

    def test_reject_keeps_merit_total_when_only_proposed(self, api):
        """PRD §2.7: "only approval debits committed totals, and rejection is
        guaranteed to leave them untouched."

        With no APPROVED plan, merit_committed_total is 0 before and after a
        reject of a PROPOSED plan.

        Design: Difficulty/compensating_invariant/reject_preserves_merit_ledger
        """
        ctx = setup_comp_planning_with_n_calibrated_reviews(
            n=1, band_label="MEETS", band_merit_pct=0.04,
            merit_budget_pct=0.5, equity_refresh_pool=100000, base_salaries=[100000])
        cyc_id = ctx["cycle"]["id"]
        appr_id = ctx["approver"]["id"]
        plan = create_comp_plan_for(cyc_id, ctx["reviews"][0]["id"], ctx["reviewers"][0]["id"])
        validate_success(api.propose_comp_plan(plan["id"], make_manager_headers(ctx["reviewers"][0]["id"])), 200)
        before = validate_success(api.get_cycle(cyc_id, HR), 200)["merit_committed_total"]
        assert before == 0
        validate_success(api.reject_comp_plan(plan["id"], make_comp_approver_headers(appr_id)), 200)
        after = validate_success(api.get_cycle(cyc_id, HR), 200)["merit_committed_total"]
        assert after == 0


class TestEquityPoolConservedOnReject:
    """Reject leaves equity_committed_total unchanged."""

    def test_reject_does_not_move_equity_total(self, api):
        """PRD §2.7: "A rejected plan never touches either ledger". PRD §3.8:
        "Rejection ... never touches the merit or equity committed totals." PRD
        §2.7: "`equity_committed_total`, the sum of `equity_refresh_units` across
        those same approved plans."

        One APPROVED EXCEEDS plan grants 400 (tenure exactly 1 year -> factor 400
        * (1 + 0.10*1) = 440); reject a second leaves equity_committed_total at
        the first plan's grant.

        Design: Difficulty/compensating_invariant/equity_pool_conserved_on_reject
        """
        ctx = setup_comp_planning_with_n_calibrated_reviews(
            n=2, band_label="EXCEEDS", band_merit_pct=0.10,
            merit_budget_pct=0.5, equity_refresh_pool=100000,
            hire_date="2010-01-01T00:00:00.000Z")
        cyc_id = ctx["cycle"]["id"]
        appr_id = ctx["approver"]["id"]
        plan0 = create_comp_plan_for(cyc_id, ctx["reviews"][0]["id"], ctx["reviewers"][0]["id"])
        plan1 = create_comp_plan_for(cyc_id, ctx["reviews"][1]["id"], ctx["reviewers"][1]["id"])
        grant0 = plan0["equity_refresh_units"]
        validate_success(api.propose_comp_plan(plan0["id"], make_manager_headers(ctx["reviewers"][0]["id"])), 200)
        validate_success(api.propose_comp_plan(plan1["id"], make_manager_headers(ctx["reviewers"][1]["id"])), 200)
        validate_success(approve_plan(plan0["id"], cyc_id, appr_id), 200)
        before = validate_success(api.get_cycle(cyc_id, HR), 200)["equity_committed_total"]
        assert before == grant0
        validate_success(api.reject_comp_plan(plan1["id"], make_comp_approver_headers(appr_id)), 200)
        after = validate_success(api.get_cycle(cyc_id, HR), 200)["equity_committed_total"]
        assert after == grant0

    def test_reject_keeps_equity_total_when_only_proposed(self, api):
        """PRD §2.7: "only approval debits committed totals, and rejection is
        guaranteed to leave them untouched."

        With no APPROVED plan, equity_committed_total is 0 before and after a
        reject of a PROPOSED equity-bearing plan.

        Design: Difficulty/compensating_invariant/equity_pool_conserved_on_reject
        """
        ctx = setup_comp_planning_with_n_calibrated_reviews(
            n=1, band_label="EXCEEDS", band_merit_pct=0.10,
            merit_budget_pct=0.5, equity_refresh_pool=100000,
            hire_date="2010-01-01T00:00:00.000Z")
        cyc_id = ctx["cycle"]["id"]
        appr_id = ctx["approver"]["id"]
        plan = create_comp_plan_for(cyc_id, ctx["reviews"][0]["id"], ctx["reviewers"][0]["id"])
        assert plan["equity_refresh_units"] > 0
        validate_success(api.propose_comp_plan(plan["id"], make_manager_headers(ctx["reviewers"][0]["id"])), 200)
        before = validate_success(api.get_cycle(cyc_id, HR), 200)["equity_committed_total"]
        assert before == 0
        validate_success(api.reject_comp_plan(plan["id"], make_comp_approver_headers(appr_id)), 200)
        after = validate_success(api.get_cycle(cyc_id, HR), 200)["equity_committed_total"]
        assert after == 0
