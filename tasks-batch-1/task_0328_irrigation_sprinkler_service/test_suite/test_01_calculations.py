"""Monetary, risk-scoring, and pricing calculations.

Covers quote estimated-vs-final divergence, winter-risk provisional-vs-assessed
divergence, the tiered blowout price with PSI surcharge, per-line final rounding,
order-sensitive plan dues, backflow result precision, and committed-cost reconciliation.
"""
import pytest
from test_helpers import (
    validate_success,
    setup_customer_property_system,
    setup_customer_property,
    setup_approved_quote_workorder,
    setup_backflow_ready,
    record_backflow_test,
    create_customer,
    create_property,
    create_zone,
    create_technician,
    create_work_order,
    complete_work_order_full,
    create_route,
    create_route_stop,
    make_technician_headers,
    TEST_USERS,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]


# ===========================================================================
# Queue A — dual_variant_calc
# ===========================================================================
def test_quote_estimated_and_final_totals_diverge(api):
    """PRD §3.3: "That whole subtotal is then multiplied by one plus the tax rate
    of 8% (a factor of 1.08), and the single resulting figure is rounded half up to
    whole cents to give `estimated_total_cents`."
    PRD §3.4: "The labor component is the `actual_labor_cents` multiplied by the 1.08
    tax factor and rounded half up to whole cents; the parts component is the
    `actual_parts_cents` multiplied by the same 1.08 factor and rounded half up to
    whole cents; and `final_total_cents` is the sum of those two already-rounded components."

    Design: Difficulty/dual_variant_calc/quote_estimated_vs_final_total_diverge
    """
    cust, prop, sys = setup_customer_property_system(company_name="Acme Lawns")
    tech = create_technician(full_name="Tina Tech")
    line_items = [
        {"description": "valve", "quantity": 1, "unit_rate_cents": 1431},
        {"description": "fitting", "quantity": 1, "unit_rate_cents": 806},
    ]
    _approved, wo_id = setup_approved_quote_workorder(
        cust["id"], prop["id"], quote_type="REPAIR", line_items=line_items)

    quote_after_send = validate_success(api.get_quote(_approved["id"], DISPATCHER))
    assert quote_after_send["estimated_total_cents"] == 2416, (
        f"estimated_total_cents should be 2416, got {quote_after_send['estimated_total_cents']}")

    # Drive the spawned work order through to COMPLETED with the actuals.
    tech_headers = make_technician_headers(tech["id"])
    route = create_route(tech["id"], route_date="2026-04-01")
    create_route_stop(route["id"], wo_id, route["version"], arrival_start_sec=28800, window_minutes=60)
    validate_success(api.depart_work_order(wo_id, tech_headers))
    validate_success(api.arrive_work_order(wo_id, tech_headers))
    validate_success(api.complete_work_order(
        wo_id, {"actual_labor_cents": 1431, "actual_parts_cents": 801}, tech_headers))

    quote = validate_success(api.get_quote(_approved["id"], DISPATCHER))
    assert quote["final_total_cents"] == 2410, (
        f"final_total_cents should be 2410, got {quote['final_total_cents']}")
    assert quote["estimated_total_cents"] != quote["final_total_cents"], (
        "estimated and final totals must diverge")


