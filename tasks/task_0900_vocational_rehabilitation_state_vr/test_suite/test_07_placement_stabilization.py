"""Placement lifecycle: stabilization window, destabilize/resume loop, verified wage,
and the 90-day boundary.

Difficulty queue (§1.8): dual_variant_calc / verified_vs_projected_weekly_wage;
non_linear_state_machine / placement_destabilize_resume_cycle;
boundary_precision_check / stabilization_exactly_90_days_succeeds.
Corner queue (§1.9): placement-type and stabilization-window validations.
"""
from test_helpers import (
    validate_success, validate_error,
    setup_employed_case, setup_stabilizing_placement, add_progress_review, set_clock,
    TEST_USERS,
)

VRADMIN = TEST_USERS["vradmin_headers"]


# ─── Difficulty: verified vs projected weekly wage ───────────────────

def test_verified_avg_weekly_wage_from_reviews(api):
    """PRD §3.8: "otherwise it is the sum of `reported_weekly_wage_cents` over the
    window divided by the number of reviews in the window, rounded half up to whole
    cents."

    Design: Difficulty/dual_variant_calc/verified_vs_projected_weekly_wage
    """
    ctx = setup_stabilizing_placement(employment_type="COMPETITIVE_INTEGRATED",
                                      weekly_wage_cents=50000, start_clock="2026-05-01T00:00:00Z")
    add_progress_review(ctx, "2026-05-10", 40000)
    add_progress_review(ctx, "2026-06-10", 60000)
    add_progress_review(ctx, "2026-07-10", 44000)
    set_clock("2026-07-30T00:00:00Z")
    placement = validate_success(api.verify_stability(ctx["placement_id"], ctx["counselor_headers"]), 200)
    assert placement["status"] == "STABLE"
    assert placement["verified_avg_weekly_wage_cents"] == 48000


def test_verified_wage_diverges_from_projected_hire_wage(api):
    """PRD §3.8: "This verified average is the closure-time counterpart to the
    forward-looking projection captured in `weekly_wage_cents` at hire, and diverges
    from it whenever reported wages differ from the hire estimate."

    Design: Difficulty/dual_variant_calc/verified_vs_projected_weekly_wage
    """
    ctx = setup_stabilizing_placement(employment_type="COMPETITIVE_INTEGRATED",
                                      weekly_wage_cents=50000, start_clock="2026-05-01T00:00:00Z")
    add_progress_review(ctx, "2026-05-10", 40000)
    add_progress_review(ctx, "2026-06-10", 60000)
    add_progress_review(ctx, "2026-07-10", 44000)
    set_clock("2026-07-30T00:00:00Z")
    placement = validate_success(api.verify_stability(ctx["placement_id"], ctx["counselor_headers"]), 200)
    assert placement["weekly_wage_cents"] == 50000
    assert placement["verified_avg_weekly_wage_cents"] == 48000
    assert placement["weekly_wage_cents"] != placement["verified_avg_weekly_wage_cents"]


# ─── Difficulty: destabilize / resume loop resets the window ─────────

def test_destabilize_resume_returns_to_stabilizing(api):
    """PRD §3.8: "A job may be lost mid-window: reporting a loss moves a
    `STABILIZING` placement to `DESTABILIZED`. Resuming after re-employment moves
    `DESTABILIZED` back to `STABILIZING` and **resets** `stabilization_start_date` to
    the current logical-clock date, restarting the 90-day count from zero."

    Design: Difficulty/non_linear_state_machine/placement_destabilize_resume_cycle
    """
    ctx = setup_stabilizing_placement(employment_type="SUPPORTED", weekly_wage_cents=40000,
                                      start_clock="2026-05-01T00:00:00Z")
    set_clock("2026-05-20T00:00:00Z")
    lost = validate_success(api.report_loss(ctx["placement_id"], ctx["counselor_headers"]), 200)
    assert lost["status"] == "DESTABILIZED"
    set_clock("2026-06-15T00:00:00Z")
    resumed = validate_success(api.resume_stabilization(ctx["placement_id"], ctx["counselor_headers"]), 200)
    assert resumed["status"] == "STABILIZING"


