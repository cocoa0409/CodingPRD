"""Aftermarket uplift policy, the LIST/QUOTE rounding-order divergence and the
fiscal gates that guard pricing."""

from test_helpers import (
    ApiErrorId, api_client, assert_line_variant_invariants, assert_part,
    assert_part_line, assert_price_rule, create_part_line_payload,
    create_price_rule, create_price_rule_payload, read_part, setup_catalogue,
    setup_scenario_with_work_order, TEST_USERS, validate_error,
    validate_paginated, validate_success,
)

PLANNER = TEST_USERS["planner_headers"]
PRICING = TEST_USERS["pricing_headers"]


def _stocked_line_scenario():
    """A DESIRABLE-banded part at unit_cost_cents 1333 with 100 units on the shelf
    and an OPEN DEGRADED work order on a covered machine."""
    return setup_scenario_with_work_order(
        work_type="BREAKDOWN", downtime_priority="DEGRADED",
        part_number="HP-1333", unit_cost_cents=1333, lead_time_days=60,
        weight_kg=12.5, hazmat=False, max_stock_units=30,
        dealer_code="D-GOLD-1", dealer_tier="GOLD", model_code="EM-100",
        serial_prefix="SN-100", qty_per_unit=5, stock_units=100,
        price_rules=(("DESIRABLE", 0.35, 0.60, 0.20),))


def test_part_line_list_and_quote_variants_diverge_by_three_cents(api):
    """PRD 3.5: "The **LIST** variant rounds first and multiplies second.
    `list_unit_price_cents` is the part's `unit_cost_cents` multiplied by one plus
    `effective_uplift_pct`, rounded half up to a whole cent at the **unit** level.
    `list_line_total_cents` is then that already-rounded unit price multiplied by the
    quantity."
    PRD 3.5: "The **QUOTE** variant multiplies first and rounds second.
    `quoted_line_total_cents` is the part's `unit_cost_cents` multiplied by the
    quantity and then by one plus `effective_uplift_pct`, with a single half-up
    rounding to a whole cent applied **once**, at line level."
    PRD 3.5: "With a `unit_cost_cents` of 1333, an `effective_uplift_pct` of 0.35 and
    a quantity of 7, the LIST variant yields a unit price of 1800 and a line total of
    12600 while the QUOTE variant yields 12597 — a positive three-cent delta."
    PRD 3.5: "`margin_pct` is computed off the QUOTE figure: it is
    `quoted_line_total_cents` minus the extended acquisition cost — that is,
    `unit_cost_cents` multiplied by the quantity — divided by
    `quoted_line_total_cents`, rounded half up to four decimal places."

    Design: Difficulty/dual_variant_calc/pricing_list_vs_quote_rounding_divergence_on_part_line
    """
    scenario = _stocked_line_scenario()
    line = validate_success(api.create_part_line(
        scenario["work_order"]["id"],
        create_part_line_payload(scenario["part"]["id"], 7),
        scenario["dealer_headers"]), 201)
    assert_part_line(line)

    assert line["effective_uplift_pct"] == 0.35
    assert line["list_unit_price_cents"] == 1800
    assert line["list_line_total_cents"] == 12600
    assert line["quoted_line_total_cents"] == 12597
    assert line["variant_delta_cents"] == 3
    assert line["margin_pct"] == 0.2593
    assert_line_variant_invariants(line)


def test_part_line_with_stock_available_reserves_and_holds_the_units(api):
    """PRD 3.6: "If `available_units` is at least `qty_requested`, the mode is
    `STOCK`. Stock on the shelf always wins, whatever the arithmetic elsewhere says."
    PRD 3.6: "A `STOCK` decision puts the line straight into `line_status`
    `RESERVED`, raises the part's `allocated_units` by `qty_requested`, recomputes
    `available_units`, and advances the part's `version`."
    PRD 2.8: "The derived counter `available_units` is always `on_hand_units` minus
    `allocated_units`, and it is recomputed after every movement that touches either
    operand."

    Design: Difficulty/dual_variant_calc/pricing_list_vs_quote_rounding_divergence_on_part_line
    """
    scenario = _stocked_line_scenario()
    line = validate_success(api.create_part_line(
        scenario["work_order"]["id"],
        create_part_line_payload(scenario["part"]["id"], 7),
        scenario["dealer_headers"]), 201)

    assert line["fulfillment_mode"] == "STOCK"
    assert line["line_status"] == "RESERVED"

    part = read_part(scenario["part"]["id"])
    assert_part(part)
    assert part["on_hand_units"] == 100
    assert part["allocated_units"] == 7
    assert part["available_units"] == 93