def test_winter_risk_provisional_exceeds_assessed_after_winterization(api):
    """PRD §3.8: "it sums the plant-type weight times `head_count` across all non-archived
    zones to form the exposure, multiplies that exposure by the pressure factor, and takes
    the smaller of that product and the 1000-point cap."
    PRD §3.8: "if the system does have a completed winterization work order, the drained
    exposure is zero. The `assessed_winter_risk` is then that drained exposure multiplied
    by the pressure factor, again capped at 1000."

    Design: Difficulty/dual_variant_calc/system_winter_risk_provisional_vs_assessed_diverge
    """
    cust = create_customer(company_name="Hill Co")
    prop = create_property(cust["id"])
    sys = validate_success(api.create_system(
        {"property_id": prop["id"], "controller_model": "Hunter", "static_psi": 90}, DISPATCHER),
        expected_status=201)
    create_zone(sys["id"], 1, plant_type="TURF", head_count=10, gpm_per_head=18)
    create_zone(sys["id"], 2, plant_type="ROTOR", head_count=6, gpm_per_head=22)
    tech = create_technician(full_name="Will Winter")

    complete_work_order_full(sys["id"], tech["id"], job_type="WINTERIZATION",
                             actual_labor_cents=5000, actual_parts_cents=1000,
                             estimated_cost_cents=9000, route_date="2026-10-15")

    system = validate_success(api.get_system(sys["id"], DISPATCHER))
    assert system["provisional_winter_risk"] == 116, (
        f"provisional_winter_risk should be 116, got {system['provisional_winter_risk']}")
    assert system["assessed_winter_risk"] == 0, (
        f"assessed_winter_risk should be 0 after winterization, got {system['assessed_winter_risk']}")
    assert system["season_state"] == "WINTERIZED"


# ===========================================================================
# Queue A — combinatorial_formula
# ===========================================================================
def test_blowout_price_tiered_rate_plus_psi_surcharge(api):
    """PRD §3.8: "The per-zone rate is tiered by that count: when the count is 4 or fewer
    the rate is 1200 cents per zone; when the count is from 5 through 10 the rate is 1000
    cents per zone; and when the count is 11 or more the rate is 850 cents per zone. A
    pressure surcharge is computed as the system's `static_psi` minus the high-pressure
    threshold of 80, multiplied by 50 cents per PSI, then floored at 0 and capped at 3000
    cents". PRD §3.8: "The `blowout_price_cents` is the base fee of 4500 cents, plus the
    per-zone rate times the zone count, plus the pressure surcharge."

    Design: Difficulty/combinatorial_formula/blowout_price_tiered_with_psi_surcharge
    """
    cust = create_customer(company_name="Tier Co")
    prop = create_property(cust["id"])
    sys = validate_success(api.create_system(
        {"property_id": prop["id"], "controller_model": "RainBird", "static_psi": 90}, DISPATCHER),
        expected_status=201)
    specs = [
        (1, "TURF", 4, 18), (2, "TURF", 4, 18), (3, "SHRUB", 4, 12),
        (4, "SHRUB", 4, 12), (5, "DRIP", 4, 5), (6, "ROTOR", 4, 22),
    ]
    for zn, pt, hc, gpm in specs:
        create_zone(sys["id"], zn, plant_type=pt, head_count=hc, gpm_per_head=gpm)

    data = validate_success(api.get_blowout_quote(sys["id"], DISPATCHER))
    assert data["zone_count"] == 6, f"zone_count should be 6, got {data['zone_count']}"
    assert data["blowout_price_cents"] == 11000, (
        f"blowout_price_cents should be 11000, got {data['blowout_price_cents']}")


