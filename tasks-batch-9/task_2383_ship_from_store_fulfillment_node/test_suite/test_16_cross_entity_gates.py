"""Cross-entity state gates.

Each test here drives one call whose permission to proceed is owned by a
*different* row than the one being written: a tender reads the carrier pickup's
status, a routing run reads the owning order's `fulfillment_status`, and an
order-level cancel reads the shipped units its child assignments produced.
Every test builds its own world from an empty database.
"""

import pytest

from test_helpers import (
    CARE,
    PLANNER,
    accept,
    add_order_line,
    close_pickup,
    commit_routing,
    create_routing_run_payload,
    find_assignment,
    find_notifications,
    find_routing_runs,
    intake_order,
    make_store_associate_headers,
    order_version,
    pack,
    pick_full,
    pickup_version,
    read_assignment,
    read_inventory,
    read_order,
    read_order_line,
    read_pickup,
    read_store,
    schedule_pickup,
    set_clock,
    setup_network,
    setup_order_with_lines,
    setup_packed_assignment,
    ship,
    ship_payload,
    stock_packaging,
    validate_error,
    validate_success,
)


# ======================================================================
# Shared preambles
# ======================================================================


def _packed_parcel_at_a_scheduled_pickup() -> dict:
    """One node, one SKU, one two-unit order committed to it, then accepted at
    09:05, fully picked at 09:10 and packed into a MEDIUM_BOX at 09:20 while the
    node's only pickup window (09:00Z-12:00Z) is still SCHEDULED."""
    return setup_packed_assignment(
        node_preset="S1",
        sku_preset="SKU-A",
        on_hand_units=12,
        safety_stock_units=2,
        quantity=2,
        destination_zone=4,
        service_level="GROUND",
        order_code="O-5801",
        customer_ref="C-28",
        clock="2026-08-03T09:00:00Z",
        accept_at="2026-08-03T09:05:00Z",
        pick_at="2026-08-03T09:10:00Z",
        pack_at="2026-08-03T09:20:00Z",
        package_type="MEDIUM_BOX",
        packaging_on_hand=5,
        pickup_start="2026-08-03T09:00:00Z",
        pickup_end="2026-08-03T12:00:00Z",
        parcel_capacity=5,
    )


def _network_with_two_single_sku_nodes() -> dict:
    """S1 (registered first) stocks only SKU-A, S3 stocks only SKU-B, and S1
    additionally holds a MEDIUM_BOX supply and a 09:00Z-12:00Z pickup window."""
    net = setup_network(
        node_presets=("S1", "S3"),
        sku_presets=("SKU-A", "SKU-B"),
        clock="2026-08-03T09:00:00Z",
        stock=[("S1", "SKU-A", 12, 2), ("S3", "SKU-B", 10, 0)],
    )
    net["supply_s1"] = stock_packaging(net["stores"]["S1"]["id"], "MEDIUM_BOX", 5, 1)
    net["pickup_s1"] = schedule_pickup(
        net["stores"]["S1"]["id"],
        window_start_utc="2026-08-03T09:00:00Z",
        window_end_utc="2026-08-03T12:00:00Z",
        parcel_capacity=5,
    )
    return net


def _commit_two_way_split_order(net: dict) -> dict:
    """A zone-2 GROUND order of SKU-A x1 then SKU-B x1: because each node stocks
    only one of the two SKUs the waterfall has to split it across both."""
    built = setup_order_with_lines(
        [(net["skus"]["SKU-A"]["id"], 1, 4500), (net["skus"]["SKU-B"]["id"], 1, 1900)],
        order_code="O-6001",
        customer_ref="C-31",
        destination_zone=2,
        service_level="GROUND",
    )
    order = built["order"]
    commit_routing(order["id"])
    return {
        "order": order,
        "line_sku_a": built["lines"][0],
        "line_sku_b": built["lines"][1],
        "assignment_s1": find_assignment(
            order_id=order["id"], store_id=net["stores"]["S1"]["id"]
        ),
        "assignment_s3": find_assignment(
            order_id=order["id"], store_id=net["stores"]["S3"]["id"]
        ),
    }


