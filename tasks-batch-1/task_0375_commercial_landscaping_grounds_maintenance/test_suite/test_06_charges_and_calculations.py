"""Calculation rules: add-on tiered pricing, storm dispatch charge & crew
selection, equipment usage cost, and invoice subtotal/tax/total.

Translates queue A (Difficulty) `combinatorial_formula` and the storm
`dual_variant_calc` instance, plus queue B (Corner) `calculations` instances.
"""
from test_helpers import (
    validate_success, get_success_data,
    create_account_payload, create_site_payload, create_crew_payload,
    create_storm_event_payload, create_equipment_payload,
    create_reservation_payload, create_invoice_payload,
    create_visit_payload,
    fixtures,
)
from test_helpers.test_users import TEST_USERS

AM = TEST_USERS["account_manager_headers"]
CL = TEST_USERS["crew_lead_headers"]
DO = TEST_USERS["dispatch_operator_headers"]


# ---------------------------------------------------------------------------
# Queue A — combinatorial_formula: add-on per-bucket rounding
# ---------------------------------------------------------------------------
def test_addon_charge_round_per_bucket_then_sum(api):
    """PRD §3.6: "The second bucket is the second-tier unit count times
    `unit_price_cents` times the factor (one minus 0.10), rounded half-up to a
    whole cent. ... The rounding here is applied independently to each tier bucket
    *before* the buckets are added — the order is pinned to
    round-per-bucket-then-sum".

    Design: Difficulty/combinatorial_formula/addon_charge_round_per_bucket_then_sum
    """
    scenario = fixtures.setup_scheduled_visit(service_type="MULCH", frequency="SEASONAL")
    addon = get_success_data(api.create_addon(
        {"service_visit_id": scenario["visit"]["id"], "addon_type": "MULCH_INSTALL",
         "quantity": 15, "unit_price_cents": 333}, CL))
    approved = validate_success(api.approve_addon(addon["id"], AM), expected_status=200)
    # bucket1 = 10*333 = 3330; bucket2 = round_half_up(5*333*0.90 = 1498.5) = 1499 -> 4829
    assert approved["addon_charge_cents"] == 4829
    assert approved["status"] == "APPROVED"


def test_addon_charge_first_tier_only_no_discount(api):
    """PRD §3.6: "The first 10 units are priced at the full `unit_price_cents`
    each. ... The first bucket is the first-tier unit count times
    `unit_price_cents`."

    Design: Difficulty/combinatorial_formula/addon_charge_round_per_bucket_then_sum
    """
    scenario = fixtures.setup_scheduled_visit(service_type="MULCH", frequency="SEASONAL")
    # quantity=8 (<=10): only the first bucket, no discount
    addon = get_success_data(api.create_addon(
        {"service_visit_id": scenario["visit"]["id"], "addon_type": "MULCH_INSTALL",
         "quantity": 8, "unit_price_cents": 333}, CL))
    approved = validate_success(api.approve_addon(addon["id"], AM), expected_status=200)
    assert approved["addon_charge_cents"] == 8 * 333  # 2664


# ---------------------------------------------------------------------------
# Queue A — combinatorial_formula: storm tier branch with priority multiplier
# ---------------------------------------------------------------------------
def test_storm_dispatch_heavy_tier_priority_surcharge(api):
    """PRD §3.8: "otherwise (8 or more) the base is 60000 cents. The surcharge
    multiplier is one plus 0.25 when the parent site's `snow_zone` is `PRIORITY`
    ... The `dispatch_charge_cents` is the base multiplied by the surcharge
    multiplier, rounded half-up to a whole cent."

    Design: Difficulty/combinatorial_formula/storm_dispatch_charge_tier_branch_with_priority_multiplier
    """
    setup = fixtures.setup_reported_storm_event(
        snow_zone="PRIORITY", snowfall_inches=8,
        certified_crews=[{"hourly_rate_cents": 5000, "certified_for_snow": True}])
    dispatched = validate_success(api.dispatch_storm_event(setup["event"]["id"], DO), expected_status=200)
    # snowfall 8 -> heavy base 60000; PRIORITY -> round(60000*1.25) = 75000
    assert dispatched["dispatch_charge_cents"] == 75000


