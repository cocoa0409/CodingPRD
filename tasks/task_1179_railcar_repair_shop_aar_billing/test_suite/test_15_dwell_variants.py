"""Dwell accounting: the forward-looking projection pinned at slot assignment
versus the chronological actual computed at departure, plus the free-hours
boundary."""
import pytest

from test_helpers import (
    TEST_USERS, add_car_with_inspection, add_price_entry, api_client,
    assign_slot_current_wo, authorize_current_wo, build_work_order,
    create_railcar, make_repair_foreman_headers, set_clock, setup_shop_ctx,
    submit_current_wo, validate_success,
)

ADMIN = TEST_USERS["shop_admin"]
YARD = TEST_USERS["yard_clerk"]
FOREMAN = "foreman-1"


def _projected_then_actual_scenario() -> dict:
    """Car arrives 2026-05-01T08:00Z; slot reserved for 2026-05-04T08:00-16:00Z;
    the order is cancelled before start and the car departs 2026-05-06T16:00Z
    with zero shop delay."""
    ctx = setup_shop_ctx(clock="2026-05-01T08:00:00Z")
    add_price_entry(ctx, job_code="J-INSPECT-MINOR", description="Minor inspection labor",
                    labor_rate_cents_per_hour=3333, mobile_labor_rate_cents_per_hour=4000,
                    standard_labor_hours=0.9, mobile_trip_surcharge_cents=0,
                    mobile_eligible=True)
    add_car_with_inspection(ctx, car_number="2002", defects=[{
        "aar_defect_code": "AAR-9001", "defect_group": "OTHER",
        "cause_code": "WEAR", "severity": "MINOR", "location": "A-end"}])
    build_work_order(ctx, lines=[{"job_code": "J-INSPECT-MINOR"}])
    submit_current_wo(ctx)
    authorize_current_wo(ctx)
    assign_slot_current_wo(ctx, starts_at="2026-05-04T08:00:00Z",
                           ends_at="2026-05-04T16:00:00Z")
    set_clock("2026-05-06T16:00:00Z")
    resp = api_client.cancel_work_order(ctx["wo"]["id"], {},
                                        make_repair_foreman_headers(FOREMAN))
    validate_success(resp)
    validate_success(api_client.depart_railcar(ctx["car"]["id"], YARD))
    return ctx


def test_projected_dwell_charge_pinned_at_slot_assignment():
    """PRD §3.6: "The **projected** variant, pinned earlier at slot reservation
    or mobile dispatch, is forward-looking: the projected release instant is
    the reserved slot's `ends_at` for `SHOP` routing, or the current logical
    time plus the sum of the lines' `standard_labor_hours` for `MOBILE`
    routing; projected billable hours are the greater of zero and the elapsed
    hours from `arrived_at` to that release instant minus the free allowance —
    no shop delay is subtracted, since none has accrued yet — and the projected
    charge is the rate multiplication rounded half up, stored as
    `projected_dwell_charge_cents`."

    Design: Difficulty/dual_variant_calc/projected_vs_actual_dwell_charge
    """
    ctx = _projected_then_actual_scenario()
    car = validate_success(api_client.get_railcar(ctx["car"]["id"], ADMIN))
    assert car["projected_dwell_charge_cents"] == 16000, (
        "80h from arrival to the slot's 2026-05-04T16:00Z end, minus 48 free, "
        "is 32 billable hours at 500c")
    summary = validate_success(api_client.get_dwell_summary(ctx["car"]["id"], ADMIN))
    assert summary["projected_dwell_charge_cents"] == 16000, (
        "the pinned projection is returned alongside the live actual read")


