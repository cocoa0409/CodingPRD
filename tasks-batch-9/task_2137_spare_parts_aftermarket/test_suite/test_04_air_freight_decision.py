"""The emergency air-freight versus stock decision on a work order part line."""

from test_helpers import (
    ApiErrorId, api_client, assert_part_line, assert_replenishment_order,
    create_part_line_payload, read_part, setup_scenario_with_work_order,
    TEST_USERS, validate_error, validate_paginated, validate_success,
)

PLANNER = TEST_USERS["planner_headers"]
CONTROLLER = TEST_USERS["controller_headers"]


def _air_scenario():
    """GOLD dealer, MACHINE_DOWN job, part at 12.5 kg with a 45-day lead time and
    an empty shelf."""
    return setup_scenario_with_work_order(
        work_type="BREAKDOWN", downtime_priority="MACHINE_DOWN",
        part_number="AIR-1", unit_cost_cents=1333, lead_time_days=45,
        weight_kg=12.5, hazmat=False, dealer_code="D-GOLD-3",
        dealer_tier="GOLD", model_code="EM-300", serial_prefix="SN-300",
        price_rules=(("DESIRABLE", 0.35, 0.60, 0.20),))


def _threshold_scenario(dealer_tier="GOLD", dealer_code="D-THR",
                        part_number="THR-1", model_code="EM-D10",
                        serial_prefix="SN-D10"):
    """A 35 kg part on a one-day lead time: the air cost lands at exactly 150000
    against a 250000 downtime cost, so the net benefit is exactly 100000."""
    return setup_scenario_with_work_order(
        work_type="BREAKDOWN", downtime_priority="MACHINE_DOWN",
        part_number=part_number, unit_cost_cents=1333, lead_time_days=1,
        weight_kg=35.0, hazmat=False, dealer_code=dealer_code,
        dealer_tier=dealer_tier, model_code=model_code,
        serial_prefix=serial_prefix,
        price_rules=(("DESIRABLE", 0.35, 0.60, 0.20),))


def test_air_freight_net_benefit_and_freight_cost_from_four_inputs(api):
    """PRD 3.6: "First, an expected wait is established: zero days when
    `available_units` is at least `qty_requested`, and otherwise the part's full
    `lead_time_days`. A downtime cost is that wait multiplied by a daily rate keyed on
    the work order's `downtime_priority` — 250000 cents per day of downtime for a
    `MACHINE_DOWN` job, 60000 cents per day for a `DEGRADED` one, and nothing at all
    for a `PLANNED` one, which is why planned work never justifies expediting on cost
    grounds alone."
    PRD 3.6: "An air-freight cost is built in parallel. Billable weight is the part's
    `weight_kg` multiplied by the requested quantity and then rounded **up** to a
    whole kilogram. The raw charge is that billable weight at 2000 cents per kilogram
    plus a flat handling fee of 10000 cents; if the part's `hazmat` flag is true a
    dangerous-goods surcharge of 30000 cents is added on top. The final
    `air_freight_cost_cents` is the larger of that raw charge and a minimum charge of
    45000 cents. Subtracting the air-freight cost from the downtime cost gives
    `decision_net_benefit_cents`, which is stored on the line."
    PRD 3.6: "Otherwise, if `decision_net_benefit_cents` is **strictly greater** than
    100000 cents, the mode is `AIR_FREIGHT`. The comparison is strict: a net benefit
    of exactly 100000 does **not** expedite."
    PRD 3.6: "`freight_cost_cents` on the line is the computed air-freight cost when
    the mode resolved to `AIR_FREIGHT`, and 0 in every other case."

    Design: Difficulty/combinatorial_formula/air_freight_four_input_nonlinear_branch_selection
    """
    scenario = _air_scenario()
    line = validate_success(api.create_part_line(
        scenario["work_order"]["id"],
        create_part_line_payload(scenario["part"]["id"], 2),
        scenario["dealer_headers"]), 201)
    assert_part_line(line)

    assert line["decision_net_benefit_cents"] == 11190000
    assert line["freight_cost_cents"] == 60000
    assert line["fulfillment_mode"] == "AIR_FREIGHT"
    assert line["quoted_line_total_cents"] == 3599
    assert line["list_line_total_cents"] == 3600