def test_resume_resets_stabilization_start_date(api):
    """PRD §3.8: "Resuming after re-employment moves `DESTABILIZED` back to
    `STABILIZING` and **resets** `stabilization_start_date` to the current
    logical-clock date, restarting the 90-day count from zero."

    Design: Difficulty/non_linear_state_machine/placement_destabilize_resume_cycle
    """
    ctx = setup_stabilizing_placement(employment_type="SUPPORTED", weekly_wage_cents=40000,
                                      start_clock="2026-05-01T00:00:00Z")
    set_clock("2026-05-20T00:00:00Z")
    api.report_loss(ctx["placement_id"], ctx["counselor_headers"])
    set_clock("2026-06-15T00:00:00Z")
    resumed = validate_success(api.resume_stabilization(ctx["placement_id"], ctx["counselor_headers"]), 200)
    assert resumed["stabilization_start_date"] == "2026-06-15"


# ─── Difficulty: 90-day boundary succeeds ────────────────────────────

def test_verify_stability_at_exactly_90_days_reaches_stable(api):
    """PRD §3.8: "Verifying stability is permitted only on a `STABILIZING` placement
    (else `ERR_INVALID_STATE`) whose `days_stable` is at least 90 (else
    `ERR_STABILIZATION_NOT_MET`). On success the placement moves to `STABLE`".

    Design: Difficulty/boundary_precision_check/stabilization_exactly_90_days_succeeds
    """
    ctx = setup_stabilizing_placement(employment_type="COMPETITIVE_INTEGRATED",
                                      weekly_wage_cents=50000, start_clock="2026-05-01T00:00:00Z")
    set_clock("2026-07-30T00:00:00Z")  # exactly 90 days from 2026-05-01
    placement = validate_success(api.verify_stability(ctx["placement_id"], ctx["counselor_headers"]), 200)
    assert placement["status"] == "STABLE"


def test_verify_stability_at_exactly_90_days_closes_case_rehabilitated(api):
    """PRD §3.8: "Reaching `STABLE` closes the case as a successful outcome: the case
    moves from `EMPLOYED` to `CLOSED_REHABILITATED` with `closure_type` set to
    `REHABILITATED`."

    Design: Difficulty/boundary_precision_check/stabilization_exactly_90_days_succeeds
    """
    ctx = setup_stabilizing_placement(employment_type="COMPETITIVE_INTEGRATED",
                                      weekly_wage_cents=50000, start_clock="2026-05-01T00:00:00Z")
    set_clock("2026-07-30T00:00:00Z")
    validate_success(api.verify_stability(ctx["placement_id"], ctx["counselor_headers"]), 200)
    case = validate_success(api.get_case(ctx["case_id"], VRADMIN), 200)
    assert case["status"] == "CLOSED_REHABILITATED"
    assert case["closure_type"] == "REHABILITATED"


# ─── Corner: placement-type and pre-90-day validations ───────────────

def test_begin_stabilization_self_employment_type_invalid(api):
    """PRD §3.8: "Beginning stabilization moves the placement from `PLACED` to
    `STABILIZING`, but only when the `employment_type` is `COMPETITIVE_INTEGRATED` or
    `SUPPORTED`; a `SELF_EMPLOYMENT` placement is rejected with
    `ERR_PLACEMENT_TYPE_INVALID`."

    Design: Corner/validations/begin_stabilization_self_employment_type_invalid
    """
    ctx = setup_employed_case(employment_type="SELF_EMPLOYMENT", weekly_wage_cents=40000)
    res = api.begin_stabilization(ctx["placement_id"], ctx["counselor_headers"])
    validate_error(res, "ERR_PLACEMENT_TYPE_INVALID")


def test_verify_stability_before_90_days_not_met(api):
    """PRD §3.8: "Verifying stability is permitted only on a `STABILIZING` placement
    (else `ERR_INVALID_STATE`) whose `days_stable` is at least 90 (else
    `ERR_STABILIZATION_NOT_MET`)."

    Design: Corner/validations/verify_stability_before_90_days_not_met
    """
    ctx = setup_stabilizing_placement(employment_type="COMPETITIVE_INTEGRATED",
                                      weekly_wage_cents=50000, start_clock="2026-05-01T00:00:00Z")
    set_clock("2026-07-29T00:00:00Z")  # day 89
    res = api.verify_stability(ctx["placement_id"], ctx["counselor_headers"])
    validate_error(res, "ERR_STABILIZATION_NOT_MET")
    placement = validate_success(api.get_placement(ctx["placement_id"], VRADMIN), 200)
    assert placement["status"] == "STABILIZING"