def _commit_single_line_order_at_s3(net: dict) -> dict:
    """A second zone-2 GROUND order of SKU-B x1, which only S3 can cover."""
    built = setup_order_with_lines(
        [(net["skus"]["SKU-B"]["id"], 1, 1900)],
        order_code="O-6002",
        customer_ref="C-32",
        destination_zone=2,
        service_level="GROUND",
    )
    order = built["order"]
    commit_routing(order["id"])
    return {
        "order": order,
        "line": built["lines"][0],
        "assignment": find_assignment(order_id=order["id"]),
    }


def _ship_the_s1_parcel(net: dict, split: dict) -> None:
    """Take the S1 half of the split order all the way to SHIPPED at 09:30."""
    store_id = net["stores"]["S1"]["id"]
    assignment_id = split["assignment_s1"]["id"]
    set_clock("2026-08-03T09:05:00Z")
    accept(assignment_id, store_id)
    pick_full(assignment_id, store_id)
    set_clock("2026-08-03T09:20:00Z")
    pack(assignment_id, store_id, "MEDIUM_BOX")
    set_clock("2026-08-03T09:30:00Z")
    ship(assignment_id, store_id, net["pickup_s1"]["id"])


# ======================================================================
# FulfillmentAssignment x CarrierPickup
# ======================================================================


def test_ship_refused_when_the_target_pickup_window_is_closed(api):
    """PRD §3.6: "A coordinator closes a `SCHEDULED` window, moving it `SCHEDULED → CLOSED`, after which no further parcel may be tendered to it — a later tender fails with `ERR_PICKUP_STATE_INVALID` — and the pickup's `version` increments."
    PRD §3.6: "The preconditions are checked in this order: the acting node must match the assignment's node; the assignment must be at `PACKED`; the pickup's `status` must be `SCHEDULED`; the node's `node_status` must be `ELIGIBLE` or `PROBATION`; the clock's minute-of-day must still be within the node's cutoff; the clock must sit inside the half-open window, at or after `window_start_utc` and strictly before `window_end_utc`, or the tender is refused with `ERR_PICKUP_WINDOW_CLOSED`; `reserved_parcels` must be strictly below `parcel_capacity`, or the tender is refused with `ERR_PICKUP_CAPACITY_EXCEEDED`; and last of all the named pickup must belong to the same node as the assignment, or the request is refused with `ERR_PICKUP_STORE_MISMATCH`."
    PRD §3.6: "Shipping moves an assignment `PACKED → SHIPPED` and is the act of handing the parcel to a specific window."
    PRD §3.5: "It is created only by a routing run and carries, as system-set references, the `order_id` it serves, the `store_id` that will fulfill it, the `routing_run_id` that created it, and a `carrier_pickup_id` that stays null until the parcel is tendered."
    PRD §2.9: "A pickup's `reserved_parcels` equals the count of assignments whose `carrier_pickup_id` names that pickup and whose `status` is `SHIPPED`, and `reserved_parcels` never exceeds `parcel_capacity`."

    Design: Difficulty/cross_entity_state_dependency/ship_is_gated_by_the_carrier_pickup_state_not_the_assignment_state
    """
    ctx = _packed_parcel_at_a_scheduled_pickup()
    store_id = ctx["store"]["id"]
    pickup_id = ctx["pickup"]["id"]

    set_clock("2026-08-03T09:25:00Z")
    close_pickup(pickup_id)

    set_clock("2026-08-03T09:30:00Z")
    response = api.ship_assignment(
        ctx["assignment"]["id"],
        ship_payload(pickup_id, pickup_version(pickup_id)),
        make_store_associate_headers(store_id),
    )
    validate_error(response, "ERR_PICKUP_STATE_INVALID")

    assignment = read_assignment(ctx["assignment"]["id"])
    assert assignment["status"] == "PACKED", (
        "a tender refused by the pickup's state must leave the assignment at PACKED, "
        f"got {assignment['status']}"
    )
    assert assignment["carrier_pickup_id"] is None, (
        "the refused tender must not store a carrier_pickup_id"
    )

    pickup = read_pickup(pickup_id)
    assert pickup["status"] == "CLOSED", (
        f"the pickup remains CLOSED, got {pickup['status']}"
    )
    assert pickup["reserved_parcels"] == 0, (
        "no assignment reached SHIPPED, so the CLOSED window holds zero parcels, got "
        f"{pickup['reserved_parcels']}"
    )