def test_final_total_rounds_each_line_then_sums(api):
    """PRD §3.4: "The labor component is the `actual_labor_cents` multiplied by the 1.08
    tax factor and rounded half up to whole cents; the parts component is the
    `actual_parts_cents` multiplied by the same 1.08 factor and rounded half up to whole
    cents; and `final_total_cents` is the sum of those two already-rounded components.
    Because each of the two lines is taxed and rounded before they are added, the final
    figure can differ by a cent from the estimate even when the underlying raw amounts
    coincide — the estimate rounds once after summing, the final rounds each line then sums."

    Design: Difficulty/combinatorial_formula/quote_final_round_per_line_then_sum
    """
    cust, prop, sys = setup_customer_property_system(company_name="Round Co")
    tech = create_technician(full_name="Ray Round")
    line_items = [
        {"description": "valve", "quantity": 1, "unit_rate_cents": 1431},
        {"description": "fitting", "quantity": 1, "unit_rate_cents": 806},
    ]
    _approved, wo_id = setup_approved_quote_workorder(
        cust["id"], prop["id"], quote_type="REPAIR", line_items=line_items)

    tech_headers = make_technician_headers(tech["id"])
    route = create_route(tech["id"], route_date="2026-04-02")
    create_route_stop(route["id"], wo_id, route["version"], arrival_start_sec=28800, window_minutes=60)
    validate_success(api.depart_work_order(wo_id, tech_headers))
    validate_success(api.arrive_work_order(wo_id, tech_headers))
    validate_success(api.complete_work_order(
        wo_id, {"actual_labor_cents": 1431, "actual_parts_cents": 801}, tech_headers))

    quote = validate_success(api.get_quote(_approved["id"], DISPATCHER))
    assert quote["final_total_cents"] == 2410, (
        f"final_total_cents should be 2410 (1545+865), got {quote['final_total_cents']}")


def test_plan_dues_discount_tier_keyed_on_gross(api):
    """PRD §3.7: "The gross is that per-visit rate multiplied by `visits_per_year`. The
    loyalty discount is then chosen from the gross — and the gross must be computed first
    before the discount tier can be selected: if the gross is at least 120000 cents the
    discount is 15%, otherwise if the gross is at least 60000 cents the discount is 8%,
    otherwise there is no discount. The `annual_dues_cents` is the gross multiplied by one
    minus that discount fraction, rounded half up to whole cents once at the end."

    Design: Difficulty/combinatorial_formula/plan_dues_circular_tier_evaluation_order
    """
    _cust, prop = setup_customer_property(company_name="Plan Co")
    plan = validate_success(api.create_plan(
        {"property_id": prop["id"], "tier": "PLUS", "visits_per_year": 8}, DISPATCHER),
        expected_status=201)
    assert plan["annual_dues_cents"] == 66240, (
        f"annual_dues_cents should be 66240 (72000 gross @ 8%), got {plan['annual_dues_cents']}")


# ===========================================================================
# Queue B — calculations section
# ===========================================================================
def test_backflow_passes_at_exact_minimum_thresholds(api):
    """PRD §3.5: "The `result` is `PASS` when the `relief_open_psi` is at least the minimum
    relief pressure of 2 PSI and the `checkvalve_hold_psi` is at least the minimum hold
    differential of 1 PSI". PRD §3.5: "Note that a relief reading exactly equal to 2, or a
    hold reading exactly equal to 1, passes, because each comparison is "at least," not
    "greater than.""

    Design: Corner/calculations/backflow_result_pass_at_exact_threshold
    """
    prop, sys, tester = setup_backflow_ready(has_backflow_device=True, certified=True)
    test = record_backflow_test(sys["id"], tester["id"], relief_open_psi=2, checkvalve_hold_psi=1)
    assert test["result"] == "PASS", f"result should be PASS at boundary, got {test['result']}"

    system = validate_success(api.get_system(sys["id"], DISPATCHER))
    assert system["backflow_status"] == "CERTIFIED", (
        f"backflow_status should be CERTIFIED, got {system['backflow_status']}")


def test_backflow_fails_below_threshold_sets_system_failed(api):
    """PRD §3.5: "if either measurement falls below its minimum, the `result` is `FAIL`."
    PRD §3.5: "A `FAIL` sets the system's `backflow_status` to `FAILED` and recomputes the
    property's `compliance_status`, which necessarily remains `NON_COMPLIANT`."

    Design: Corner/calculations/backflow_result_fail_below_threshold_sets_failed
    """
    prop, sys, tester = setup_backflow_ready(has_backflow_device=True, certified=True)
    test = record_backflow_test(sys["id"], tester["id"], relief_open_psi=1, checkvalve_hold_psi=3)
    assert test["result"] == "FAIL", f"result should be FAIL below boundary, got {test['result']}"

    system = validate_success(api.get_system(sys["id"], DISPATCHER))
    assert system["backflow_status"] == "FAILED"
    property_ = validate_success(api.get_property(prop["id"], DISPATCHER))
    assert property_["compliance_status"] == "NON_COMPLIANT"