def test_storm_dispatch_boundary_8_inches_is_heavy_tier(api):
    """PRD §3.8: "The two tier boundaries at 3 and 8 inches are strict, so exactly
    3 inches falls into the moderate tier and exactly 8 inches falls into the
    heavy tier."

    Design: Difficulty/combinatorial_formula/storm_dispatch_charge_tier_branch_with_priority_multiplier
    """
    setup = fixtures.setup_reported_storm_event(
        snow_zone="PRIORITY", snowfall_inches=8,
        certified_crews=[{"hourly_rate_cents": 5000, "certified_for_snow": True}])
    dispatched = validate_success(api.dispatch_storm_event(setup["event"]["id"], DO), expected_status=200)
    # exactly 8 -> heavy tier (60000), not moderate (30000)
    assert dispatched["dispatch_charge_cents"] == 75000


# ---------------------------------------------------------------------------
# Queue A — dual_variant_calc: storm dispatch charge vs crew selection
# ---------------------------------------------------------------------------
def test_storm_dispatch_charge_and_crew_selection_distinct_domains(api):
    """PRD §3.8: "if `snowfall_inches` is strictly less than 8, the base is 30000
    cents ... The surcharge multiplier is one plus 0.25 when the parent site's
    `snow_zone` is `PRIORITY`".
    PRD §3.8: "Among that candidate set, it ranks crews ascending by
    `hourly_rate_cents` (cheapest certified crew first), breaking ties by earliest
    `created_at` ascending. The `assigned_crew_id` is the `id` of the first crew
    after this ordering."

    Design: Difficulty/dual_variant_calc/storm_dispatch_charge_vs_crew_selection_distinct_domains
    """
    setup = fixtures.setup_reported_storm_event(
        snow_zone="PRIORITY", snowfall_inches=5,
        certified_crews=[
            {"hourly_rate_cents": 4000, "certified_for_snow": True},   # cheap (selected)
            {"hourly_rate_cents": 9000, "certified_for_snow": True},   # pricey
        ])
    cheap_id = setup["crews"][0]["id"]
    dispatched = validate_success(api.dispatch_storm_event(setup["event"]["id"], DO), expected_status=200)
    # snowfall 5 -> moderate 30000; PRIORITY -> round(30000*1.25) = 37500
    assert dispatched["dispatch_charge_cents"] == 37500
    assert dispatched["assigned_crew_id"] == cheap_id
    assert dispatched["status"] == "DISPATCHED"


def test_storm_dispatch_selects_cheapest_certified_crew(api):
    """PRD §3.8: "Among that candidate set, it ranks crews ascending by
    `hourly_rate_cents` (cheapest certified crew first) ... The `assigned_crew_id`
    is the `id` of the first crew after this ordering."

    Design: Difficulty/dual_variant_calc/storm_dispatch_charge_vs_crew_selection_distinct_domains
    """
    setup = fixtures.setup_reported_storm_event(
        snow_zone="PRIORITY", snowfall_inches=5,
        certified_crews=[
            {"hourly_rate_cents": 4000, "certified_for_snow": True},
            {"hourly_rate_cents": 9000, "certified_for_snow": True},
        ])
    cheap_id = setup["crews"][0]["id"]
    dispatched = validate_success(api.dispatch_storm_event(setup["event"]["id"], DO), expected_status=200)
    assert dispatched["assigned_crew_id"] == cheap_id


# ---------------------------------------------------------------------------
# Queue B — calculations
# ---------------------------------------------------------------------------
def test_equipment_usage_cost_ceil_boundary_61_minutes(api):
    """PRD §3.7: "`usage_cost_cents` is computed as the number of whole hours of
    the reserved window — that is, `reserved_minutes` divided by 60 and rounded
    *up* to a whole number of hours — multiplied by the asset's
    `hourly_usage_cost_cents`. Because the ceiling is on hours, a 60-minute window
    bills as one hour and a 61-minute window bills as two hours."

    Design: Corner/calculations/equipment_usage_cost_ceil_boundary_61_minutes
    """
    scenario = fixtures.setup_scheduled_visit()
    asset = get_success_data(api.create_equipment(
        create_equipment_payload(scenario["account"]["id"], name="Edger",
                                 hourly_usage_cost_cents=1000, service_interval_hours=100), AM))
    resp = api.create_reservation(
        create_reservation_payload(asset["id"], scenario["visit"]["id"],
                                   window_start_minute=0, window_end_minute=61), CL)
    data = validate_success(resp, expected_status=201)
    assert data["reserved_minutes"] == 61
    # 61 minutes -> ceil(61/60) = 2 hours -> 2*1000 = 2000
    assert data["usage_cost_cents"] == 2000