def test_price_quote_variant_delta_grows_with_quantity(api):
    """PRD 3.5: "A `PricingAnalyst`, an `AftermarketPlanner` or a `DealerUser` may
    also ask for a hypothetical quote on a part by supplying a `qty`; the response
    returns `effective_uplift_pct`, `list_unit_price_cents`, `list_line_total_cents`,
    `quoted_line_total_cents`, `variant_delta_cents` and `margin_pct` side by side,
    and it is subject to both the missing-rule and the margin-floor rejections."
    PRD 3.5: "`variant_delta_cents` records the divergence as `list_line_total_cents`
    minus `quoted_line_total_cents`. That divergence is real and its sign is not
    constant."
    PRD 3.5: "With a `unit_cost_cents` of 1333, an `effective_uplift_pct` of 0.35 and
    a quantity of 7, the LIST variant yields a unit price of 1800 and a line total of
    12600 while the QUOTE variant yields 12597 — a positive three-cent delta."

    Design: Difficulty/combinatorial_formula/price_quote_rounding_order_diverges_across_quantities
    """
    create_price_rule("DESIRABLE", 0.35, 0.60, 0.20)
    part = validate_success(api.create_part(
        {"part_number": "RND-1", "description": "Rounding probe part",
         "unit_cost_cents": 1333, "lead_time_days": 30, "weight_kg": 1.0},
        PLANNER), 201)

    q1 = validate_success(api.get_price_quote(part["id"], 1, PRICING))
    assert q1["list_unit_price_cents"] == 1800
    assert q1["list_line_total_cents"] == 1800
    assert q1["quoted_line_total_cents"] == 1800
    assert q1["variant_delta_cents"] == 0
    assert q1["effective_uplift_pct"] == 0.35

    q3 = validate_success(api.get_price_quote(part["id"], 3, PRICING))
    assert q3["list_line_total_cents"] == 5400
    assert q3["quoted_line_total_cents"] == 5399
    assert q3["variant_delta_cents"] == 1
    assert q3["effective_uplift_pct"] == 0.35

    q7 = validate_success(api.get_price_quote(part["id"], 7, PRICING))
    assert q7["list_line_total_cents"] == 12600
    assert q7["quoted_line_total_cents"] == 12597
    assert q7["variant_delta_cents"] == 3
    assert q7["effective_uplift_pct"] == 0.35


def test_price_quote_margin_tracks_the_quote_variant_and_catalogue_uses_qty_one(api):
    """PRD 3.5: "`margin_pct` is computed off the QUOTE figure: it is
    `quoted_line_total_cents` minus the extended acquisition cost — that is,
    `unit_cost_cents` multiplied by the quantity — divided by
    `quoted_line_total_cents`, rounded half up to four decimal places."
    PRD 3.5: "The part's own catalogue fields are simply this calculation evaluated at
    a quantity of one: `current_effective_uplift_pct` holds the `effective_uplift_pct`
    and `current_list_unit_price_cents` holds the LIST unit price."

    Design: Difficulty/combinatorial_formula/price_quote_rounding_order_diverges_across_quantities
    """
    create_price_rule("DESIRABLE", 0.35, 0.60, 0.20)
    part = validate_success(api.create_part(
        {"part_number": "RND-1", "description": "Rounding probe part",
         "unit_cost_cents": 1333, "lead_time_days": 30, "weight_kg": 1.0},
        PLANNER), 201)

    assert validate_success(api.get_price_quote(part["id"], 1, PRICING))["margin_pct"] \
        == 0.2594
    assert validate_success(api.get_price_quote(part["id"], 3, PRICING))["margin_pct"] \
        == 0.2593
    assert validate_success(api.get_price_quote(part["id"], 7, PRICING))["margin_pct"] \
        == 0.2593

    catalogue = read_part(part["id"])
    assert catalogue["current_list_unit_price_cents"] == 1800
    assert catalogue["current_effective_uplift_pct"] == 0.35


def test_price_rule_with_base_above_max_is_rejected(api):
    """PRD 3.5: "Publishing a rule whose `base_uplift_pct` is greater than its
    `max_uplift_pct` is refused with `ERR_UPLIFT_CAP_EXCEEDED`."

    Design: Corner/validations/price_rule_uplift_cap_exceeded_on_create
    """
    resp = api.create_price_rule(create_price_rule_payload(
        "VITAL", 0.70, 0.60, 0.30), PRICING)
    validate_error(resp, ApiErrorId.ERR_UPLIFT_CAP_EXCEEDED.value)

    _, meta = validate_paginated(api.list_price_rules(PRICING))
    assert meta["total_count"] == 0, "a refused rule must not be stored"


