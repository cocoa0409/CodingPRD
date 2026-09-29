"""Work orders, part lines, consumption billing, cancellation and closing."""

from test_helpers import (
    ApiErrorId, add_part_line, api_client, assert_dealer, assert_part,
    assert_replenishment_order, classify_part, close_work_order, consume_line,
    create_forecast, create_part, create_part_line_payload, create_work_order,
    list_ledger, read_dealer, read_part, setup_catalogue,
    setup_scenario_with_work_order, TEST_USERS, validate_error,
    validate_paginated, validate_success,
)

PLANNER = TEST_USERS["planner_headers"]
CONTROLLER = TEST_USERS["controller_headers"]


def _reorder_cascade_scenario():
    """A VITAL part classified to reorder_point_units 5 with a RESERVED line for 82
    of the 86 available units, poised so that consuming it crosses the reorder
    point."""
    scenario = setup_catalogue(
        part_number="REORD-1", unit_cost_cents=1333, lead_time_days=60,
        weight_kg=12.5, max_stock_units=30, dealer_code="D-REORD",
        model_code="EM-800", serial_prefix="SN-800", installed_units=4,
        qty_per_unit=5, stock_units=100,
        price_rules=(("DESIRABLE", 0.35, 0.60, 0.20),
                     ("VITAL", 0.55, 0.60, 0.30)))
    dealer_id = scenario["dealer"]["id"]
    for unit_index, work_type, priority, qty in (
            (0, "BREAKDOWN", "MACHINE_DOWN", 5),
            (1, "BREAKDOWN", "MACHINE_DOWN", 5),
            (2, "SCHEDULED_MAINTENANCE", "DEGRADED", 4)):
        wo = create_work_order(scenario["units"][unit_index]["id"], dealer_id,
                               work_type, priority)
        line = add_part_line(wo["id"], dealer_id, scenario["part"]["id"], qty)
        consume_line(line["id"], dealer_id, qty)
        close_work_order(wo["id"], dealer_id)

    create_forecast(scenario["part"]["id"], 12, "BLENDED", 365)
    classified = classify_part(scenario["part"]["id"])
    assert classified["reorder_point_units"] == 5, "setup precondition"
    assert classified["stocking_policy"] == "STOCK_TO_MAX", "setup precondition"

    wo4 = create_work_order(scenario["units"][3]["id"], dealer_id,
                            "SCHEDULED_MAINTENANCE", "DEGRADED")
    line4 = add_part_line(wo4["id"], dealer_id, scenario["part"]["id"], 82)
    scenario["work_order"] = wo4
    scenario["line"] = line4
    return scenario


def test_consume_drops_available_units_to_the_reorder_point(api):
    """PRD 3.6: "The consequences chain. `qty_consumed` is stored and `consumed_at` is
    stamped from the logical clock; the part's `allocated_units` falls by the full
    `qty_requested` (the whole reservation is released, not merely the fitted portion)
    while `on_hand_units` falls by `qty_consumed`; and one ledger entry is appended
    with `entry_type` `ISSUE` and a `delta_units` equal to the negative of
    `qty_consumed`."
    PRD 3.6: "The second hop follows from the first: `available_units` is recomputed,
    and if it has fallen to or below `reorder_point_units` the part's
    `replenishment_status` moves from `NORMAL` to `BELOW_REORDER_POINT`."
    PRD 3.6: "The dealer is then billed: `charged_amount_cents` is the part's
    `unit_cost_cents` multiplied by `qty_consumed` and then by one plus the line's
    `effective_uplift_pct`, rounded half up to a whole cent; that amount is added to
    the dealer's `outstanding_balance_cents`, and the dealer's `credit_hold` is
    recomputed."

    Design: Difficulty/transitive_cascade/consume_cascades_reorder_point_then_auto_stock_order
    """
    scenario = _reorder_cascade_scenario()
    assert scenario["line"]["effective_uplift_pct"] == 0.55
    assert scenario["line"]["quoted_line_total_cents"] == 169424

    consumed = validate_success(api.consume_part_line(
        scenario["line"]["id"], 82, scenario["dealer_headers"]))
    assert consumed["line_status"] == "CONSUMED"
    assert consumed["qty_consumed"] == 82
    assert consumed["charged_amount_cents"] == 169424

    part = read_part(scenario["part"]["id"])
    assert_part(part)
    assert part["on_hand_units"] == 4
    assert part["allocated_units"] == 0
    assert part["available_units"] == 4
    assert part["available_units"] <= part["reorder_point_units"]

    dealer = read_dealer(scenario["dealer"]["id"])
    assert_dealer(dealer)
    assert dealer["outstanding_balance_cents"] == 194618