def test_air_freight_backorders_the_line_and_auto_creates_an_emergency_order(api):
    """PRD 3.6: "An `AIR_FREIGHT` or `BACKORDER` decision instead puts the line into
    `line_status` `BACKORDERED` and moves the parent work order from `OPEN` to
    `PARTS_PENDING`. On the `AIR_FREIGHT` branch only, a replenishment order is
    additionally auto-created for the part with `order_type` `EMERGENCY_AIR`, a `qty`
    equal to `qty_requested`, `auto_generated` set to true, `approval_status`
    `PENDING`, `logistics_status` `NOT_STARTED`, and a `freight_cost_cents` equal to
    the line's own freight figure."
    PRD 3.7: "Replenishment orders can be listed and filtered by `part_id`, by
    `order_type`, by `approval_status`, by `logistics_status` and by `auto_generated`."

    Design: Difficulty/combinatorial_formula/air_freight_four_input_nonlinear_branch_selection
    """
    scenario = _air_scenario()
    line = validate_success(api.create_part_line(
        scenario["work_order"]["id"],
        create_part_line_payload(scenario["part"]["id"], 2),
        scenario["dealer_headers"]), 201)

    assert line["line_status"] == "BACKORDERED"
    assert validate_success(api.get_work_order(
        scenario["work_order"]["id"], PLANNER))["status"] == "PARTS_PENDING"

    orders, meta = validate_paginated(api.list_replenishment_orders(
        CONTROLLER, params={"part_id": scenario["part"]["id"],
                            "auto_generated": "true"}))
    assert meta["total_count"] == 1
    order = orders[0]
    assert_replenishment_order(order)
    assert order["order_type"] == "EMERGENCY_AIR"
    assert order["qty"] == 2
    assert order["freight_cost_cents"] == 60000
    assert order["auto_generated"] is True
    assert order["approval_status"] == "PENDING"
    assert order["logistics_status"] == "NOT_STARTED"

    part = read_part(scenario["part"]["id"])
    assert part["allocated_units"] == 0
    assert part["available_units"] == 0


def test_net_benefit_exactly_at_the_threshold_does_not_expedite(api):
    """PRD 3.6: "Otherwise, if `decision_net_benefit_cents` is **strictly greater**
    than 100000 cents, the mode is `AIR_FREIGHT`. The comparison is strict: a net
    benefit of exactly 100000 does **not** expedite."
    PRD 3.6: "Failing all of those, the mode is `BACKORDER`."
    PRD 3.6: "`freight_cost_cents` on the line is the computed air-freight cost when
    the mode resolved to `AIR_FREIGHT`, and 0 in every other case."

    Design: Difficulty/boundary_precision_check/air_freight_net_benefit_exactly_at_threshold_backorders
    """
    scenario = _threshold_scenario()
    line = validate_success(api.create_part_line(
        scenario["work_order"]["id"],
        create_part_line_payload(scenario["part"]["id"], 2),
        scenario["dealer_headers"]), 201)

    assert line["decision_net_benefit_cents"] == 100000
    assert line["fulfillment_mode"] == "BACKORDER"
    assert line["freight_cost_cents"] == 0


def test_threshold_backorder_creates_no_replenishment_order(api):
    """PRD 3.6: "An `AIR_FREIGHT` or `BACKORDER` decision instead puts the line into
    `line_status` `BACKORDERED` and moves the parent work order from `OPEN` to
    `PARTS_PENDING`. On the `AIR_FREIGHT` branch only, a replenishment order is
    additionally auto-created for the part with `order_type` `EMERGENCY_AIR`, a `qty`
    equal to `qty_requested`, `auto_generated` set to true, `approval_status`
    `PENDING`, `logistics_status` `NOT_STARTED`, and a `freight_cost_cents` equal to
    the line's own freight figure."

    Design: Difficulty/boundary_precision_check/air_freight_net_benefit_exactly_at_threshold_backorders
    """
    scenario = _threshold_scenario()
    line = validate_success(api.create_part_line(
        scenario["work_order"]["id"],
        create_part_line_payload(scenario["part"]["id"], 2),
        scenario["dealer_headers"]), 201)

    assert line["line_status"] == "BACKORDERED"
    assert validate_success(api.get_work_order(
        scenario["work_order"]["id"], PLANNER))["status"] == "PARTS_PENDING"

    _, meta = validate_paginated(api.list_replenishment_orders(
        CONTROLLER, params={"part_id": scenario["part"]["id"]}))
    assert meta["total_count"] == 0, \
        "the BACKORDER branch must not raise an emergency air order"