def test_ship_succeeds_for_the_same_packed_parcel_on_a_scheduled_pickup(api):
    """PRD §3.6: "The preconditions are checked in this order: the acting node must match the assignment's node; the assignment must be at `PACKED`; the pickup's `status` must be `SCHEDULED`; the node's `node_status` must be `ELIGIBLE` or `PROBATION`; the clock's minute-of-day must still be within the node's cutoff; the clock must sit inside the half-open window, at or after `window_start_utc` and strictly before `window_end_utc`, or the tender is refused with `ERR_PICKUP_WINDOW_CLOSED`; `reserved_parcels` must be strictly below `parcel_capacity`, or the tender is refused with `ERR_PICKUP_CAPACITY_EXCEEDED`; and last of all the named pickup must belong to the same node as the assignment, or the request is refused with `ERR_PICKUP_STORE_MISMATCH`."
    PRD §3.6: "The assignment's `status` becomes `SHIPPED`, `shipped_at` is set to the clock instant, `carrier_pickup_id` is stored, and `cycle_time_minutes` is computed as the elapsed time from `created_at` to `shipped_at` in whole minutes with remaining seconds discarded."
    PRD §3.6: "The pickup's `reserved_parcels` increases by 1 and its `version` increments."
    PRD §3.6: "For each line's SKU, the node's inventory row has `on_hand_units` reduced by the line's `units_picked` and `reserved_units` reduced by its `units_assigned`, and `available_to_promise_units` is recomputed."
    PRD §3.6: "The node's `reserved_labor_minutes` is reduced by the assignment's `labor_minutes_reserved` and its `eligibility_score` is recomputed."
    PRD §3.6: "From `PENDING`, a ship that leaves `shipped_units` above 0 with that same sum exactly equal to `total_units` moves the order straight to `SHIPPED`, writing `final_cost_cents` on the final variant, setting `cost_variance_cents` to `final_cost_cents` minus `provisional_cost_cents`, and recomputing `cost_index_bps` against the final figure."
    PRD §2.9: "A pickup's `reserved_parcels` equals the count of assignments whose `carrier_pickup_id` names that pickup and whose `status` is `SHIPPED`, and `reserved_parcels` never exceeds `parcel_capacity`."

    Design: Difficulty/cross_entity_state_dependency/ship_is_gated_by_the_carrier_pickup_state_not_the_assignment_state
    """
    ctx = _packed_parcel_at_a_scheduled_pickup()
    store_id = ctx["store"]["id"]
    closed_pickup_id = ctx["pickup"]["id"]

    set_clock("2026-08-03T09:25:00Z")
    close_pickup(closed_pickup_id)

    # A second window at the same node, starting after the first one ended.
    fresh_pickup = schedule_pickup(
        store_id,
        window_start_utc="2026-08-03T12:30:00Z",
        window_end_utc="2026-08-03T15:00:00Z",
        parcel_capacity=5,
    )

    set_clock("2026-08-03T12:35:00Z")
    response = api.ship_assignment(
        ctx["assignment"]["id"],
        ship_payload(fresh_pickup["id"], pickup_version(fresh_pickup["id"])),
        make_store_associate_headers(store_id),
    )
    shipped = validate_success(response, 200)

    assert shipped["status"] == "SHIPPED", (
        "the identical PACKED parcel ships once the target window is SCHEDULED, got "
        f"{shipped['status']}"
    )
    assert shipped["carrier_pickup_id"] == fresh_pickup["id"], (
        "the tender stores the pickup it was handed to"
    )
    assert shipped["cycle_time_minutes"] == 215, (
        "cycle_time_minutes is the whole minutes from created_at (09:00) to shipped_at "
        f"(12:35), got {shipped['cycle_time_minutes']}"
    )

    assert read_pickup(closed_pickup_id)["status"] == "CLOSED", (
        "the window that refused the tender is untouched by the successful one"
    )
    assert read_pickup(closed_pickup_id)["reserved_parcels"] == 0, (
        "the CLOSED window never took a parcel"
    )

    accepting_pickup = read_pickup(fresh_pickup["id"])
    assert accepting_pickup["status"] == "SCHEDULED", (
        f"the accepting window stays SCHEDULED, got {accepting_pickup['status']}"
    )
    assert accepting_pickup["reserved_parcels"] == 1, (
        "the successful tender consumes exactly one parcel slot, got "
        f"{accepting_pickup['reserved_parcels']}"
    )

    inventory = read_inventory(ctx["inventory"]["id"])
    assert inventory["on_hand_units"] == 10, (
        f"on_hand drops by the 2 picked units, got {inventory['on_hand_units']}"
    )
    assert inventory["reserved_units"] == 0, (
        f"the reservation is released at ship, got {inventory['reserved_units']}"
    )
    assert inventory["available_to_promise_units"] == 8, (
        "available_to_promise is 10 on hand less 0 reserved less the 2-unit safety "
        f"buffer, got {inventory['available_to_promise_units']}"
    )

    store = read_store(store_id)
    assert store["reserved_labor_minutes"] == pytest.approx(0.00, abs=0.01), (
        "the node's whole labour standard is released at ship, got "
        f"{store['reserved_labor_minutes']}"
    )

    order = read_order(ctx["order"]["id"])
    assert order["fulfillment_status"] == "SHIPPED", (
        "both ordered units shipped, so the order resolves to SHIPPED, got "
        f"{order['fulfillment_status']}"
    )


