"""Calculation engines: composite score, merit, equity, final-rating variant.

Queue B (Corner) — calculations and entities (computed-field) sections.
"""
import pytest
from test_helpers import (
    validate_success, get_success_data,
    create_cycle_payload, create_rating_band_payload, create_calibration_session_payload,
    create_comp_plan_payload,
    TEST_USERS,
    create_employee, create_open_cycle_single_band, create_review,
    drive_review_to_submitted, setup_calibrated_review_in_comp_planning,
    create_comp_plan_for,
    make_manager_headers, make_employee_headers, make_hrbp_headers,
)

HR = TEST_USERS["hr_admin_headers"]


def test_composite_with_feedback_blend(api):
    """PRD §3.5: "multiply the goal component by seven tenths and the feedback
    component by three tenths, add the two, and round the result half up to two
    decimal places." PRD §3.5: "average the `score` values of the submitted
    requests (each on the one-to-five scale), subtract one, divide by four, and
    multiply by 100".

    Goal 100, feedback scores 5 and 1 -> avg5 3 -> feedback_score 50 ->
    0.7*100 + 0.3*50 = 85.00.

    Design: Corner/calculations/composite_with_feedback_blend
    """
    cyc = create_open_cycle_single_band()
    mgr = create_employee(full_name="Mgr", department="ENG")
    emp = create_employee(full_name="Emp", department="ENG", manager_id=mgr["id"])
    rev = create_review(cyc["id"], emp["id"], mgr["id"])
    review = drive_review_to_submitted(
        cyc["id"], rev["id"], emp["id"], mgr["id"],
        self_rating="MEETS", manager_rating="MEETS",
        goal_attainment=1.0, feedback_scores=[5, 1])
    assert review["composite_score"] == 85.00


def test_comp_plan_create_computes_merit(api):
    """PRD §3.8: "For a `MERIT_ONLY` plan, the plan's `merit_pct` is exactly that
    base fraction with no uplift. The plan's `merit_amount` is the resulting
    `merit_pct` multiplied by the review's `base_salary`, rounded half up to two
    decimal places."

    MEETS band merit_pct 0.04, base_salary 120000 -> merit_amount 4800.00.

    Design: Corner/entities/comp_plan_create_computes_merit
    """
    ctx = setup_calibrated_review_in_comp_planning(
        band_label="MEETS", band_merit_pct=0.04, base_salary=120000)
    plan = create_comp_plan_for(ctx["cycle"]["id"], ctx["review"]["id"], ctx["manager"]["id"])
    assert plan["merit_pct"] == 0.04
    assert plan["merit_amount"] == 4800.00


def test_assign_final_rating_within_tolerance(api):
    """PRD §3.6: "When the actual distribution is already within tolerance of the
    target for every band, no demotions occur and each review's `final_rating` is
    simply the band its `composite_score` fell into."

    Single MEETS band -> the one review's composite 60 falls in MEETS,
    final_rating MEETS with no demotion.

    Design: Corner/calculations/assign_final_rating_within_tolerance
    """
    ctx = setup_calibrated_review_in_comp_planning(band_label="MEETS", band_merit_pct=0.04)
    review = get_success_data(api.get_review(ctx["review"]["id"], HR))
    assert review["final_rating"] == "MEETS"
    assert review["status"] == "CALIBRATED"


def test_equity_pool_constrained_clamp(api):
    """PRD §3.8: "The granted amount is the smaller of that raw target and the
    pool's remaining headroom (the `equity_refresh_pool` minus the cycle's
    current `equity_committed_total`), floored at zero so it never goes negative,
    and rounded half up to three decimal places."

    EXCEEDS subject, tenure capped at 5yr -> raw_target 400*1.5 = 600. Pool is
    only 100, committed 0 -> granted clamps to 100.

    Design: Corner/calculations/equity_pool_constrained_clamp
    """
    ctx = setup_calibrated_review_in_comp_planning(
        band_label="EXCEEDS", band_merit_pct=0.10,
        equity_refresh_pool=100, base_salary=100000,
        hire_date="2010-01-01T00:00:00.000Z")
    plan = create_comp_plan_for(ctx["cycle"]["id"], ctx["review"]["id"], ctx["manager"]["id"])
    assert plan["equity_refresh_units"] == 100