def test_consume_auto_creates_a_stock_replenishment_order(api):
    """PRD 3.6: "The third hop follows from the second: when the part's
    `stocking_policy` is either `STOCK_TO_MAX` or `MIN_MAX` and the part is now
    `BELOW_REORDER_POINT`, a replenishment order is auto-created with `order_type`
    `STOCK`, `auto_generated` true, `approval_status` `PENDING` and `logistics_status`
    `NOT_STARTED`, and a `qty` equal to the part's `max_stock_units` less its
    `available_units` less its `in_transit_units`, floored at a minimum of 1 unit so
    that the order is never empty. Because that order now exists and is neither
    rejected nor received, the part's `replenishment_status` immediately reads
    `ON_ORDER` rather than `BELOW_REORDER_POINT`."

    Design: Difficulty/transitive_cascade/consume_cascades_reorder_point_then_auto_stock_order
    """
    scenario = _reorder_cascade_scenario()
    validate_success(api.consume_part_line(
        scenario["line"]["id"], 82, scenario["dealer_headers"]))

    orders, meta = validate_paginated(api.list_replenishment_orders(
        CONTROLLER, params={"part_id": scenario["part"]["id"],
                            "auto_generated": "true"}))
    assert meta["total_count"] == 1
    order = orders[0]
    assert_replenishment_order(order)
    assert order["order_type"] == "STOCK"
    assert order["qty"] == 26, "max_stock_units 30 less available 4 less in transit 0"
    assert order["approval_status"] == "PENDING"
    assert order["logistics_status"] == "NOT_STARTED"
    assert order["auto_generated"] is True

    assert read_part(scenario["part"]["id"])["replenishment_status"] == "ON_ORDER"


def test_work_order_close_blocked_by_a_reserved_line(api):
    """PRD 3.6: "**Closing** a work order requires it to be in `OPEN` and requires
    that no line on it sits in `REQUESTED`, `RESERVED` or `BACKORDERED`; an unfinished
    line blocks the close with `ERR_OPEN_LINES_BLOCK_CLOSE`, and closing a work order
    that is not `OPEN` gives `ERR_WORK_ORDER_STATE_INVALID`."
    PRD 3.6: "Cancelling from `RESERVED` releases the reservation — `allocated_units`
    falls by `qty_requested`, `available_units` is recomputed, and the part's `version`
    advances."
    PRD 3.6: "On close, `closed_at` is stamped from the logical clock and the work
    order's `version` advances."

    Design: Corner/state_machines/work_order_close_blocked_by_reserved_line
    """
    scenario = setup_scenario_with_work_order(
        part_number="CLS-1", unit_cost_cents=1333, lead_time_days=30,
        weight_kg=1.0, dealer_code="D-CLS", model_code="EM-K10",
        serial_prefix="SN-K10", stock_units=10,
        price_rules=(("DESIRABLE", 0.35, 0.60, 0.20),))
    dealer_headers = scenario["dealer_headers"]
    line = validate_success(api.create_part_line(
        scenario["work_order"]["id"],
        create_part_line_payload(scenario["part"]["id"], 2), dealer_headers), 201)
    assert line["line_status"] == "RESERVED"

    blocked = api.close_work_order(scenario["work_order"]["id"], dealer_headers)
    validate_error(blocked, ApiErrorId.ERR_OPEN_LINES_BLOCK_CLOSE.value)

    cancelled = validate_success(api.cancel_part_line(line["id"], dealer_headers))
    assert cancelled["line_status"] == "CANCELLED"
    part = read_part(scenario["part"]["id"])
    assert part["allocated_units"] == 0
    assert part["available_units"] == 10

    closed = validate_success(
        api.close_work_order(scenario["work_order"]["id"], dealer_headers))
    assert closed["status"] == "CLOSED"
    assert closed["closed_at"].startswith("2026-08-01T00:00:00"), (
        f"closed_at is stamped from the logical clock, got {closed['closed_at']}")