# ======================================================================
# CustomerOrder x RoutingRun
# ======================================================================


def test_routing_run_refused_when_the_order_fulfillment_status_is_cancelled(api):
    """PRD §3.4: "Routing is refused when the order's `fulfillment_status` is anything other than `PENDING`, with `ERR_ORDER_NOT_ROUTABLE`, and when no demand line has at least one open unit, with `ERR_NO_ROUTABLE_LINES`."
    PRD §2.11: "State validity sixth: whether the assignment, order, pickup, node or window is in a status that permits the operation."
    PRD §3.2: "A full cancel moves `fulfillment_status` from `PENDING` to `CANCELLED`, cancels every non-terminal assignment of the order with cancellation reason `CUSTOMER_REQUEST` and no reroute, turns all released units into each line's `cancelled_units` so that every line ends with `open_units` 0 and `line_status` `CANCELLED`, releases each affected node's inventory reservations along with its `units_committed_epoch` and `reserved_labor_minutes`, recomputes each affected node's `eligibility_score`, emits exactly one customer notification of type `CANCELLATION_FULL`, leaves `final_cost_cents` null, recomputes `provisional_cost_cents` and `cost_index_bps`, and increments the order's `version`."
    PRD §3.2: "With those in hand, the status is the first match in this fixed order: `UNROUTED` when no routing run exists for the order; otherwise `ROUTING` when open units is greater than 0 and the pending-reroute predicate holds; otherwise `UNROUTABLE` when covered units is 0; otherwise `ROUTED` when covered units plus cancelled units equals `total_units`; otherwise `PARTIALLY_ROUTED`."
    PRD §2.9: "At the order level, `total_units` equals the sum of every demand line's `quantity`, and `unassigned_units` equals the sum of every demand line's `open_units`."

    Design: Difficulty/cross_entity_state_dependency/routing_run_is_gated_by_the_orders_fulfillment_status
    """
    net = setup_network(
        node_presets=("S1",),
        sku_presets=("SKU-A",),
        clock="2026-08-03T09:00:00Z",
        stock=[("S1", "SKU-A", 12, 2)],
    )
    sku_id = net["skus"]["SKU-A"]["id"]

    order = intake_order(
        order_code="O-5901",
        customer_ref="C-29",
        destination_zone=4,
        service_level="GROUND",
        promised_ship_by_utc="2026-08-03T16:00:00Z",
    )
    line = add_order_line(order["id"], sku_id, 2, 4500)

    set_clock("2026-08-03T09:05:00Z")
    validate_success(
        api.cancel_order(order["id"], {"cancel_reason_code": "CUSTOMER_REQUEST"}, CARE),
        200,
    )

    cancelled = read_order(order["id"])
    assert cancelled["fulfillment_status"] == "CANCELLED", (
        f"the full cancel lands the order on CANCELLED, got {cancelled['fulfillment_status']}"
    )

    response = api.create_routing_run(
        order["id"],
        create_routing_run_payload(cancelled["version"], "COMMIT"),
        PLANNER,
    )
    validate_error(response, "ERR_ORDER_NOT_ROUTABLE")

    assert find_routing_runs(order_id=order["id"]) == [], (
        "the refused waterfall must persist no RoutingRun row for the cancelled order"
    )

    after = read_order(order["id"])
    assert after["fulfillment_status"] == "CANCELLED", (
        "the refusal leaves the order's execution dimension untouched"
    )
    assert after["routing_status"] == "UNROUTED", (
        "no routing run exists for the order, so routing_status stays UNROUTED, got "
        f"{after['routing_status']}"
    )
    assert after["unassigned_units"] == 0, (
        "every unit was cancelled, so no open unit remains, got "
        f"{after['unassigned_units']}"
    )

    cancelled_line = read_order_line(line["id"])
    assert cancelled_line["cancelled_units"] == 2, (
        f"both units became cancelled_units, got {cancelled_line['cancelled_units']}"
    )
    assert cancelled_line["open_units"] == 0, (
        f"the cancelled line ends with open_units 0, got {cancelled_line['open_units']}"
    )