def test_platinum_machine_down_override_expedites_at_the_threshold(api):
    """PRD 3.6: "Otherwise, if the owning dealer's `tier` is `PLATINUM` **and** the
    work order's `downtime_priority` is `MACHINE_DOWN`, the mode is `AIR_FREIGHT`.
    This is a contractual override and is entirely independent of
    `decision_net_benefit_cents`."
    PRD 3.6: "`fulfillment_mode` is then resolved by walking four branches strictly
    top to bottom, where the first match wins and no later branch is evaluated:"
    PRD 3.6: "On the `AIR_FREIGHT` branch only, a replenishment order is additionally
    auto-created for the part with `order_type` `EMERGENCY_AIR`, a `qty` equal to
    `qty_requested`, `auto_generated` set to true, `approval_status` `PENDING`,
    `logistics_status` `NOT_STARTED`, and a `freight_cost_cents` equal to the line's
    own freight figure."

    Design: Corner/calculations/air_freight_platinum_override_ignores_net_benefit_threshold
    """
    scenario = _threshold_scenario(dealer_tier="PLATINUM", dealer_code="D-PLT",
                                   part_number="PLT-1", model_code="EM-S10",
                                   serial_prefix="SN-S10")
    line = validate_success(api.create_part_line(
        scenario["work_order"]["id"],
        create_part_line_payload(scenario["part"]["id"], 2),
        scenario["dealer_headers"]), 201)

    assert line["decision_net_benefit_cents"] == 100000
    assert line["fulfillment_mode"] == "AIR_FREIGHT"
    assert line["freight_cost_cents"] == 150000
    assert line["line_status"] == "BACKORDERED"

    orders, meta = validate_paginated(api.list_replenishment_orders(
        CONTROLLER, params={"part_id": scenario["part"]["id"],
                            "auto_generated": "true"}))
    assert meta["total_count"] == 1
    assert orders[0]["order_type"] == "EMERGENCY_AIR"
    assert orders[0]["qty"] == 2


def test_hazmat_part_resolving_to_air_freight_is_prohibited(api):
    """PRD 3.6: "If the mode resolved to `AIR_FREIGHT` for a part whose `hazmat` is
    true, the request is refused with `ERR_HAZMAT_AIR_PROHIBITED`. Note the ordering
    carefully: the dangerous-goods surcharge is still added into the air cost
    **before** the decision is taken, because that surcharge can be exactly what
    pushes the net benefit below the threshold and causes the branch to resolve to
    `BACKORDER` instead — in which case no rejection occurs at all."

    Design: Corner/validations/hazmat_part_air_freight_decision_is_prohibited
    """
    scenario = setup_scenario_with_work_order(
        work_type="BREAKDOWN", downtime_priority="MACHINE_DOWN",
        part_number="HAZ-1", unit_cost_cents=1333, lead_time_days=45,
        weight_kg=12.5, hazmat=True, dealer_code="D-HAZ", dealer_tier="GOLD",
        model_code="EM-X10", serial_prefix="SN-X10",
        price_rules=(("DESIRABLE", 0.35, 0.60, 0.20),))

    resp = api.create_part_line(
        scenario["work_order"]["id"],
        create_part_line_payload(scenario["part"]["id"], 2),
        scenario["dealer_headers"])
    validate_error(resp, ApiErrorId.ERR_HAZMAT_AIR_PROHIBITED.value)

    _, meta_lines = validate_paginated(api.list_part_lines(
        PLANNER, params={"work_order_id": scenario["work_order"]["id"]}))
    assert meta_lines["total_count"] == 0
    _, meta_orders = validate_paginated(api.list_replenishment_orders(
        CONTROLLER, params={"part_id": scenario["part"]["id"]}))
    assert meta_orders["total_count"] == 0
    assert validate_success(api.get_work_order(
        scenario["work_order"]["id"], PLANNER))["status"] == "OPEN"