def test_blowout_price_tier_boundary_at_five_zones(api):
    """PRD §3.8: "when the count is 4 or fewer the rate is 1200 cents per zone; when the
    count is from 5 through 10 the rate is 1000 cents per zone". PRD §3.8: "The
    `blowout_price_cents` is the base fee of 4500 cents, plus the per-zone rate times the
    zone count, plus the pressure surcharge."

    Design: Corner/calculations/blowout_price_tier_boundary_at_five_zones
    """
    cust = create_customer(company_name="Tb Co")
    prop = create_property(cust["id"])
    sys = validate_success(api.create_system(
        {"property_id": prop["id"], "controller_model": "Hunter", "static_psi": 60}, DISPATCHER),
        expected_status=201)
    specs = [
        (1, "TURF", 4, 18), (2, "TURF", 4, 18), (3, "SHRUB", 4, 12),
        (4, "DRIP", 4, 5), (5, "ROTOR", 4, 22),
    ]
    for zn, pt, hc, gpm in specs:
        create_zone(sys["id"], zn, plant_type=pt, head_count=hc, gpm_per_head=gpm)

    data = validate_success(api.get_blowout_quote(sys["id"], DISPATCHER))
    assert data["zone_count"] == 5
    assert data["blowout_price_cents"] == 9500, (
        f"blowout_price_cents should be 9500, got {data['blowout_price_cents']}")


def test_plan_dues_premium_high_loyalty_tier(api):
    """PRD §3.7: "The per-visit base rate is fixed by tier: 6000 cents for `BASIC`, 9000
    cents for `PLUS`, and 13000 cents for `PREMIUM`." PRD §3.7: "if the gross is at least
    120000 cents the discount is 15%". PRD §3.7: "The `annual_dues_cents` is the gross
    multiplied by one minus that discount fraction, rounded half up to whole cents once at
    the end."

    Design: Corner/calculations/plan_dues_premium_high_loyalty_tier
    """
    _cust, prop = setup_customer_property(company_name="Pr Co")
    plan = validate_success(api.create_plan(
        {"property_id": prop["id"], "tier": "PREMIUM", "visits_per_year": 12}, DISPATCHER),
        expected_status=201)
    assert plan["annual_dues_cents"] == 132600, (
        f"annual_dues_cents should be 132600 (156000 gross @ 15%), got {plan['annual_dues_cents']}")


# ===========================================================================
# Queue B — cross_cutting_complexity_layers (derived field reconciliation)
# ===========================================================================
def test_committed_cost_reconciles_across_two_work_orders(api):
    """PRD §3.4: "Creating any work order immediately debits the serviced system's
    `committed_cost_cents` by the work order's `estimated_cost_cents`. A system's
    `committed_cost_cents` is, by definition, the sum of `estimated_cost_cents` over all
    work orders on that system whose `completion_status` is not yet one of `COMPLETED`,
    `FAILED`, or `CANCELLED`."

    Design: Corner/cross_cutting_complexity_layers/derived_committed_cost_reconciles_after_two_workorders
    """
    _cust, _prop, sys = setup_customer_property_system(company_name="Dcc Co")
    create_work_order(sys["id"], job_type="HEAD_REPAIR", estimated_minutes=20, estimated_cost_cents=3000)
    create_work_order(sys["id"], job_type="LEAK_REPAIR", estimated_minutes=30, estimated_cost_cents=5000)

    system = validate_success(api.get_system(sys["id"], DISPATCHER))
    assert system["committed_cost_cents"] == 8000, (
        f"committed_cost_cents should be 8000, got {system['committed_cost_cents']}")