def test_routing_run_commits_for_a_pending_order_in_the_same_network(api):
    """PRD §3.4: "Routing is refused when the order's `fulfillment_status` is anything other than `PENDING`, with `ERR_ORDER_NOT_ROUTABLE`, and when no demand line has at least one open unit, with `ERR_NO_ROUTABLE_LINES`."
    PRD §3.4: "A run initiated this way records `initiated_by` as `PLANNER`; runs the system starts for itself record `SYSTEM_REROUTE` when they follow a reject, a short pick, a cancel-with-reroute or a pick-deadline expiry, and `SYSTEM_DEACTIVATION` when they follow a node deactivation cascade."
    PRD §3.4: "When the loop ends, `unfulfillable_units` records whatever remaining demand is left, and `selected_store_count` and `planned_split_count` both equal the number of nodes selected."
    PRD §3.4: "Otherwise a `COMMIT` run's `status` is `COMMITTED`."
    PRD §3.4: "A planner's `COMMIT` run on an order at `UNROUTED` lands it on `ROUTED` when every open unit is covered, on `PARTIALLY_ROUTED` when some but not all are covered — with the shortfall recorded in `unfulfillable_units` and left in `open_units` unless the three-split ceiling converted it to `dc_fallback_units`, which is the only case in which that run emits a `DC_FALLBACK` notification — and on `UNROUTABLE` when the pool is empty at the first iteration."
    PRD §3.1: "A row's `reserved_units` is always the sum, over the assignment lines whose owning assignment belongs to this node and whose served demand line references this SKU, of that line's `units_assigned` minus its `units_cancelled`, counting only assignments whose `status` is one of `ASSIGNED`, `ACCEPTED`, `PICKED`, `SHORT_PICKED` or `PACKED`."

    Design: Difficulty/cross_entity_state_dependency/routing_run_is_gated_by_the_orders_fulfillment_status
    """
    net = setup_network(
        node_presets=("S1",),
        sku_presets=("SKU-A",),
        clock="2026-08-03T09:00:00Z",
        stock=[("S1", "SKU-A", 12, 2)],
    )
    store_id = net["stores"]["S1"]["id"]
    sku_id = net["skus"]["SKU-A"]["id"]

    # The sibling order that will be cancelled: same node, same SKU, same shape.
    cancelled_order = intake_order(
        order_code="O-5901",
        customer_ref="C-29",
        destination_zone=4,
        service_level="GROUND",
        promised_ship_by_utc="2026-08-03T16:00:00Z",
    )
    add_order_line(cancelled_order["id"], sku_id, 2, 4500)

    routable_order = intake_order(
        order_code="O-5902",
        customer_ref="C-30",
        destination_zone=4,
        service_level="GROUND",
        promised_ship_by_utc="2026-08-03T16:00:00Z",
    )
    add_order_line(routable_order["id"], sku_id, 2, 4500)

    set_clock("2026-08-03T09:05:00Z")
    validate_success(
        api.cancel_order(
            cancelled_order["id"], {"cancel_reason_code": "CUSTOMER_REQUEST"}, CARE
        ),
        200,
    )

    response = api.create_routing_run(
        routable_order["id"],
        create_routing_run_payload(order_version(routable_order["id"]), "COMMIT"),
        PLANNER,
    )
    run = validate_success(response, 201)

    assert run["status"] == "COMMITTED", (
        "the same network that refused the cancelled order commits the PENDING one, got "
        f"status {run['status']}"
    )
    assert run["initiated_by"] == "PLANNER", (
        f"a planner-started run records initiated_by PLANNER, got {run['initiated_by']}"
    )
    assert run["selected_store_count"] == 1, (
        f"the single stocked node is selected once, got {run['selected_store_count']}"
    )

    assignment = find_assignment(order_id=routable_order["id"])
    assert assignment["store_id"] == store_id, (
        "the assignment is created at the only node that can promise the units"
    )

    routed = read_order(routable_order["id"])
    assert routed["routing_status"] == "ROUTED", (
        f"every open unit is covered, so the order lands on ROUTED, got {routed['routing_status']}"
    )

    inventory = read_inventory(net["inventories"][("S1", "SKU-A")]["id"])
    assert inventory["reserved_units"] == 2, (
        "the committed assignment reserves both units at the node, got "
        f"{inventory['reserved_units']}"
    )


