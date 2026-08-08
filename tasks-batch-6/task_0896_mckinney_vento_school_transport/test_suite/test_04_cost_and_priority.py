"""Cost estimation/actuals, tiered allocation, invoicing, priority scoring,
and caseload boundary (difficulty: dual_variant_calc, combinatorial_formula,
boundary_precision_check; corner: calculations)."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS,
    create_district, create_student, create_liaison, create_plan, create_cost_share,
    create_completed_trip, make_student_eligible,
    setup_active_plan, setup_active_plan_with_vehicle, setup_completed_trip,
)

SC = TEST_USERS["state_coordinator_headers"]


# ---------------------------------------------------------------------------
# Difficulty: dual_variant_calc — plan estimated vs actual
# ---------------------------------------------------------------------------
def test_plan_estimated_and_actual_diverge(api):
    """PRD §3.5: "The `estimated_daily_cost_cents` is the route mileage multiplied
    by a per-mile rate of 155 cents plus a fixed per-trip base of 500 cents; the
    `estimated_monthly_cost_cents` is that daily estimate multiplied by 20 school
    days per month."
    PRD §3.7: "the trip's `trip_cost_cents` is computed as `actual_miles` multiplied
    by the 155-cent per-mile rate plus the 500-cent base. Second, the plan's
    `actual_cost_cents` increases by that `trip_cost_cents`".

    Design: Difficulty/dual_variant_calc/plan_estimated_vs_actual_transport_cost
    """
    ctx = setup_completed_trip(route_miles=20, actual_miles=20)
    plan = validate_success(api.get_plan(ctx["plan"]["id"], SC))
    assert plan["estimated_monthly_cost_cents"] == 72000
    assert plan["actual_cost_cents"] == 3600
    assert plan["estimated_monthly_cost_cents"] != plan["actual_cost_cents"]


def test_cost_summary_reports_actual_after_one_trip(api):
    """PRD §3.5: "A plan's dual-variant cost picture is available as a computed read
    exposing `estimated_daily_cost_cents`, `estimated_monthly_cost_cents`,
    `actual_cost_cents`, and a `completed_trip_count`. The `actual_cost_cents` is
    the chronological sum of `trip_cost_cents` over the plan's trips that are
    `COMPLETED` and not voided".

    Design: Difficulty/dual_variant_calc/plan_estimated_vs_actual_transport_cost
    """
    ctx = setup_completed_trip(route_miles=20, actual_miles=20)
    summary = validate_success(api.plan_cost_summary(ctx["plan"]["id"], SC))
    assert summary["actual_cost_cents"] == 3600
    assert summary["completed_trip_count"] == 1
    assert summary["estimated_monthly_cost_cents"] == 72000


# ---------------------------------------------------------------------------
# Difficulty: dual_variant_calc — student priority provisional vs final
# ---------------------------------------------------------------------------
def test_student_priority_provisional_at_intake(api):
    """PRD §3.3: "The provisional variant, computed at intake from the self-reported
    `living_situation`, assigns 50 points for `UNSHELTERED`, 40 for `SHELTER`, 35
    for `FOSTER_PLACEMENT`, 30 for `HOTEL_MOTEL`, 20 for `DOUBLED_UP`, and 0 for
    `HOUSED`."

    Design: Difficulty/dual_variant_calc/student_priority_provisional_vs_final
    """
    d = create_district()
    s = create_student(d["id"], living_situation="DOUBLED_UP")
    assert s["priority_score"] == 20, "self-reported DOUBLED_UP -> provisional 20"
    assert s["priority_basis"] == "PROVISIONAL"


def test_student_priority_final_after_finalize(api):
    """PRD §3.3: "The final variant, computed at finalization from the verified
    determination, assigns a base from the `basis` — 50 for `NIGHT_TO_NIGHT`, 50 for
    `UNSHELTERED`, 40 for `SHELTER`, 35 for `FOSTER`, 30 for `HOTEL_MOTEL`, and 20
    for `DOUBLED_UP` — and then adds a 10-point bonus when the determination's
    `category` is `FOSTER`."

    Design: Difficulty/dual_variant_calc/student_priority_provisional_vs_final
    """
    d = create_district()
    s = create_student(d["id"], living_situation="DOUBLED_UP")
    make_student_eligible(s["id"], s["version"], category="HOMELESS", basis="UNSHELTERED", decision="ELIGIBLE")
    student = validate_success(api.get_student(s["id"], SC))
    assert student["priority_score"] == 50, "verified UNSHELTERED basis -> final 50"
    assert student["priority_basis"] == "FINAL"


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula — tiered allocation with cap
# ---------------------------------------------------------------------------
def _draft_plan_with_cost_share(route_miles):
    d = create_district()
    s = create_student(d["id"])
    plan = create_plan(s["id"], d["id"], route_miles=route_miles)
    agreement = create_cost_share(plan["id"], plan["version"])
    return agreement


def test_cost_share_tier_selection_and_snapshot(api):
    """PRD §3.6: "At creation the agreement snapshots the plan's
    `estimated_monthly_cost_cents` into `total_monthly_cents` and selects a tiered
    serving-share fraction, `serving_pct`, from the plan's one-way route mileage: a
    route of at most 10 miles takes a serving fraction of 0.50; a route of more than
    10 but at most 25 miles takes 0.60; a route longer than 25 miles takes 0.75."

    Design: Difficulty/combinatorial_formula/cost_share_tiered_allocation_with_cap
    """
    agreement = _draft_plan_with_cost_share(50)
    assert agreement["total_monthly_cents"] == 165000
    assert agreement["serving_pct"] == 0.75


def test_cost_share_cap_applied_after_rounding(api):
    """PRD §3.6: "The `serving_share_cents` is then the lesser of the
    `SHARE_CAP_CENTS` ceiling of 100,000 cents and the round-half-up of
    `total_monthly_cents` multiplied by `serving_pct` — with the rounding done first
    and the cap applied afterward (§2.6). The `origin_share_cents` is simply
    `total_monthly_cents` minus `serving_share_cents`."

    Design: Difficulty/combinatorial_formula/cost_share_tiered_allocation_with_cap
    """
    agreement = _draft_plan_with_cost_share(50)  # raw serving 123750 -> capped at 100000
    assert agreement["serving_share_cents"] == 100000
    assert agreement["origin_share_cents"] == 65000


# ---------------------------------------------------------------------------
# Difficulty: combinatorial_formula — invoice per-trip rounding then sum
# ---------------------------------------------------------------------------
def _invoice_two_small_trips():
    ctx = setup_active_plan_with_vehicle(route_miles=10)  # serving_pct 0.5
    create_completed_trip(ctx["plan"]["id"], ctx["vehicle"]["id"],
                          "2026-05-04T08:00:00Z", "2026-05-04T08:30:00Z", actual_miles=1)
    create_completed_trip(ctx["plan"]["id"], ctx["vehicle"]["id"],
                          "2026-05-05T08:00:00Z", "2026-05-05T08:30:00Z", actual_miles=1)
    return ctx


def test_invoice_serving_rounds_each_trip_before_summing(api):
    """PRD §3.8: "For each such trip, the serving portion is the round-half-up of that trip's `trip_cost_cents` multiplied by the agreement's `serving_pct`; `serving_invoice_cents` is the sum of those per-trip rounded portions."

    Design: Difficulty/combinatorial_formula/invoice_per_trip_rounding_then_sum
    """
    ctx = _invoice_two_small_trips()
    invoice = validate_success(api.agreement_invoice(ctx["agreement"]["id"], SC))
    # trip_cost 655 each; round(655*0.5)=round(327.5)=328 per trip -> 656 (not round(1310*0.5)=655)
    assert invoice["serving_invoice_cents"] == 656
    assert invoice["trip_count"] == 2


def test_invoice_origin_is_complement_per_trip(api):
    """PRD §3.8: "The `origin_invoice_cents` is the sum, over the same trips, of each
    trip's `trip_cost_cents` minus that trip's rounded serving portion."

    Design: Difficulty/combinatorial_formula/invoice_per_trip_rounding_then_sum
    """
    ctx = _invoice_two_small_trips()
    invoice = validate_success(api.agreement_invoice(ctx["agreement"]["id"], SC))
    # per trip: 655 - 328 = 327; two trips -> 654
    assert invoice["origin_invoice_cents"] == 654


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check — caseload max+1
# ---------------------------------------------------------------------------
def _two_eligible_students_and_liaison():
    d = create_district()
    lia = create_liaison(d["id"], max_caseload=1)
    sa = create_student(d["id"])
    make_student_eligible(sa["id"], sa["version"])
    sb = create_student(d["id"])
    make_student_eligible(sb["id"], sb["version"])
    return d, lia, sa, sb


def test_caseload_boundary_second_assignment_rejected(api):
    """PRD §3.1: "The boundary is strict: a caseload of exactly `max_caseload` is
    allowed, and only an assignment that would make the count exceed `max_caseload`
    (that is, reach `max_caseload` plus one) is refused, with `ERR_LIAISON_CASELOAD_FULL`."

    Design: Difficulty/boundary_precision_check/caseload_boundary_max_plus_one_rejected
    """
    d, lia, sa, sb = _two_eligible_students_and_liaison()
    validate_success(api.assign_liaison(sa["id"], {"liaison_id": lia["id"]}, SC))
    validate_error(api.assign_liaison(sb["id"], {"liaison_id": lia["id"]}, SC),
                   ApiErrorId.ERR_LIAISON_CASELOAD_FULL.value, 409)
    liaison = validate_success(api.get_liaison(lia["id"], SC))
    assert liaison["current_caseload"] == 1


def test_caseload_at_exactly_max_allowed(api):
    """PRD §3.1: "The boundary is strict: a caseload of exactly `max_caseload` is
    allowed, and only an assignment that would make the count exceed `max_caseload`
    (that is, reach `max_caseload` plus one) is refused, with `ERR_LIAISON_CASELOAD_FULL`."

    Design: Difficulty/boundary_precision_check/caseload_boundary_max_plus_one_rejected
    """
    d, lia, sa, sb = _two_eligible_students_and_liaison()
    student = validate_success(api.assign_liaison(sa["id"], {"liaison_id": lia["id"]}, SC))
    assert student["liaison_id"] == lia["id"]
    liaison = validate_success(api.get_liaison(lia["id"], SC))
    assert liaison["current_caseload"] == 1, "caseload of exactly max_caseload is allowed"


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check — cost summary with zero completed trips
# ---------------------------------------------------------------------------
def test_cost_summary_zero_completed_trips_actual_zero(api):
    """PRD §3.5: "The `actual_cost_cents` is the chronological sum of
    `trip_cost_cents` over the plan's trips that are `COMPLETED` and not voided; for
    a plan with zero completed trips it is zero even though the estimate is positive."

    Design: Difficulty/boundary_precision_check/cost_summary_zero_completed_trips_actual_zero
    """
    ctx = setup_active_plan(route_miles=20)
    summary = validate_success(api.plan_cost_summary(ctx["plan"]["id"], SC))
    assert summary["actual_cost_cents"] == 0
    assert summary["completed_trip_count"] == 0


def test_cost_summary_estimate_positive_with_no_trips(api):
    """PRD §3.5: "for a plan with zero completed trips it is zero even though the
    estimate is positive."
    PRD §3.5: "the `estimated_monthly_cost_cents` is that daily estimate multiplied
    by 20 school days per month."

    Design: Difficulty/boundary_precision_check/cost_summary_zero_completed_trips_actual_zero
    """
    ctx = setup_active_plan(route_miles=20)
    summary = validate_success(api.plan_cost_summary(ctx["plan"]["id"], SC))
    assert summary["estimated_monthly_cost_cents"] == 72000


# ---------------------------------------------------------------------------
# Corner: calculations
# ---------------------------------------------------------------------------
def test_cost_share_uncapped_middle_tier(api):
    """PRD §3.6: "a route of more than 10 but at most 25 miles takes 0.60".
    PRD §3.6: "The `origin_share_cents` is simply `total_monthly_cents` minus
    `serving_share_cents`."

    Design: Corner/calculations/cost_share_uncapped_tier_60
    """
    agreement = _draft_plan_with_cost_share(20)  # total 72000, serving 43200 (< cap)
    assert agreement["serving_pct"] == 0.6
    assert agreement["serving_share_cents"] == 43200
    assert agreement["origin_share_cents"] == 28800


def test_actual_cost_excludes_voided_trip(api):
    """PRD §3.5: "The `actual_cost_cents` is the chronological sum of
    `trip_cost_cents` over the plan's trips that are `COMPLETED` and not voided".

    Design: Corner/calculations/actual_cost_excludes_voided_trips
    """
    ctx = setup_active_plan_with_vehicle(route_miles=20)
    create_completed_trip(ctx["plan"]["id"], ctx["vehicle"]["id"],
                          "2026-05-04T08:00:00Z", "2026-05-04T08:30:00Z", actual_miles=20)
    t2 = create_completed_trip(ctx["plan"]["id"], ctx["vehicle"]["id"],
                               "2026-05-05T08:00:00Z", "2026-05-05T08:30:00Z", actual_miles=20)
    api.void_trip(t2["id"], SC)
    plan = validate_success(api.get_plan(ctx["plan"]["id"], SC))
    assert plan["actual_cost_cents"] == 3600, "voided trip excluded; only 1 of 2 counts"