def test_actual_dwell_charge_computed_at_departure():
    """PRD §3.6: "The **actual** variant, run at departure, takes the car's
    actual hours as the fractional elapsed time — at two decimal places — from
    `arrived_at` to `departed_at`; subtracts the shop's `dwell_free_hours`
    allowance and the car's accumulated `shop_delay_hours`; keeps the greater
    of that difference and zero as the billable hours; and multiplies billable
    hours by `dwell_rate_cents_per_hour`, rounding half up to whole cents."

    Design: Difficulty/dual_variant_calc/projected_vs_actual_dwell_charge
    """
    ctx = _projected_then_actual_scenario()
    car = validate_success(api_client.get_railcar(ctx["car"]["id"], ADMIN))
    assert car["dwell_charge_cents"] == 40000, (
        "128h actual dwell minus 48 free minus 0 shop delay is 80 billable "
        "hours at 500c")
    summary = validate_success(api_client.get_dwell_summary(ctx["car"]["id"], ADMIN))
    assert summary["actual_dwell_hours"] == pytest.approx(128.0, abs=0.001)
    assert summary["billable_hours"] == pytest.approx(80.0, abs=0.001)
    assert car["dwell_charge_cents"] != car["projected_dwell_charge_cents"], (
        "the same stay is priced 16000 forward-looking versus 40000 chronological")


def test_dwell_exactly_free_hours_bills_zero():
    """PRD §3.6: "When actual hours minus shop delay is less than or equal to
    the free allowance the charge is exactly zero — only a strictly greater
    excess bills."

    Design: Difficulty/boundary_precision_check/dwell_exactly_free_hours_bills_zero
    """
    ctx = setup_shop_ctx(clock="2026-05-01T08:00:00Z")
    car = create_railcar(ctx["shop"]["id"], ctx["owner"]["id"], ctx["line"]["id"],
                         car_number="1212")
    set_clock("2026-05-03T08:00:00Z")  # exactly 48.0 hours after arrival
    departed = validate_success(api_client.depart_railcar(car["id"], YARD))
    assert departed["status"] == "DEPARTED"
    assert departed["dwell_charge_cents"] == 0, (
        "exactly at the free boundary bills nothing; strictly greater is required")
    summary = validate_success(api_client.get_dwell_summary(car["id"], ADMIN))
    assert summary["actual_dwell_hours"] == pytest.approx(48.0, abs=0.001)
    assert summary["billable_hours"] == pytest.approx(0.0, abs=0.001)


def test_dwell_free_boundary_is_strictly_greater():
    """PRD §3.6: "keeps the greater of that difference and zero as the billable
    hours; and multiplies billable hours by `dwell_rate_cents_per_hour`,
    rounding half up to whole cents."
    PRD §3.6: "When actual hours minus shop delay is less than or equal to the
    free allowance the charge is exactly zero — only a strictly greater excess
    bills."

    Design: Difficulty/boundary_precision_check/dwell_exactly_free_hours_bills_zero
    """
    ctx = setup_shop_ctx(clock="2026-05-01T08:00:00Z")
    car_at = create_railcar(ctx["shop"]["id"], ctx["owner"]["id"], ctx["line"]["id"],
                            car_number="1213")
    car_over = create_railcar(ctx["shop"]["id"], ctx["owner"]["id"], ctx["line"]["id"],
                              car_number="1214")
    # Car departing at exactly 48.0h bills nothing; a sibling departing one
    # hour later bills exactly one hour — the comparison is strictly greater.
    set_clock("2026-05-03T08:00:00Z")
    departed_at = validate_success(api_client.depart_railcar(car_at["id"], YARD))
    assert departed_at["dwell_charge_cents"] == 0
    set_clock("2026-05-03T09:00:00Z")
    departed_over = validate_success(api_client.depart_railcar(car_over["id"], YARD))
    assert departed_over["dwell_charge_cents"] == 500, (
        "49h dwell - 48h free = 1 billable hour at 500c")
    summary = validate_success(api_client.get_dwell_summary(car_over["id"], ADMIN))
    assert summary["billable_hours"] == pytest.approx(1.0, abs=0.001)