# ======================================================================
# CustomerOrder x FulfillmentAssignment
# ======================================================================


def test_order_cancel_refused_when_a_child_assignment_has_shipped_units(api):
    """PRD §3.2: "A care agent may cancel the whole order outright, supplying a `cancel_reason_code`, but only while `fulfillment_status` is `PENDING` and `shipped_units` is 0; otherwise the request is rejected with `ERR_ORDER_ALREADY_SHIPPED_UNITS`."
    PRD §3.2: "The transition from `PARTIALLY_SHIPPED` to `CANCELLED` does not exist: once `shipped_units` is above 0 the order can only resolve to `SHIPPED`, and a cancel attempt is refused with `ERR_ORDER_ALREADY_SHIPPED_UNITS`."
    PRD §3.6: "From `PENDING`, a ship that leaves the order with `shipped_units` above 0 while `shipped_units` plus the sum of the lines' `cancelled_units` plus `dc_fallback_units` is still strictly below `total_units` moves it to `PARTIALLY_SHIPPED`, recomputing `shipped_units` and refreshing the provisional cost fields."
    PRD §3.6: "Each served demand line has its `shipped_units` raised by the line's `units_picked` and its `assigned_units` reduced by its `units_assigned`."
    PRD §3.6: "For each line's SKU, the node's inventory row has `on_hand_units` reduced by the line's `units_picked` and `reserved_units` reduced by its `units_assigned`, and `available_to_promise_units` is recomputed."
    PRD §3.1: "A row's `reserved_units` is always the sum, over the assignment lines whose owning assignment belongs to this node and whose served demand line references this SKU, of that line's `units_assigned` minus its `units_cancelled`, counting only assignments whose `status` is one of `ASSIGNED`, `ACCEPTED`, `PICKED`, `SHORT_PICKED` or `PACKED`."

    Design: Difficulty/cross_entity_state_dependency/order_cancel_is_gated_by_a_child_assignments_shipped_units
    """
    net = _network_with_two_single_sku_nodes()
    split = _commit_two_way_split_order(net)
    _ship_the_s1_parcel(net, split)

    partially_shipped = read_order(split["order"]["id"])
    assert partially_shipped["fulfillment_status"] == "PARTIALLY_SHIPPED", (
        "one of the two parcels shipped, so the order is PARTIALLY_SHIPPED, got "
        f"{partially_shipped['fulfillment_status']}"
    )
    assert partially_shipped["shipped_units"] == 1, (
        f"exactly one unit shipped, got {partially_shipped['shipped_units']}"
    )

    response = api.cancel_order(
        split["order"]["id"], {"cancel_reason_code": "CUSTOMER_REQUEST"}, CARE
    )
    validate_error(response, "ERR_ORDER_ALREADY_SHIPPED_UNITS")

    after = read_order(split["order"]["id"])
    assert after["fulfillment_status"] == "PARTIALLY_SHIPPED", (
        "the refused cancel leaves the order at PARTIALLY_SHIPPED, got "
        f"{after['fulfillment_status']}"
    )
    assert after["shipped_units"] == 1, (
        f"the refused cancel moves no unit, got {after['shipped_units']}"
    )

    still_assigned = read_assignment(split["assignment_s3"]["id"])
    assert still_assigned["status"] == "ASSIGNED", (
        "the sibling assignment at the second node is not cancelled by the refused "
        f"order-level cancel, got {still_assigned['status']}"
    )

    shipped_line = read_order_line(split["line_sku_a"]["id"])
    assert shipped_line["shipped_units"] == 1, (
        f"the shipped parcel's demand line carries the shipped unit, got {shipped_line['shipped_units']}"
    )

    held_line = read_order_line(split["line_sku_b"]["id"])
    assert held_line["assigned_units"] == 1, (
        "the untouched demand line still has its unit held by the live assignment, got "
        f"{held_line['assigned_units']}"
    )

    inventory_s1 = read_inventory(net["inventories"][("S1", "SKU-A")]["id"])
    assert inventory_s1["on_hand_units"] == 11, (
        f"the shipped unit left the building, got {inventory_s1['on_hand_units']}"
    )

    inventory_s3 = read_inventory(net["inventories"][("S3", "SKU-B")]["id"])
    assert inventory_s3["reserved_units"] == 1, (
        "the second node still reserves its unit for the ASSIGNED parcel, got "
        f"{inventory_s3['reserved_units']}"
    )