def test_margin_below_the_rule_floor_rejects_the_line(api):
    """PRD 3.5: "When `margin_pct` falls below the matched rule's `min_margin_pct`,
    the operation is refused with `ERR_MARGIN_FLOOR_BREACH`."
    PRD 3.5: "`margin_pct` is computed off the QUOTE figure: it is
    `quoted_line_total_cents` minus the extended acquisition cost — that is,
    `unit_cost_cents` multiplied by the quantity — divided by
    `quoted_line_total_cents`, rounded half up to four decimal places."

    Design: Corner/validations/margin_floor_breach_rejects_part_line
    """
    scenario = setup_scenario_with_work_order(
        part_number="MRG-1", unit_cost_cents=1333, lead_time_days=30,
        weight_kg=1.0, dealer_code="D-MRG", model_code="EM-V10",
        serial_prefix="SN-V10",
        price_rules=(("DESIRABLE", 0.10, 0.40, 0.20),))

    resp = api.create_part_line(
        scenario["work_order"]["id"],
        create_part_line_payload(scenario["part"]["id"], 7),
        scenario["dealer_headers"])
    validate_error(resp, ApiErrorId.ERR_MARGIN_FLOOR_BREACH.value)

    _, meta = validate_paginated(api.list_part_lines(
        PLANNER, params={"work_order_id": scenario["work_order"]["id"]}))
    assert meta["total_count"] == 0
    assert validate_success(api.get_work_order(
        scenario["work_order"]["id"], PLANNER))["status"] == "OPEN"


def test_no_active_rule_for_the_band_rejects_the_line(api):
    """PRD 3.5: "Pricing a part begins by selecting the single `ACTIVE` rule whose
    `criticality_class` matches the part's own."
    PRD 2.10: "Exactly one active price rule exists for the part's criticality band —
    otherwise `ERR_PRICE_RULE_NOT_FOUND` (404). Applies to adding a part line to a
    work order, reading a price quote for a part, and classifying a part."

    Design: Corner/validations/price_rule_not_found_when_no_active_rule_matches_class
    """
    scenario = setup_scenario_with_work_order(
        part_number="NPR-1", unit_cost_cents=1333, lead_time_days=30,
        weight_kg=1.0, dealer_code="D-NPR", model_code="EM-W10",
        serial_prefix="SN-W10",
        price_rules=(("VITAL", 0.55, 0.60, 0.30),))

    resp = api.create_part_line(
        scenario["work_order"]["id"],
        create_part_line_payload(scenario["part"]["id"], 1),
        scenario["dealer_headers"])
    validate_error(resp, ApiErrorId.ERR_PRICE_RULE_NOT_FOUND.value)

    part = read_part(scenario["part"]["id"])
    assert part["criticality_class"] == "DESIRABLE"
    assert part["current_list_unit_price_cents"] == 0


def test_patch_part_recomputes_catalogue_price_and_bumps_version(api):
    """PRD 3.2: "A planner may revise any subset of `description`,
    `unit_cost_cents`, `lead_time_days`, `weight_kg`, `hazmat` and `max_stock_units` on
    an existing part; every such amendment recomputes `current_effective_uplift_pct`
    and `current_list_unit_price_cents` and advances the part's `version`."
    PRD 3.5: "The part's own catalogue fields are simply this calculation evaluated at
    a quantity of one: `current_effective_uplift_pct` holds the `effective_uplift_pct`
    and `current_list_unit_price_cents` holds the LIST unit price."

    Design: Corner/endpoints/patch_part_recomputes_catalogue_price_and_bumps_version
    """
    rule = create_price_rule("DESIRABLE", 0.35, 0.60, 0.20)
    assert_price_rule(rule)
    part = validate_success(api.create_part(
        {"part_number": "PCH-1", "description": "Patch probe",
         "unit_cost_cents": 1333, "lead_time_days": 30, "weight_kg": 1.0},
        PLANNER), 201)
    assert part["current_list_unit_price_cents"] == 1800
    assert part["version"] == 1

    patched = validate_success(api.patch_part(
        part["id"], {"unit_cost_cents": 2000, "max_stock_units": 50}, PLANNER))
    assert patched["unit_cost_cents"] == 2000
    assert patched["max_stock_units"] == 50
    assert patched["current_effective_uplift_pct"] == 0.35
    assert patched["current_list_unit_price_cents"] == 2700
    assert patched["version"] == 2
    assert patched["description"] == "Patch probe", \
        "fields not supplied are left untouched"
