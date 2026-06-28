"""Calculation correctness: load sizing, warranty refund, plan pricing,
repair invoicing, compliance scoring, fuel adequacy.

Covers difficulty queue A (dual_variant_calc, combinatorial_formula,
boundary_precision_check/compliance) and corner queue B (calculations section).
"""
import pytest

from test_helpers import (
    api_client,
    get_success_data,
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    fixtures as fx,
    factories as f,
)

SM = TEST_USERS["service_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]

# Five-appliance set shared by the STAGGERED-vs-FULL_LOAD divergence tests.
APPLIANCES_5 = [
    {"name": "ac_5ton", "running_watts": 5000, "starting_watts": 16000},
    {"name": "well_pump", "running_watts": 1000, "starting_watts": 3000},
    {"name": "fridge", "running_watts": 700, "starting_watts": 2200},
    {"name": "sump", "running_watts": 800, "starting_watts": 2000},
    {"name": "lights", "running_watts": 1500, "starting_watts": 1500},
]


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty: dual_variant_calc / load_sizing_staggered_vs_full_load_diverges
# ─────────────────────────────────────────────────────────────────────────────
def _draft_ng_project():
    _, project = fx.create_draft_project(fuel_type="NG")
    return project


def test_load_sizing_staggered_uses_single_largest_surge(api):
    """PRD §3.2: "Under `STAGGERED`, motor sequencing is assumed, so only the single
    largest surge delta across all appliances is added to the running load;
    `peak_demand_w` is the running load plus that one largest surge delta."
    PRD §3.2: "the required volt-amps is the peak watt demand divided by a power
    factor of 0.8. The `computed_required_kw` is that volt-amps figure divided by
    1000, then rounded up to the next 0.25 kW increment"

    Design: Difficulty/dual_variant_calc/load_sizing_staggered_vs_full_load_diverges
    """
    project = _draft_ng_project()
    res = api.create_load_assessment(
        project["id"], f.create_load_assessment_payload(method="STAGGERED", appliances=APPLIANCES_5), SM
    )
    assessment = validate_success(res, 201)
    assert assessment["peak_demand_w"] == 20000, "running 9000 + largest surge 11000 = 20000"
    assert assessment["computed_required_kw"] == 25.0, "ceil_to_quarter(20000/0.8/1000) = 25.0"


def test_load_sizing_full_load_sums_all_surges(api):
    """PRD §3.2: "Under `FULL_LOAD`, no sequencing is assumed, so every surge delta
    coincides; `peak_demand_w` is the running load plus the sum of all appliance
    surge deltas — which yields a strictly larger result than `STAGGERED` for the
    same appliances."

    Design: Difficulty/dual_variant_calc/load_sizing_staggered_vs_full_load_diverges
    """
    project = _draft_ng_project()
    res = api.create_load_assessment(
        project["id"], f.create_load_assessment_payload(method="FULL_LOAD", appliances=APPLIANCES_5), SM
    )
    assessment = validate_success(res, 201)
    assert assessment["peak_demand_w"] == 24700, "running 9000 + all surges 15700 = 24700"
    assert assessment["computed_required_kw"] == 31.0, "ceil_to_quarter(24700/0.8/1000) = 31.0"


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty: dual_variant_calc / warranty_refund_calendar_vs_usage_diverges
# ─────────────────────────────────────────────────────────────────────────────
def _activated_unit_with_runtime(runtime_hours):
    """Activate a unit (warranty_start 2026-01-01, 60mo) then run a PAID dispatch
    that resolves with the given runtime, advancing the unit's runtime_hours."""
    setup = fx.setup_activated_unit(rated_kw=26, warranty_months=60)
    tech_id = setup["technician"]["id"]
    unit_id = setup["unit"]["id"]
    disp = fx.dispatch_in_progress(unit_id, tech_id, labor_cents=0, parts_cents=0)
    from test_helpers import make_technician_headers
    get_success_data(
        api_client.resolve_dispatch(
            disp["id"], {"runtime_added_hours": runtime_hours}, make_technician_headers(tech_id)
        )
    )
    return setup, unit_id


def test_warranty_refund_usage_basis_ages_unit_by_runtime(api):
    """PRD §3.7: "under `USAGE` the elapsed is the larger of the calendar-elapsed
    months and the usage-elapsed months, so a heavily run unit ages faster and
    earns a smaller refund than `CALENDAR` would for the same dates."
    PRD §3.7: "The `refund_cents` is a coverage value of 240000 cents multiplied by
    remaining divided by total, rounded half up to whole cents."

    Design: Difficulty/dual_variant_calc/warranty_refund_calendar_vs_usage_diverges
    """
    setup, unit_id = _activated_unit_with_runtime(500)
    # Advance to 6 calendar months; usage_elapsed = ceil(500/50) = 10 > 6.
    fx.set_clock("2026-07-01T00:00:00Z")
    unit = get_success_data(api.get_unit(unit_id, SM))
    claim = get_success_data(
        api.create_warranty_claim(
            unit_id, f.warranty_claim_payload(unit["version"], description="control board fault"), SM
        )
    )
    get_success_data(api.review_claim(claim["id"], CO))
    res = api.adjudicate_claim(
        claim["id"],
        f.adjudicate_payload("APPROVE", resolution="PRORATED_REFUND", refund_basis="USAGE"),
        CO,
    )
    adjudicated = validate_success(res, 200)
    # elapsed=max(6,10)=10, remaining=50, 240000*50/60 = 200000.
    assert adjudicated["refund_cents"] == 200000


def test_warranty_refund_calendar_basis_ignores_runtime(api):
    """PRD §3.7: "under `CALENDAR` the elapsed is the calendar-elapsed months only,
    ignoring runtime"
    PRD §3.7: "The `refund_cents` is a coverage value of 240000 cents multiplied by
    remaining divided by total, rounded half up to whole cents."

    Design: Difficulty/dual_variant_calc/warranty_refund_calendar_vs_usage_diverges
    """
    setup, unit_id = _activated_unit_with_runtime(500)
    fx.set_clock("2026-07-01T00:00:00Z")
    unit = get_success_data(api.get_unit(unit_id, SM))
    claim = get_success_data(
        api.create_warranty_claim(
            unit_id, f.warranty_claim_payload(unit["version"], description="control board fault"), SM
        )
    )
    get_success_data(api.review_claim(claim["id"], CO))
    res = api.adjudicate_claim(
        claim["id"],
        f.adjudicate_payload("APPROVE", resolution="PRORATED_REFUND", refund_basis="CALENDAR"),
        CO,
    )
    adjudicated = validate_success(res, 200)
    # CALENDAR: elapsed=6, remaining=54, 240000*54/60 = 216000 (> USAGE's 200000).
    assert adjudicated["refund_cents"] == 216000


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty: combinatorial_formula / plan_price_tiered_with_bundle_discount_mode_a
# ─────────────────────────────────────────────────────────────────────────────
def test_plan_price_semiannual_bundled_applies_tier_and_discount(api):
    """PRD §3.6: "a unit rated above 24 kW prices each visit at 34000 cents."
    PRD §3.6: "When and only when the plan is both `monitoring_bundled` and
    `SEMI_ANNUAL`, a 10% bundle discount applies: `annual_price_cents` is the subtotal
    multiplied by the remaining 90% (one minus the discount), rounded half up — the
    discount is applied to the integer subtotal before rounding."

    Design: Difficulty/combinatorial_formula/plan_price_tiered_with_bundle_discount_mode_a
    """
    setup = fx.setup_activated_unit(rated_kw=26)
    res = api.create_maintenance_plan(
        setup["unit"]["id"], f.maintenance_plan_payload(frequency="SEMI_ANNUAL", monitoring_bundled=True), SM
    )
    plan = validate_success(res, 201)
    assert plan["visits_per_year"] == 2
    # subtotal = 34000*2 + 6000 = 74000; *0.90 = 66600.
    assert plan["annual_price_cents"] == 66600


def test_plan_price_full_value_without_discount_is_higher(api):
    """PRD §3.6: "The subtotal is that per-visit price multiplied by `visits_per_year`,
    plus a 6000-cent monitoring add-on when `monitoring_bundled` is true (and nothing
    when it is false). When and only when the plan is both `monitoring_bundled` and
    `SEMI_ANNUAL`, a 10% bundle discount applies"

    A SEMI_ANNUAL plan WITHOUT monitoring takes no discount, so its price (the full
    subtotal) is strictly larger than the bundled-and-discounted counterpart.

    Design: Difficulty/combinatorial_formula/plan_price_tiered_with_bundle_discount_mode_a
    """
    setup = fx.setup_activated_unit(rated_kw=26)
    res = api.create_maintenance_plan(
        setup["unit"]["id"], f.maintenance_plan_payload(frequency="SEMI_ANNUAL"), SM
    )
    plan = validate_success(res, 201)
    # No monitoring, no bundle discount: subtotal = 34000*2 = 68000.
    assert plan["annual_price_cents"] == 68000
    assert plan["annual_price_cents"] > 66600


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty: combinatorial_formula / repair_invoice_rounding_order_mode_b
# ─────────────────────────────────────────────────────────────────────────────
def test_repair_invoice_rounds_per_line_then_sums(api):
    """PRD §3.8: "each present line (a zero line is skipped from the sum) is taxed
    independently at a tax rate of 8.75% and rounded half up to whole cents, and the
    rounded line totals are summed last. This per-line-then-sum order is contractual
    and can differ from taxing the sum"

    Design: Difficulty/combinatorial_formula/repair_invoice_rounding_order_mode_b
    """
    from test_helpers import make_technician_headers  # noqa: F811
    setup = fx.setup_activated_unit(rated_kw=22)
    tech_id = setup["technician"]["id"]
    disp = fx.dispatch_in_progress(setup["unit"]["id"], tech_id, labor_cents=200, parts_cents=200)
    res = api.resolve_dispatch(disp["id"], {}, make_technician_headers(tech_id))
    resolved = validate_success(res, 200)
    assert resolved["billable"] is True
    # round(200*1.0875)=218 per line, summed = 436 (sum-then-round would give 435).
    assert resolved["invoice_total_cents"] == 436


def test_repair_invoice_per_line_order_observable_at_the_cent(api):
    """PRD §3.8: "the two lines are `labor_cents` and then `parts_cents` in that fixed
    order; each present line (a zero line is skipped from the sum) is taxed
    independently at a tax rate of 8.75% and rounded half up to whole cents, and the
    rounded line totals are summed last. This per-line-then-sum order is contractual
    and can differ from taxing the sum"

    Lines 200 and 100: per-line round(217.5)=218 + round(108.75)=109 = 327, which
    differs from the sum-then-round value round(300*1.0875)=round(326.25)=326. The
    pinned order is therefore observable at the cent on a second line combination.

    Design: Difficulty/combinatorial_formula/repair_invoice_rounding_order_mode_b
    """
    from test_helpers import make_technician_headers
    setup = fx.setup_activated_unit(rated_kw=22)
    tech_id = setup["technician"]["id"]
    disp = fx.dispatch_in_progress(setup["unit"]["id"], tech_id, labor_cents=200, parts_cents=100)
    res = api.resolve_dispatch(disp["id"], {}, make_technician_headers(tech_id))
    resolved = validate_success(res, 200)
    # round(200*1.0875)=218 + round(100*1.0875)=109 = 327 (sum-then-round = 326).
    assert resolved["invoice_total_cents"] == 327


# ─────────────────────────────────────────────────────────────────────────────
# Difficulty: boundary_precision_check / compliance_score_threshold_70_inclusive_health
# ─────────────────────────────────────────────────────────────────────────────
def _activated_monitoring_unit_at(clock_iso):
    setup = fx.setup_activated_unit(rated_kw=20, monitoring_enabled=True)
    fx.set_clock(clock_iso)
    return setup["unit"]["id"]


def test_compliance_score_below_threshold_degrades_monitoring(api):
    """PRD §3.5: "Otherwise it is 100 multiplied by completed divided by expected,
    rounded half up and then clamped to the 0-to-100 range."
    PRD §3.5: "From `OK` it drops to `DEGRADED` when `compliance_score` falls below 70
    while monitoring stays enabled"

    PRD §3.5 makes monitoring_health a stateful transition graph: DEGRADED is only
    reachable "From `OK`", and the sole edge out of OFFLINE is "From `OFFLINE`, the
    unit's `monitoring_health` becomes `OK` once monitoring is enabled and
    `compliance_score` is at least 70." So the unit must first reach OK (score >= 70)
    before a later sub-70 score can drop it to DEGRADED. The setup drives the score
    >= 70 first (OFFLINE -> OK), then advances the clock so the rising expected count
    pushes the score below 70 (OK -> DEGRADED).

    Design: Difficulty/boundary_precision_check/compliance_score_threshold_70_inclusive_health
    """
    # Activate with monitoring on; clock still at default 2026-01-01 (score 0, OFFLINE).
    setup = fx.setup_activated_unit(rated_kw=20, monitoring_enabled=True)
    unit_id = setup["unit"]["id"]
    # 7 SUCCESS logs, all dated before the OK clock so they all count there.
    fx.add_success_exercise_logs(
        unit_id,
        [
            "2026-01-08T00:00:00Z",
            "2026-01-15T00:00:00Z",
            "2026-01-22T00:00:00Z",
            "2026-01-29T00:00:00Z",
            "2026-02-05T00:00:00Z",
            "2026-02-12T00:00:00Z",
            "2026-02-19T00:00:00Z",
        ],
    )
    # Phase 1: clock -> days_active=70 -> expected=10; completed=7 -> score=70 >= 70.
    # OFFLINE -> OK (threshold inclusive on the at-least-70 side).
    fx.set_clock("2026-03-12T00:00:00Z")
    unit = get_success_data(api.get_unit(unit_id, SM))
    assert unit["compliance_score"] == 70
    assert unit["monitoring_health"] == "OK"
    # Phase 2: clock -> days_active=119 -> expected=17; completed=7 -> round(700/17)=41 < 70.
    # OK -> DEGRADED while monitoring stays enabled.
    fx.set_clock("2026-04-30T00:00:00Z")
    unit = get_success_data(api.get_unit(unit_id, SM))
    assert unit["compliance_score"] == 41
    assert unit["monitoring_health"] == "DEGRADED"


def test_compliance_score_at_threshold_70_keeps_monitoring_ok(api):
    """PRD §3.5: "From `OFFLINE`, the unit's `monitoring_health` becomes `OK` once
    monitoring is enabled and `compliance_score` is at least 70."
    PRD §3.5: "the threshold is inclusive on the at-least-70 side, so a score of
    exactly 70 is healthy."

    Design: Difficulty/boundary_precision_check/compliance_score_threshold_70_inclusive_health
    """
    # 10 expected (70 days), 7 completed -> round(100*7/10)=70 exactly.
    unit_id = _activated_monitoring_unit_at("2026-03-12T00:00:00Z")
    fx.add_success_exercise_logs(
        unit_id,
        [
            "2026-01-08T00:00:00Z",
            "2026-01-15T00:00:00Z",
            "2026-01-22T00:00:00Z",
            "2026-01-29T00:00:00Z",
            "2026-02-05T00:00:00Z",
            "2026-02-12T00:00:00Z",
            "2026-02-19T00:00:00Z",
        ],
    )
    unit = get_success_data(api.get_unit(unit_id, SM))
    # days_active=70 -> expected=10; completed=7 -> round(100*7/10)=70 == 70 (healthy).
    assert unit["compliance_score"] == 70
    assert unit["monitoring_health"] == "OK"


# ─────────────────────────────────────────────────────────────────────────────
# Corner: calculations / plan_price_annual_no_monitoring_no_discount
# ─────────────────────────────────────────────────────────────────────────────
def test_plan_price_annual_no_monitoring_no_discount(api):
    """PRD §3.6: "a unit rated above 24 kW prices each visit at 34000 cents."
    PRD §3.6: "In every other combination, `annual_price_cents` equals the subtotal
    with no discount."

    Design: Corner/calculations/plan_price_annual_no_monitoring_no_discount
    """
    setup = fx.setup_activated_unit(rated_kw=26)
    res = api.create_maintenance_plan(setup["unit"]["id"], f.maintenance_plan_payload(frequency="ANNUAL"), SM)
    plan = validate_success(res, 201)
    assert plan["visits_per_year"] == 1
    assert plan["annual_price_cents"] == 34000


# ─────────────────────────────────────────────────────────────────────────────
# Corner: calculations / fuel_inadequate_blocks_permit
# ─────────────────────────────────────────────────────────────────────────────
def test_fuel_inadequate_blocks_permit(api):
    """PRD §3.3: "the required BTU per hour is the project's `required_kw` multiplied
    by 10,000"
    PRD §3.3: "If the supply is insufficient, the permit is rejected with
    `ERR_FUEL_INADEQUATE`."

    Design: Corner/calculations/fuel_inadequate_blocks_permit
    """
    # required_kw 15.0 -> 150000 BTU/hr; supply 200000 - existing 100000 = 100000 < 150000.
    sized = fx.setup_sized_project(
        rated_kw=15, fuel_type="NG",
        appliances=[{"name": "ac", "running_watts": 4000, "starting_watts": 12000}],
    )
    res = api.permit_project(
        sized["project"]["id"],
        f.permit_payload(fuel_supply_btu_per_hr=200000, existing_load_btu_per_hr=100000),
        SM,
    )
    validate_error(res, ApiErrorId.ERR_FUEL_INADEQUATE.value)


# ─────────────────────────────────────────────────────────────────────────────
# Corner: calculations / fault_exercise_does_not_raise_compliance
# ─────────────────────────────────────────────────────────────────────────────
def test_fault_exercise_does_not_raise_compliance(api):
    """PRD §3.5: "The completed count is the number of this unit's exercise logs
    whose `result` is `SUCCESS` and whose `occurred_at` is at or before the current
    clock; `FAULT` exercises are logged but never count toward completed."

    Design: Corner/calculations/fault_exercise_does_not_raise_compliance
    """
    setup = fx.setup_activated_unit(rated_kw=20, monitoring_enabled=True)
    unit_id = setup["unit"]["id"]
    fx.set_clock("2026-01-29T00:00:00Z")  # 28 days -> expected 4.
    fx.add_success_exercise_logs(
        unit_id, ["2026-01-08T00:00:00Z", "2026-01-15T00:00:00Z", "2026-01-22T00:00:00Z"]
    )
    # FAULT log must not lift the completed count.
    get_success_data(api.create_exercise_log(unit_id, f.exercise_log_payload("2026-01-26T00:00:00Z", "FAULT"), SM))
    unit = get_success_data(api.get_unit(unit_id, SM))
    # 3 SUCCESS / 4 expected -> round(100*3/4)=75 (FAULT did not raise to 100).
    assert unit["compliance_score"] == 75