def test_work_order_returns_to_open_when_the_last_backordered_line_is_cancelled(api):
    """PRD 3.6: "An `AIR_FREIGHT` or `BACKORDER` decision instead puts the line into
    `line_status` `BACKORDERED` and moves the parent work order from `OPEN` to
    `PARTS_PENDING`."
    PRD 3.6: "Cancelling from `BACKORDERED` touches no stock counter but may unblock
    the parent work order: when the cancelled line was the last one on that work order
    in `BACKORDERED`, the work order moves from `PARTS_PENDING` back to `OPEN`. That
    return edge is general — a work order leaves `PARTS_PENDING` for `OPEN` whenever
    the count of its lines in `BACKORDERED` reaches zero, whether the last such line
    was cancelled or promoted into `RESERVED`."

    Design: Corner/state_machines/work_order_cycles_open_parts_pending_open_on_line_cancel
    """
    scenario = setup_scenario_with_work_order(
        part_number="CYCW-1", unit_cost_cents=1333, lead_time_days=0,
        weight_kg=1.0, dealer_code="D-CYCW", model_code="EM-L10",
        serial_prefix="SN-L10", price_rules=(("DESIRABLE", 0.35, 0.60, 0.20),))
    dealer_headers = scenario["dealer_headers"]

    line = validate_success(api.create_part_line(
        scenario["work_order"]["id"],
        create_part_line_payload(scenario["part"]["id"], 4), dealer_headers), 201)
    assert line["fulfillment_mode"] == "BACKORDER"
    assert line["line_status"] == "BACKORDERED"
    assert line["freight_cost_cents"] == 0
    assert line["decision_net_benefit_cents"] == -45000
    assert validate_success(api.get_work_order(
        scenario["work_order"]["id"], PLANNER))["status"] == "PARTS_PENDING"

    cancelled = validate_success(api.cancel_part_line(line["id"], dealer_headers))
    assert cancelled["line_status"] == "CANCELLED"
    assert validate_success(api.get_work_order(
        scenario["work_order"]["id"], PLANNER))["status"] == "OPEN"
    assert read_part(scenario["part"]["id"])["allocated_units"] == 0, \
        "a BACKORDERED line never reserved anything"


def test_consuming_a_line_twice_is_refused(api):
    """PRD 3.6: "A `DealerUser` supplies the `qty_consumed` actually fitted; it must
    be at least 1 and no more than `qty_requested`, the line must be in `RESERVED` —
    anything else is `ERR_LINE_STATE_INVALID` — the parent work order must still be
    `OPEN`, and the dealer must not be on credit hold."
    PRD 3.6: "The dealer is then billed: `charged_amount_cents` is the part's
    `unit_cost_cents` multiplied by `qty_consumed` and then by one plus the line's
    `effective_uplift_pct`, rounded half up to a whole cent; that amount is added to
    the dealer's `outstanding_balance_cents`, and the dealer's `credit_hold` is
    recomputed."

    Design: Corner/state_machines/part_line_consume_twice_returns_line_state_invalid
    """
    scenario = setup_scenario_with_work_order(
        part_number="CNS-1", unit_cost_cents=1333, lead_time_days=30,
        weight_kg=1.0, dealer_code="D-CNS", model_code="EM-N10",
        serial_prefix="SN-N10", stock_units=10,
        price_rules=(("DESIRABLE", 0.35, 0.60, 0.20),))
    dealer_headers = scenario["dealer_headers"]
    line = validate_success(api.create_part_line(
        scenario["work_order"]["id"],
        create_part_line_payload(scenario["part"]["id"], 2), dealer_headers), 201)
    first = validate_success(api.consume_part_line(line["id"], 2, dealer_headers))
    assert first["charged_amount_cents"] == 3599

    second = api.consume_part_line(line["id"], 2, dealer_headers)
    validate_error(second, ApiErrorId.ERR_LINE_STATE_INVALID.value)

    settled = validate_success(api.get_part_line(line["id"], PLANNER))
    assert settled["qty_consumed"] == 2
    assert settled["charged_amount_cents"] == 3599
    assert read_dealer(scenario["dealer"]["id"])["outstanding_balance_cents"] == 3599

    part = read_part(scenario["part"]["id"])
    assert part["on_hand_units"] == 8
    assert part["allocated_units"] == 0
    _, meta = list_ledger(scenario["part"]["id"])
    assert meta["total_count"] == 2, "one RECEIPT and one ISSUE, no second issue"


