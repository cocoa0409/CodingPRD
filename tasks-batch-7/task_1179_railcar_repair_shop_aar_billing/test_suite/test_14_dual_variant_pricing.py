"""Dual-variant pricing: one repair line priced provisionally and finally
under two different price-master windows crossed mid-repair."""
from test_helpers import (
    TEST_USERS, add_car_with_inspection, add_price_entry, api_client,
    assign_slot_current_wo, authorize_current_wo, build_work_order,
    complete_current_wo, qa_current_wo, set_clock, setup_shop_ctx,
    start_current_wo, submit_current_wo, validate_success,
)

ADMIN = TEST_USERS["shop_admin"]


def _rate_window_scenario() -> dict:
    """One BRAKE_BEAM line: estimate under the May window (10000c/h), final
    under the July window (11000c/h), identical 2.0 hours both times."""
    ctx = setup_shop_ctx(clock="2026-05-01T08:00:00Z")
    add_price_entry(ctx, job_code="J-BRAKE-BEAM", description="Brake beam renewal",
                    labor_rate_cents_per_hour=10000, mobile_labor_rate_cents_per_hour=12000,
                    standard_labor_hours=2.0, mobile_trip_surcharge_cents=20000,
                    mobile_eligible=True, effective_from="2026-01-01",
                    effective_to="2026-06-30")
    add_price_entry(ctx, job_code="J-BRAKE-BEAM", description="Brake beam renewal H2",
                    labor_rate_cents_per_hour=11000, mobile_labor_rate_cents_per_hour=13000,
                    standard_labor_hours=2.0, mobile_trip_surcharge_cents=20000,
                    mobile_eligible=True, effective_from="2026-07-01",
                    effective_to="2026-12-31")
    add_car_with_inspection(ctx, car_number="1001", defects=[{
        "aar_defect_code": "AAR-3100", "defect_group": "BRAKE_BEAM",
        "cause_code": "WEAR", "severity": "MAJOR", "location": "B-end"}])
    build_work_order(ctx, lines=[{"job_code": "J-BRAKE-BEAM"}])
    submit_current_wo(ctx)
    authorize_current_wo(ctx)
    assign_slot_current_wo(ctx)
    start_current_wo(ctx)
    set_clock("2026-07-02T10:00:00Z")  # cross the window boundary mid-repair
    complete_current_wo(ctx, actual_hours=2.0)
    qa_current_wo(ctx, result="PASS")
    return ctx


def test_estimate_reading_uses_estimate_date_entry():
    """PRD §2.7: "The **provisional** reading is taken at estimate time: the
    price entry effective at the current logical-clock date is resolved, and
    the line's `estimate_labor_cents` is the entry's `standard_labor_hours`
    multiplied by the entry's shop `labor_rate_cents_per_hour`, rounded half up
    to whole cents."
    PRD §2.7: "The provisional reading never uses the mobile rate and never
    includes the trip surcharge."

    Design: Difficulty/dual_variant_calc/estimate_vs_final_pricing_across_rate_windows
    """
    ctx = _rate_window_scenario()
    line = validate_success(api_client.get_repair_line(ctx["wo_lines"][0]["id"], ADMIN))
    assert line["estimate_labor_cents"] == 20000, (
        "2.0 standard hours x 10000c/h from the entry effective at the "
        "2026-05-01 estimate date")
    assert line["estimate_total_cents"] == 20000, "no parts, so labor is the whole estimate"
    assert line["price_master_entry_id"] == ctx["entries"][0]["id"], (
        "the estimate pinned the entry effective at the estimate date")


def test_final_reading_uses_completion_date_entry():
    """PRD §2.7: "The **final** reading is taken when the quality gate passes:
    the price entry effective at the work order's completion date is resolved —
    which may be a different entry than the estimate used if a window boundary
    was crossed mid-repair — and the labor rate is the entry's
    `mobile_labor_rate_cents_per_hour` when the work order's `routing` is
    `MOBILE`, otherwise its `labor_rate_cents_per_hour`."

    Design: Difficulty/dual_variant_calc/estimate_vs_final_pricing_across_rate_windows
    """
    ctx = _rate_window_scenario()
    line = validate_success(api_client.get_repair_line(ctx["wo_lines"][0]["id"], ADMIN))
    assert line["status"] == "FINALIZED"
    assert line["final_labor_cents"] == 22000, (
        "2.0 actual hours x 11000c/h from the entry effective at the "
        "2026-07-02 completion date")
    assert line["final_total_cents"] == 22000
    assert line["final_labor_cents"] != line["estimate_labor_cents"], (
        "identical hours diverge because the rate window was crossed mid-repair")