def test_order_cancel_succeeds_when_every_child_assignment_is_still_assigned(api):
    """PRD §3.2: "A care agent may cancel the whole order outright, supplying a `cancel_reason_code`, but only while `fulfillment_status` is `PENDING` and `shipped_units` is 0; otherwise the request is rejected with `ERR_ORDER_ALREADY_SHIPPED_UNITS`."
    PRD §3.2: "A full cancel moves `fulfillment_status` from `PENDING` to `CANCELLED`, cancels every non-terminal assignment of the order with cancellation reason `CUSTOMER_REQUEST` and no reroute, turns all released units into each line's `cancelled_units` so that every line ends with `open_units` 0 and `line_status` `CANCELLED`, releases each affected node's inventory reservations along with its `units_committed_epoch` and `reserved_labor_minutes`, recomputes each affected node's `eligibility_score`, emits exactly one customer notification of type `CANCELLATION_FULL`, leaves `final_cost_cents` null, recomputes `provisional_cost_cents` and `cost_index_bps`, and increments the order's `version`."
    PRD §3.7: "It carries a `channel` of `EMAIL` or `SMS`, defaulting to `EMAIL`, a `units_affected` count of the units the event moved or removed, a `sent_at_utc` clock instant, and a `body_summary` — a templated one-line summary containing the order's `order_code`, the `notification_type` and the `units_affected` count."
    PRD §3.1: "A row's `reserved_units` is always the sum, over the assignment lines whose owning assignment belongs to this node and whose served demand line references this SKU, of that line's `units_assigned` minus its `units_cancelled`, counting only assignments whose `status` is one of `ASSIGNED`, `ACCEPTED`, `PICKED`, `SHORT_PICKED` or `PACKED`."

    Design: Difficulty/cross_entity_state_dependency/order_cancel_is_gated_by_a_child_assignments_shipped_units
    """
    net = _network_with_two_single_sku_nodes()
    split = _commit_two_way_split_order(net)
    sibling = _commit_single_line_order_at_s3(net)
    _ship_the_s1_parcel(net, split)

    response = api.cancel_order(
        sibling["order"]["id"], {"cancel_reason_code": "CUSTOMER_REQUEST"}, CARE
    )
    validate_success(response, 200)

    cancelled_order = read_order(sibling["order"]["id"])
    assert cancelled_order["fulfillment_status"] == "CANCELLED", (
        "an order whose only child is still ASSIGNED cancels cleanly, got "
        f"{cancelled_order['fulfillment_status']}"
    )
    assert cancelled_order["shipped_units"] == 0, (
        f"nothing had shipped on this order, got {cancelled_order['shipped_units']}"
    )

    cancelled_assignment = read_assignment(sibling["assignment"]["id"])
    assert cancelled_assignment["status"] == "CANCELLED", (
        "the full cancel cancels every non-terminal assignment, got "
        f"{cancelled_assignment['status']}"
    )
    assert cancelled_assignment["cancel_reason_code"] == "CUSTOMER_REQUEST", (
        "a full cancel stores cancellation reason CUSTOMER_REQUEST, got "
        f"{cancelled_assignment['cancel_reason_code']}"
    )

    cancelled_line = read_order_line(sibling["line"]["id"])
    assert cancelled_line["cancelled_units"] == 1, (
        f"the released unit becomes cancelled_units, got {cancelled_line['cancelled_units']}"
    )
    assert cancelled_line["open_units"] == 0, (
        f"every line ends with open_units 0, got {cancelled_line['open_units']}"
    )
    assert cancelled_line["line_status"] == "CANCELLED", (
        f"every line ends at line_status CANCELLED, got {cancelled_line['line_status']}"
    )

    notifications = find_notifications(order_id=sibling["order"]["id"])
    assert len(notifications) == 1, (
        f"the full cancel emits exactly one notification, got {len(notifications)}"
    )
    assert notifications[0]["notification_type"] == "CANCELLATION_FULL", (
        "a customer cancel of the whole order notifies CANCELLATION_FULL, got "
        f"{notifications[0]['notification_type']}"
    )
    assert notifications[0]["units_affected"] == 1, (
        f"one unit was removed, got {notifications[0]['units_affected']}"
    )

    # The partially shipped order's own allocation is untouched by its sibling's cancel.
    assert read_assignment(split["assignment_s3"]["id"])["status"] == "ASSIGNED", (
        "the other order's assignment at the same node is unaffected"
    )
    inventory_s3 = read_inventory(net["inventories"][("S3", "SKU-B")]["id"])
    assert inventory_s3["reserved_units"] == 1, (
        "the cancelled assignment released its reservation while the surviving one "
        f"keeps its unit reserved, got {inventory_s3['reserved_units']}"
    )