def test_supersede_cancels_open_lines_and_releases_the_reservation(api):
    """PRD 3.8: "On success the part's `superseded_by_part_id` is set to the nominated
    successor, its `lifecycle_state` becomes `SUPERSEDED`, and its `stocking_policy`
    becomes `NO_STOCK`. Its open lines are then wound up: every line in `REQUESTED` or
    `BACKORDERED` moves to `CANCELLED`, and every line in `RESERVED` also moves to
    `CANCELLED` and additionally releases the part's `allocated_units` by that line's
    `qty_requested`."

    Design: Corner/state_machines/supersede_cancels_open_lines_and_releases_reservation
    """
    scenario = setup_scenario_with_work_order(
        part_number="SUP-1", unit_cost_cents=1333, lead_time_days=30,
        weight_kg=1.0, dealer_code="D-SUP", model_code="EM-O10",
        serial_prefix="SN-O10", stock_units=10,
        price_rules=(("DESIRABLE", 0.35, 0.60, 0.20),))
    successor = create_part(part_number="SUP-2", description="Supersede target",
                            unit_cost_cents=1400, lead_time_days=30, weight_kg=1.0)
    line = validate_success(api.create_part_line(
        scenario["work_order"]["id"],
        create_part_line_payload(scenario["part"]["id"], 4),
        scenario["dealer_headers"]), 201)
    assert line["line_status"] == "RESERVED"

    superseded = validate_success(api.supersede_part(
        scenario["part"]["id"], successor["id"], PLANNER))
    assert superseded["lifecycle_state"] == "SUPERSEDED"
    assert superseded["superseded_by_part_id"] == successor["id"]
    assert superseded["stocking_policy"] == "NO_STOCK"

    assert validate_success(api.get_part_line(line["id"], PLANNER))["line_status"] \
        == "CANCELLED"
    part = read_part(scenario["part"]["id"])
    assert part["allocated_units"] == 0
    assert part["available_units"] == 10
    assert part["on_hand_units"] == 10
    assert validate_success(api.get_work_order(
        scenario["work_order"]["id"], PLANNER))["status"] == "OPEN"
    _, meta = list_ledger(scenario["part"]["id"])
    assert meta["total_count"] == 1, "cancelling a reservation writes no ledger row"


def test_part_line_on_a_closed_work_order_is_refused(api):
    """PRD 3.6: "The work order must be `OPEN`; adding a line to a work order in any
    other status is refused with `ERR_WORK_ORDER_STATE_INVALID`."
    PRD 2.10: "The target resource is in a state from which the requested transition
    is declared, including the cross-dimension guard on shipping a replenishment order
    and the cross-entity guards: submitting a campaign requires its part to be in
    `PHASE_OUT`; creating an allocation request requires the campaign to be in
    `APPROVED`; creating a return authorization requires the source line to be in
    `CONSUMED`; approving or receiving a replenishment order requires the part not to
    be `OBSOLETE`; and inspecting a return with a `RESTOCK` disposition requires the
    part not to be `OBSOLETE`."

    Design: Corner/errors/part_line_create_on_closed_work_order_returns_work_order_state_invalid
    """
    scenario = setup_scenario_with_work_order(
        part_number="WOS-1", unit_cost_cents=1333, lead_time_days=30,
        weight_kg=1.0, dealer_code="D-WOS", model_code="EM-AE1",
        serial_prefix="SN-AE1", stock_units=10,
        price_rules=(("DESIRABLE", 0.35, 0.60, 0.20),))
    dealer_headers = scenario["dealer_headers"]
    closed = validate_success(
        api.close_work_order(scenario["work_order"]["id"], dealer_headers))
    assert closed["status"] == "CLOSED"

    resp = api.create_part_line(
        scenario["work_order"]["id"],
        create_part_line_payload(scenario["part"]["id"], 1), dealer_headers)
    validate_error(resp, ApiErrorId.ERR_WORK_ORDER_STATE_INVALID.value)

    part = read_part(scenario["part"]["id"])
    assert part["allocated_units"] == 0
    assert part["available_units"] == 10