def test_storm_charge_light_tier_standard_zone_no_surcharge(api):
    """PRD §3.8: "If `snowfall_inches` is strictly less than 3, the base is 15000
    cents ... The surcharge multiplier is ... exactly one for `STANDARD` or
    `EXEMPT` zones."

    Design: Corner/calculations/storm_charge_light_tier_standard_zone_no_surcharge
    """
    setup = fixtures.setup_reported_storm_event(
        snow_zone="STANDARD", snowfall_inches=2,
        certified_crews=[{"hourly_rate_cents": 5000, "certified_for_snow": True}])
    dispatched = validate_success(api.dispatch_storm_event(setup["event"]["id"], DO), expected_status=200)
    assert dispatched["dispatch_charge_cents"] == 15000


def test_storm_crew_selector_tie_break_created_at(api):
    """PRD §3.8: "it ranks crews ascending by `hourly_rate_cents` (cheapest
    certified crew first), breaking ties by earliest `created_at` ascending. ...
    The resource `id` is never itself a ranking input."

    Design: Corner/calculations/storm_crew_selector_tie_break_created_at
    """
    setup = fixtures.setup_reported_storm_event(
        snow_zone="STANDARD", snowfall_inches=5,
        certified_crews=[
            {"hourly_rate_cents": 5000, "certified_for_snow": True},   # earliest -> selected
            {"hourly_rate_cents": 5000, "certified_for_snow": True},   # later, equal rate
        ])
    early_id = setup["crews"][0]["id"]
    dispatched = validate_success(api.dispatch_storm_event(setup["event"]["id"], DO), expected_status=200)
    assert dispatched["assigned_crew_id"] == early_id


def test_invoice_subtotal_excludes_written_off_visits(api):
    """PRD §3.10: "Visits that are `WRITTEN_OFF` (whether by an explicit write-off
    or by a failed inspection) and visits already `INVOICED` are excluded. ... A
    contract with no completed-and-unbilled visits yields a sweep of
    `line_item_count` equal to 0".

    Design: Corner/calculations/invoice_subtotal_excludes_written_off_visits
    """
    scenario = fixtures.setup_completed_visit(actual_labor_minutes=90)
    get_success_data(api.write_off_visit(scenario["visit"]["id"], AM))
    invoice = validate_success(
        api.create_invoice(create_invoice_payload(scenario["contract"]["id"], "2026-08"), AM),
        expected_status=201)
    assert invoice["line_item_count"] == 0
    assert invoice["subtotal_cents"] == 0


def test_invoice_total_sum_then_round_two_visits(api):
    """PRD §3.10: "tax is computed once on the whole swept subtotal: `tax_cents`
    is `subtotal_cents` multiplied by the tax rate of 0.0825, rounded half-up to a
    whole cent. The `total_cents` is `subtotal_cents` plus `tax_cents`. This is a
    single sum-then-round operation on the aggregate subtotal".

    Design: Corner/calculations/invoice_total_sum_then_round_two_visits
    """
    # Build two completed visits on one contract: A (final 68000) and B (final 59000).
    scenario = fixtures.setup_active_contract_scenario(
        turf_area_sqft=5000, base_rate_cents=10000, hourly_rate_cents=6000)
    plan_id = scenario["plan"]["id"]
    route_id = scenario["route"]["id"]
    contract_id = scenario["contract"]["id"]
    cver = scenario["contract_version"]
    vA = get_success_data(api.create_visit(
        create_visit_payload(plan_id, route_id, cver, slot_start_minute=480, slot_duration_minute=90), CL))
    cver2 = fixtures.get_contract_version(contract_id)
    vB = get_success_data(api.create_visit(
        create_visit_payload(plan_id, route_id, cver2, slot_start_minute=600, slot_duration_minute=90), CL))
    asset = get_success_data(api.create_equipment(create_equipment_payload(scenario["account"]["id"]), AM))
    get_success_data(api.create_reservation(
        create_reservation_payload(asset["id"], vA["id"], window_start_minute=480, window_end_minute=600), CL))
    get_success_data(api.lock_route(route_id, CL))
    get_success_data(api.start_visit(vA["id"], CL))
    get_success_data(api.complete_visit(vA["id"], {"actual_labor_minutes": 120}, CL))  # final 68000
    get_success_data(api.start_visit(vB["id"], CL))
    get_success_data(api.complete_visit(vB["id"], {"actual_labor_minutes": 90}, CL))   # final 59000
    invoice = validate_success(
        api.create_invoice(create_invoice_payload(contract_id, "2026-09"), AM), expected_status=201)
    assert invoice["line_item_count"] == 2
    assert invoice["subtotal_cents"] == 127000
    # tax = round_half_up(127000*0.0825 = 10477.5) = 10478; total = 137478
    assert invoice["tax_cents"] == 10478
    assert invoice["total_cents"] == 137478
