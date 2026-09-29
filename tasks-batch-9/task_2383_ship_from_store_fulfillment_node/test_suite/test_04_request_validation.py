"""Request validation: the refusals a badly shaped, badly timed or badly
targeted request earns, and the sibling call that proves each rule is
state-driven rather than a blanket ban.

Every test builds its own world from an empty database and calls the raw client
for the refusing request so the error envelope can be inspected.
"""

import pytest

from test_helpers import (
    CARE,
    CARRIER,
    NON_EXISTENT_UUID,
    PLANNER,
    add_order_line,
    commit_routing,
    create_carrier_pickup_payload,
    create_order_line_payload,
    create_routing_run_payload,
    find_assignment,
    find_notifications,
    find_routing_candidates,
    intake_order,
    line_pick,
    make_store_associate_headers,
    pick_payload,
    provisional_routing,
    read_order,
    read_order_line,
    read_store,
    register_node,
    register_sku,
    set_clock,
    stock_inventory,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK_OPEN = "2026-08-03T09:00:00Z"
CLOCK_BEFORE_OPEN = "2026-08-03T08:59:00Z"
PROMISED_SHIP_BY = "2026-08-03T15:00:00Z"


# ======================================================================
# shared preambles
# ======================================================================


def _stocked_node_and_sku(sku_preset="SKU-A", on_hand_units=20, safety_stock_units=2):
    """Clock at 09:00, one node, one SKU stocked at that node."""
    set_clock(CLOCK_OPEN)
    store = register_node("S1")
    sku = register_sku(sku_preset)
    inventory = stock_inventory(
        store["id"], sku["id"], on_hand_units, safety_stock_units
    )
    return {"store": store, "sku": sku, "inventory": inventory}


def _order_with_one_line(sku, order_code, customer_ref, quantity=2):
    """A GROUND order to zone 4 carrying exactly one demand line."""
    order = intake_order(
        order_code=order_code,
        customer_ref=customer_ref,
        destination_zone=4,
        service_level="GROUND",
        promised_ship_by_utc=PROMISED_SHIP_BY,
    )
    line = add_order_line(order["id"], sku["id"], quantity, sku["unit_price_cents"])
    return {"order": read_order(order["id"]), "line": line}


def _hazmat_demand_at_uncertified_node():
    """S1-DOWNTOWN (hazmat_certified false) holds the hazardous SKU-H, and one
    order demands two of those units."""
    net = _stocked_node_and_sku(sku_preset="SKU-H")
    built = _order_with_one_line(net["sku"], "O-B401", "C-341", quantity=2)
    return {**net, **built}


def _commit_hazmat_demand_after_adding_certified_node():
    """Run the empty-pool COMMIT first, then register the hazmat-certified
    S2-HARBOR, stock it with the same SKU and COMMIT again."""
    ctx = _hazmat_demand_at_uncertified_node()
    first_run = commit_routing(ctx["order"]["id"])

    certified = register_node("S2")
    stock_inventory(certified["id"], ctx["sku"]["id"], 20, 2)

    second_run = commit_routing(ctx["order"]["id"])
    return {
        **ctx,
        "certified": certified,
        "first_run": first_run,
        "second_run": second_run,
    }


# ======================================================================
# Demand lines are frozen once routing has begun
# ======================================================================


def test_adding_a_line_after_a_provisional_run_reports_order_lines_locked(api):
    """PRD §3.2: "Lines are frozen the moment routing begins: adding a line to an order whose `routing_status` is no longer `UNROUTED` is rejected with `ERR_ORDER_LINES_LOCKED`."
    PRD §3.2: "With those in hand, the status is the first match in this fixed order: `UNROUTED` when no routing run exists for the order; otherwise `ROUTING` when open units is greater than 0 and the pending-reroute predicate holds; otherwise `UNROUTABLE` when covered units is 0; otherwise `ROUTED` when covered units plus cancelled units equals `total_units`; otherwise `PARTIALLY_ROUTED`."
    PRD §3.2: "Adding a line recomputes the order's `total_units`, `unassigned_units` and `dc_baseline_cost_cents`, and increments the order's `version`."

    Design: Corner/validations/adding_a_line_after_the_first_routing_run_returns_order_lines_locked
    """
    net = _stocked_node_and_sku()
    built = _order_with_one_line(net["sku"], "O-B001", "C-301", quantity=2)
    order_id = built["order"]["id"]

    provisional_routing(order_id)
    assert read_order(order_id)["routing_status"] != "UNROUTED", (
        "setup expected the PROVISIONAL run to move the order off UNROUTED"
    )

    response = api.create_order_line(
        order_id, create_order_line_payload(net["sku"]["id"], 1, 4500), CARE
    )

    validate_error(response, "ERR_ORDER_LINES_LOCKED")

    rows, meta = validate_paginated(
        api.list_order_lines(PLANNER, params={"order_id": order_id})
    )
    assert meta["total_count"] == 1, (
        f"the refused line must not be persisted: expected 1 demand line, got "
        f"{meta['total_count']}"
    )
    assert len(rows) == 1, "only the original demand line may be listed"

    order = read_order(order_id)
    assert order["total_units"] == 2, (
        f"total_units must still count only the accepted line, got {order['total_units']}"
    )
    assert order["unassigned_units"] == 2, (
        f"unassigned_units must still be 2, got {order['unassigned_units']}"
    )


def test_second_demand_line_is_accepted_while_the_order_is_still_unrouted(api):
    """PRD §3.2: "Demand lines are then added one at a time to the order, each carrying a `sku_id`, a `quantity` of at least 1 and a `unit_price_cents` of at least 0 recording the sold price."
    PRD §3.2: "A new line starts with `assigned_units`, `shipped_units`, `cancelled_units` and `dc_fallback_units` all 0, `open_units` equal to `quantity`, and `line_status` `OPEN`."
    PRD §3.2: "Adding a line recomputes the order's `total_units`, `unassigned_units` and `dc_baseline_cost_cents`, and increments the order's `version`."
    PRD §3.2: "Lines are frozen the moment routing begins: adding a line to an order whose `routing_status` is no longer `UNROUTED` is rejected with `ERR_ORDER_LINES_LOCKED`."
    PRD §2.5: "Most resources — nodes, SKUs, inventory rows, packaging rows, carrier pickups, customer orders, demand lines, routing runs, fulfillment assignments and performance windows — additionally carry `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation, and `version`, an integer that starts at 1 on creation and increments by exactly 1 on every mutation of that row."

    Design: Corner/validations/a_second_line_is_accepted_while_the_order_is_still_unrouted
    """
    set_clock(CLOCK_OPEN)
    sku_a = register_sku("SKU-A")
    sku_b = register_sku("SKU-B")
    built = _order_with_one_line(sku_a, "O-B101", "C-311", quantity=2)
    order_id = built["order"]["id"]

    response = api.create_order_line(
        order_id, create_order_line_payload(sku_b["id"], 3, 1900), CARE
    )

    second_line = validate_success(response, 201)
    assert second_line["quantity"] == 3, (
        f"the second line's quantity must be 3, got {second_line['quantity']}"
    )
    assert second_line["open_units"] == 3, (
        f"a new line's open_units equals its quantity, got {second_line['open_units']}"
    )
    assert second_line["line_status"] == "OPEN", (
        f"a new line starts at OPEN, got {second_line['line_status']}"
    )

    order = read_order(order_id)
    assert order["total_units"] == 5, (
        f"total_units is the sum of both lines' quantities, got {order['total_units']}"
    )
    assert order["unassigned_units"] == 5, (
        f"unassigned_units is the sum of both lines' open units, got "
        f"{order['unassigned_units']}"
    )
    assert order["routing_status"] == "UNROUTED", (
        f"no routing run exists yet, so routing_status stays UNROUTED, got "
        f"{order['routing_status']}"
    )
    assert order["version"] == 3, (
        f"intake writes version 1 and each of the two line adds increments it, so "
        f"version must be 3, got {order['version']}"
    )


# ======================================================================
# Request shape is checked before the path identifier is resolved
# ======================================================================


def test_zero_quantity_outranks_the_unknown_order_id_on_a_line_post(api):
    """PRD §2.11: "When a request violates several rules at once, exactly one error comes back, and which one is fixed."
    PRD §2.11: "Checks run in these bands, in this sequence."
    PRD §2.11: "Request shape second: required fields present, types correct, enum members inside their declared sets, integers inside their declared ranges — `limit` from 1 to 100, `offset` at least 0, `quantity` at least 1, `picked_units` at least 0, `parcel_capacity` at least 1, and both `origin_zone` and `destination_zone` from 1 to 8 — all reported as `ERR_INVALID_REQUEST`."
    PRD §2.11: "Existence third: path identifiers left to right, then foreign keys supplied in the body."

    Design: Corner/validations/body_shape_error_outranks_the_unresolved_path_id
    """
    set_clock(CLOCK_OPEN)
    sku = register_sku("SKU-A")
    intake_order(
        order_code="O-B201",
        customer_ref="C-321",
        destination_zone=4,
        service_level="GROUND",
        promised_ship_by_utc=PROMISED_SHIP_BY,
    )

    response = api.create_order_line(
        NON_EXISTENT_UUID, create_order_line_payload(sku["id"], 0, 4500), CARE
    )

    validate_error(response, "ERR_INVALID_REQUEST")

    _rows, meta = validate_paginated(api.list_order_lines(PLANNER))
    assert meta["total_count"] == 0, (
        f"a refused line POST must persist nothing, got {meta['total_count']} rows"
    )


def test_unknown_order_id_alone_reports_order_not_found_on_a_line_post(api):
    """PRD §2.11: "Existence third: path identifiers left to right, then foreign keys supplied in the body."
    PRD §2.4: "Where a path does carry more than one identifier — a pickup being scheduled at a node, or a demand line being added to an order — the identifiers are resolved strictly left to right, and the first one that does not resolve determines the 404 that comes back."
    PRD §2.4: "The per-identifier codes are `ERR_STORE_NOT_FOUND` for `store_id`, `ERR_SKU_NOT_FOUND` for `sku_id`, `ERR_INVENTORY_NOT_FOUND` for `inventory_id`, `ERR_PACKAGING_NOT_FOUND` for `supply_id`, `ERR_PICKUP_NOT_FOUND` for `pickup_id` (and for a `carrier_pickup_id` supplied in a body), `ERR_ORDER_NOT_FOUND` for `order_id`, `ERR_ORDER_LINE_NOT_FOUND` for `order_line_id`, `ERR_ROUTING_RUN_NOT_FOUND` for `routing_run_id`, `ERR_CANDIDATE_NOT_FOUND` for `candidate_id`, `ERR_ASSIGNMENT_NOT_FOUND` for `assignment_id`, `ERR_ASSIGNMENT_LINE_NOT_FOUND` for `assignment_line_id`, `ERR_WINDOW_NOT_FOUND` for `window_id` and `ERR_NOTIFICATION_NOT_FOUND` for `notification_id`."

    Design: Corner/validations/body_shape_error_outranks_the_unresolved_path_id
    """
    set_clock(CLOCK_OPEN)
    sku = register_sku("SKU-A")
    intake_order(
        order_code="O-B201",
        customer_ref="C-321",
        destination_zone=4,
        service_level="GROUND",
        promised_ship_by_utc=PROMISED_SHIP_BY,
    )

    response = api.create_order_line(
        NON_EXISTENT_UUID, create_order_line_payload(sku["id"], 2, 4500), CARE
    )

    validate_error(response, "ERR_ORDER_NOT_FOUND")

    _rows, meta = validate_paginated(api.list_order_lines(PLANNER))
    assert meta["total_count"] == 0, (
        f"a refused line POST must persist nothing, got {meta['total_count']} rows"
    )


# ======================================================================
# Routing needs at least one open demand unit
# ======================================================================


def test_routing_a_lineless_order_reports_no_routable_lines(api):
    """PRD §3.4: "Routing is refused when the order's `fulfillment_status` is anything other than `PENDING`, with `ERR_ORDER_NOT_ROUTABLE`, and when no demand line has at least one open unit, with `ERR_NO_ROUTABLE_LINES`."
    PRD §2.5: "Most resources — nodes, SKUs, inventory rows, packaging rows, carrier pickups, customer orders, demand lines, routing runs, fulfillment assignments and performance windows — additionally carry `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation, and `version`, an integer that starts at 1 on creation and increments by exactly 1 on every mutation of that row."

    Design: Corner/validations/routing_a_lineless_order_returns_no_routable_lines_then_succeeds
    """
    net = _stocked_node_and_sku()
    order = intake_order(
        order_code="O-B301",
        customer_ref="C-331",
        destination_zone=4,
        service_level="GROUND",
        promised_ship_by_utc=PROMISED_SHIP_BY,
    )
    assert net["inventory"]["available_to_promise_units"] == 18, (
        "setup expected the node to be able to promise 18 units"
    )

    response = api.create_routing_run(
        order["id"],
        create_routing_run_payload(order["version"], "COMMIT"),
        PLANNER,
    )

    validate_error(response, "ERR_NO_ROUTABLE_LINES")

    _rows, meta = validate_paginated(
        api.list_routing_runs(PLANNER, params={"order_id": order["id"]})
    )
    assert meta["total_count"] == 0, (
        f"a refused routing run must persist no RoutingRun row, got "
        f"{meta['total_count']}"
    )
    assert read_order(order["id"])["version"] == 1, (
        "a refused run is not a mutation of the order, so its version stays at 1"
    )


def test_routing_the_same_order_succeeds_once_a_demand_line_exists(api):
    """PRD §3.4: "Routing is refused when the order's `fulfillment_status` is anything other than `PENDING`, with `ERR_ORDER_NOT_ROUTABLE`, and when no demand line has at least one open unit, with `ERR_NO_ROUTABLE_LINES`."
    PRD §3.4: "Otherwise a `COMMIT` run's `status` is `COMMITTED`."
    PRD §3.4: "When the loop ends, `unfulfillable_units` records whatever remaining demand is left, and `selected_store_count` and `planned_split_count` both equal the number of nodes selected."
    PRD §3.4: "`projected_cost_cents` is the order-level store cost this run projects, computed on the provisional basis of §3.8 including the split penalty, the reroute overhead and the network overhead fee."
    PRD §3.8: "That gap indexes a base shipping charge — 320 cents at a gap of 0, then 380, 445, 520, 610, 700, 800 and 900 cents at gaps of 1 through 7 respectively."
    PRD §3.8: "For each line, the line weight is the served SKU's `unit_weight_grams` multiplied by the units on that line; the number of weight steps is that weight divided by a 500-gram step and rounded up to a whole number of steps; the raw line charge is the zone base charge plus 25 cents per weight step; that raw charge is multiplied by the service multiplier — 1.00 for a `GROUND` order and 1.35 for an `EXPEDITED` one — and the product is rounded half-up to whole cents."
    PRD §3.8: "**Labour cost** is the charged labour minutes multiplied by the node's `labor_rate_cents_per_minute`, rounded up to the next whole cent."
    PRD §3.8: "**Packaging cost** is the base cost of the charged package type — 45 cents for a `POLY_MAILER`, 85 for a `SMALL_BOX`, 130 for a `MEDIUM_BOX` and 190 for a `LARGE_BOX` — plus 15 cents of dunnage per charged unit."
    PRD §3.8: "The assignment's cost is labour cost plus packaging cost plus ship cost."
    PRD §3.8: "The **provisional** variant, written to the assignment's `provisional_cost_cents` at candidate evaluation and at assignment creation, charges the labour *standard*: `labor_standard_minutes_per_order` plus `pick_labor_minutes_per_unit` multiplied by `assigned_units`."
    PRD §3.8: "The pre-fee subtotal is that component sum, plus a split penalty of 175 cents for each parcel beyond the first, plus a reroute overhead of 90 cents multiplied by the order's `reroute_attempt_count`."
    PRD §3.8: "The overhead fee rate is then keyed on the pre-fee subtotal: 6.0 percent when the subtotal is strictly below 2000 cents, 4.5 percent when it is strictly below 5000 cents, and 3.0 percent at or above 5000 cents."
    PRD §3.8: "The network fee is the pre-fee subtotal multiplied by that rate, rounded half-up to whole cents, and the store cost is the pre-fee subtotal plus the network fee."
    PRD §3.4: "A planner's `COMMIT` run on an order at `UNROUTED` lands it on `ROUTED` when every open unit is covered, on `PARTIALLY_ROUTED` when some but not all are covered — with the shortfall recorded in `unfulfillable_units` and left in `open_units` unless the three-split ceiling converted it to `dc_fallback_units`, which is the only case in which that run emits a `DC_FALLBACK` notification — and on `UNROUTABLE` when the pool is empty at the first iteration."

    Design: Corner/validations/routing_a_lineless_order_returns_no_routable_lines_then_succeeds
    """
    net = _stocked_node_and_sku()
    order = intake_order(
        order_code="O-B301",
        customer_ref="C-331",
        destination_zone=4,
        service_level="GROUND",
        promised_ship_by_utc=PROMISED_SHIP_BY,
    )
    refused = api.create_routing_run(
        order["id"],
        create_routing_run_payload(order["version"], "COMMIT"),
        PLANNER,
    )
    validate_error(refused, "ERR_NO_ROUTABLE_LINES")

    add_order_line(order["id"], net["sku"]["id"], 2, 4500)
    run = commit_routing(order["id"])

    assert run["status"] == "COMMITTED", (
        f"the identical call must commit once a line has open units, got "
        f"{run['status']}"
    )
    assert run["selected_store_count"] == 1, (
        f"exactly one node covers the two units, got {run['selected_store_count']}"
    )
    assert run["projected_cost_cents"] == 1416, (
        f"projected_cost_cents must be 1416, got {run['projected_cost_cents']}"
    )

    rows, meta = validate_paginated(
        api.list_routing_runs(PLANNER, params={"order_id": order["id"]})
    )
    assert meta["total_count"] == 1, (
        f"only the successful run may be persisted, got {meta['total_count']} runs"
    )
    assert rows[0]["id"] == run["id"], "the single persisted run is the successful one"

    after = read_order(order["id"])
    assert after["routing_status"] == "ROUTED", (
        f"every open unit is covered, so routing_status is ROUTED, got "
        f"{after['routing_status']}"
    )
    assert after["unassigned_units"] == 0, (
        f"no open unit is left after the commit, got {after['unassigned_units']}"
    )


# ======================================================================
# Temporal shape: the logical clock and the pickup window's geometry
# ======================================================================


def test_moving_the_clock_backwards_reports_clock_not_monotonic(api):
    """PRD §2.6: "The clock is monotonic: a `to_iso8601` earlier than the clock's current value is rejected with `ERR_CLOCK_NOT_MONOTONIC` (HTTP 422), while a value equal to the current one is accepted."
    PRD §2.6: "A `NetworkPlanner` may advance it through an administrative test-driving capability that takes a `to_iso8601` instant and answers with the resulting `current_utc` alongside the `previous_utc` it replaced."

    Design: Corner/validations/clock_regression_and_an_inverted_pickup_window_are_both_refused
    """
    set_clock(CLOCK_OPEN)
    register_node("S1")

    response = api.set_clock({"to_iso8601": CLOCK_BEFORE_OPEN}, PLANNER)

    validate_error(response, "ERR_CLOCK_NOT_MONOTONIC")

    reread = validate_success(api.set_clock({"to_iso8601": CLOCK_OPEN}, PLANNER))
    assert reread["previous_utc"].startswith("2026-08-03T09:00:00"), (
        "the refused regression must leave the clock at 09:00, but the accepted "
        f"re-set reports previous_utc {reread['previous_utc']}"
    )


def test_setting_the_clock_to_the_value_it_already_holds_is_accepted(api):
    """PRD §2.6: "The clock is monotonic: a `to_iso8601` earlier than the clock's current value is rejected with `ERR_CLOCK_NOT_MONOTONIC` (HTTP 422), while a value equal to the current one is accepted."
    PRD §2.6: "A `NetworkPlanner` may advance it through an administrative test-driving capability that takes a `to_iso8601` instant and answers with the resulting `current_utc` alongside the `previous_utc` it replaced."

    Design: Corner/validations/clock_regression_and_an_inverted_pickup_window_are_both_refused
    """
    set_clock(CLOCK_OPEN)

    data = validate_success(api.set_clock({"to_iso8601": CLOCK_OPEN}, PLANNER))

    assert data["current_utc"].startswith("2026-08-03T09:00:00"), (
        f"current_utc must report the instant just set, got {data['current_utc']}"
    )
    assert data["previous_utc"].startswith("2026-08-03T09:00:00"), (
        f"previous_utc must report the identical instant it replaced, got "
        f"{data['previous_utc']}"
    )


def test_pickup_window_with_equal_start_and_end_reports_invalid_window(api):
    """PRD §3.6: "Pickup windows are scheduled per node by a `CarrierCoordinator` or a `NetworkPlanner`, with a `carrier_code` identifying the carrier, an inclusive `window_start_utc`, an exclusive `window_end_utc` that must be strictly later (otherwise `ERR_INVALID_WINDOW`), and a `parcel_capacity` of at least 1 giving the parcels the carrier will accept in that window."

    Design: Corner/validations/clock_regression_and_an_inverted_pickup_window_are_both_refused
    """
    set_clock(CLOCK_OPEN)
    store = register_node("S1")

    response = api.create_carrier_pickup(
        store["id"],
        create_carrier_pickup_payload(
            carrier_code="ACME",
            window_start_utc="2026-08-03T10:00:00Z",
            window_end_utc="2026-08-03T10:00:00Z",
            parcel_capacity=2,
        ),
        CARRIER,
    )

    validate_error(response, "ERR_INVALID_WINDOW")

    _rows, meta = validate_paginated(
        api.list_carrier_pickups(CARRIER, params={"store_id": store["id"]})
    )
    assert meta["total_count"] == 0, (
        f"a refused window must write no CarrierPickup row, got {meta['total_count']}"
    )


def test_pickup_window_one_second_long_is_accepted(api):
    """PRD §3.6: "Pickup windows are scheduled per node by a `CarrierCoordinator` or a `NetworkPlanner`, with a `carrier_code` identifying the carrier, an inclusive `window_start_utc`, an exclusive `window_end_utc` that must be strictly later (otherwise `ERR_INVALID_WINDOW`), and a `parcel_capacity` of at least 1 giving the parcels the carrier will accept in that window."
    PRD §3.6: "A new window begins at `status` `SCHEDULED` with `reserved_parcels` 0."

    Design: Corner/validations/clock_regression_and_an_inverted_pickup_window_are_both_refused
    """
    set_clock(CLOCK_OPEN)
    store = register_node("S1")

    response = api.create_carrier_pickup(
        store["id"],
        create_carrier_pickup_payload(
            carrier_code="ACME",
            window_start_utc="2026-08-03T10:00:00Z",
            window_end_utc="2026-08-03T10:00:01Z",
            parcel_capacity=2,
        ),
        CARRIER,
    )

    pickup = validate_success(response, 201)
    assert pickup["status"] == "SCHEDULED", (
        f"a one-second window satisfies the strict-inequality rule, got "
        f"{pickup['status']}"
    )
    assert pickup["reserved_parcels"] == 0, (
        f"a new window holds no parcels, got {pickup['reserved_parcels']}"
    )


# ======================================================================
# Hazmat demand may only be routed to a certified node
# ======================================================================


def test_hazmat_demand_with_no_certified_node_ends_no_eligible_node():
    """PRD §3.1: "A SKU whose `hazmat_flag` is true may only be fulfilled from a node whose `hazmat_certified` is true."
    PRD §3.4: "for every SKU still in remaining demand whose `hazmat_flag` is true, the node's `hazmat_certified` is true — otherwise `HAZMAT_NOT_CERTIFIED`;"
    PRD §3.4: "Candidates that failed the eligibility filter carry a null `routing_score` and a null `rank`; they are still persisted so the planner can see why they lost."
    PRD §3.4: "If the pool was already empty on the very first iteration, the run's `status` becomes `NO_ELIGIBLE_NODE` with `selected_store_count` 0 and `unfulfillable_units` equal to the order's `unassigned_units`, a notification of type `UNROUTABLE` is emitted, and no assignment and no reservation change occurs at all."
    PRD §3.4: "`candidate_count` records how many candidate rows this run persisted across all iterations."
    PRD §3.4: "When the loop ends, `unfulfillable_units` records whatever remaining demand is left, and `selected_store_count` and `planned_split_count` both equal the number of nodes selected."
    PRD §3.7: "It carries a `channel` of `EMAIL` or `SMS`, defaulting to `EMAIL`, a `units_affected` count of the units the event moved or removed, a `sent_at_utc` clock instant, and a `body_summary` — a templated one-line summary containing the order's `order_code`, the `notification_type` and the `units_affected` count."

    Design: Corner/validations/hazmat_routing_requires_a_certified_node
    """
    ctx = _hazmat_demand_at_uncertified_node()
    assert ctx["sku"]["hazmat_flag"] is True, "setup expected a hazardous SKU"
    assert ctx["store"]["hazmat_certified"] is False, (
        "setup expected the only node in the network to be uncertified"
    )

    run = commit_routing(ctx["order"]["id"])

    assert run["status"] == "NO_ELIGIBLE_NODE", (
        f"an empty pool on the first iteration ends the run at NO_ELIGIBLE_NODE, got "
        f"{run['status']}"
    )
    assert run["candidate_count"] == 1, (
        f"the single node is still evaluated and persisted, got "
        f"{run['candidate_count']}"
    )
    assert run["selected_store_count"] == 0, (
        f"no node was selected, got {run['selected_store_count']}"
    )
    assert run["planned_split_count"] == 0, (
        f"no node was selected, so no parcel was planned, got "
        f"{run['planned_split_count']}"
    )
    assert run["unfulfillable_units"] == 2, (
        f"both demanded units are unfulfillable, got {run['unfulfillable_units']}"
    )

    candidates = find_routing_candidates(routing_run_id=run["id"])
    assert len(candidates) == 1, (
        f"exactly one candidate row is expected, got {len(candidates)}"
    )
    candidate = candidates[0]
    assert candidate["eligible"] is False, "an uncertified node cannot be eligible"
    assert candidate["ineligible_reason"] == "HAZMAT_NOT_CERTIFIED", (
        f"the failing clause must be recorded as HAZMAT_NOT_CERTIFIED, got "
        f"{candidate['ineligible_reason']}"
    )
    assert candidate["routing_score"] is None, (
        "an ineligible candidate carries a null routing_score"
    )
    assert candidate["rank"] is None, "an ineligible candidate carries a null rank"
    assert candidate["selected"] is False, "an ineligible candidate is never selected"

    order = read_order(ctx["order"]["id"])
    assert order["routing_status"] == "UNROUTABLE", (
        f"covered units are 0 after the run, so routing_status is UNROUTABLE, got "
        f"{order['routing_status']}"
    )

    notifications = find_notifications(order_id=ctx["order"]["id"])
    assert len(notifications) == 1, (
        f"exactly one notification is emitted, got {len(notifications)}"
    )
    assert notifications[0]["notification_type"] == "UNROUTABLE", (
        f"the empty-pool exit notifies UNROUTABLE, got "
        f"{notifications[0]['notification_type']}"
    )
    assert notifications[0]["units_affected"] == 2, (
        f"both units are affected, got {notifications[0]['units_affected']}"
    )

    line = read_order_line(ctx["line"]["id"])
    assert line["open_units"] == 2, (
        f"an empty-pool exit leaves the units open, got {line['open_units']}"
    )
    assert line["dc_fallback_units"] == 0, (
        f"an empty-pool exit never hands units to the distribution centre, got "
        f"{line['dc_fallback_units']}"
    )


def test_hazmat_demand_commits_to_the_certified_node_once_it_exists():
    """PRD §3.1: "A SKU whose `hazmat_flag` is true may only be fulfilled from a node whose `hazmat_certified` is true."
    PRD §3.4: "for every SKU still in remaining demand whose `hazmat_flag` is true, the node's `hazmat_certified` is true — otherwise `HAZMAT_NOT_CERTIFIED`;"
    PRD §3.4: "`candidate_count` records how many candidate rows this run persisted across all iterations."
    PRD §3.4: "Otherwise a `COMMIT` run's `status` is `COMMITTED`."
    PRD §3.4: "The winner's `selected` flag is set to true and its `assigned_units` is set equal to its `coverage_units`."
    PRD §3.4: "From `UNROUTABLE`, a `COMMIT` run issued after inventory or node posture has changed can also move the order to `ROUTED`, which closes the cycle and guarantees that an unroutable order is never permanently stuck; both of those transitions require the order's `fulfillment_status` to be `PENDING` and at least one demand line with at least one open unit, and both carry the same side effects as the original `UNROUTED` to `ROUTED` move."
    PRD §3.5: "`derived_package_type` is the package the provisional cost assumes: take the heaviest `package_class` among the allocation's SKUs by package rank and map it, so `SMALL` becomes `SMALL_BOX`, `MEDIUM` becomes `MEDIUM_BOX` and `LARGE` becomes `LARGE_BOX`."

    Design: Corner/validations/hazmat_routing_requires_a_certified_node
    """
    ctx = _commit_hazmat_demand_after_adding_certified_node()
    run = ctx["second_run"]

    assert run["status"] == "COMMITTED", (
        f"the certified node covers the demand, so the run commits, got "
        f"{run['status']}"
    )
    assert run["candidate_count"] == 2, (
        f"both nodes are evaluated and persisted, got {run['candidate_count']}"
    )
    assert run["selected_store_count"] == 1, (
        f"only the certified node may be selected, got {run['selected_store_count']}"
    )

    candidates = find_routing_candidates(routing_run_id=run["id"])
    by_store = {row["store_id"]: row for row in candidates}
    uncertified = by_store[ctx["store"]["id"]]
    certified = by_store[ctx["certified"]["id"]]
    assert uncertified["eligible"] is False, (
        "the uncertified node is still filtered out on the second run"
    )
    assert uncertified["ineligible_reason"] == "HAZMAT_NOT_CERTIFIED", (
        f"the uncertified node still fails on hazmat, got "
        f"{uncertified['ineligible_reason']}"
    )
    assert certified["eligible"] is True, "the certified node clears every clause"
    assert certified["selected"] is True, "the certified node is the winner"

    assignment = find_assignment(
        order_id=ctx["order"]["id"], store_id=ctx["certified"]["id"]
    )
    assert assignment["store_id"] == ctx["certified"]["id"], (
        "the assignment must be created at the hazmat-certified node"
    )
    assert assignment["assigned_units"] == 2, (
        f"the winner covers both units, got {assignment['assigned_units']}"
    )
    assert assignment["derived_package_type"] == "LARGE_BOX", (
        f"a LARGE package_class maps to LARGE_BOX, got "
        f"{assignment['derived_package_type']}"
    )

    order = read_order(ctx["order"]["id"])
    assert order["routing_status"] == "ROUTED", (
        f"the previously unroutable order returns to ROUTED, got "
        f"{order['routing_status']}"
    )
    assert order["unassigned_units"] == 0, (
        f"no open unit is left, got {order['unassigned_units']}"
    )


def test_hazmat_commit_prices_the_certified_node_parcel():
    """PRD §3.8: "Start from the zone gap: the absolute difference between the order's `destination_zone` and the node's `origin_zone`."
    PRD §3.8: "That gap indexes a base shipping charge — 320 cents at a gap of 0, then 380, 445, 520, 610, 700, 800 and 900 cents at gaps of 1 through 7 respectively."
    PRD §3.8: "For each line, the line weight is the served SKU's `unit_weight_grams` multiplied by the units on that line; the number of weight steps is that weight divided by a 500-gram step and rounded up to a whole number of steps; the raw line charge is the zone base charge plus 25 cents per weight step; that raw charge is multiplied by the service multiplier — 1.00 for a `GROUND` order and 1.35 for an `EXPEDITED` one — and the product is rounded half-up to whole cents."
    PRD §3.8: "**Labour cost** is the charged labour minutes multiplied by the node's `labor_rate_cents_per_minute`, rounded up to the next whole cent."
    PRD §3.8: "**Packaging cost** is the base cost of the charged package type — 45 cents for a `POLY_MAILER`, 85 for a `SMALL_BOX`, 130 for a `MEDIUM_BOX` and 190 for a `LARGE_BOX` — plus 15 cents of dunnage per charged unit."
    PRD §3.8: "The assignment's cost is labour cost plus packaging cost plus ship cost."
    PRD §3.8: "The **provisional** variant, written to the assignment's `provisional_cost_cents` at candidate evaluation and at assignment creation, charges the labour *standard*: `labor_standard_minutes_per_order` plus `pick_labor_minutes_per_unit` multiplied by `assigned_units`."
    PRD §3.8: "The pre-fee subtotal is that component sum, plus a split penalty of 175 cents for each parcel beyond the first, plus a reroute overhead of 90 cents multiplied by the order's `reroute_attempt_count`."
    PRD §3.8: "The overhead fee rate is then keyed on the pre-fee subtotal: 6.0 percent when the subtotal is strictly below 2000 cents, 4.5 percent when it is strictly below 5000 cents, and 3.0 percent at or above 5000 cents."
    PRD §3.8: "The network fee is the pre-fee subtotal multiplied by that rate, rounded half-up to whole cents, and the store cost is the pre-fee subtotal plus the network fee."
    PRD §3.8: "The distribution-centre baseline is a per-zone handling figure plus a per-unit charge: 1450 cents for `destination_zone` 1, then 1560, 1700, 1850, 2010, 2180, 2360 and 2550 cents for zones 2 through 8, plus 120 cents multiplied by the order's `total_units`."
    PRD §3.8: "The cost index in basis points is the store cost multiplied by 10000, divided by the baseline, rounded half-up — and 0 when the baseline is 0."
    PRD §3.8: "The order's `cost_index_bps` uses `final_cost_cents` once that is set and `provisional_cost_cents` before then."

    Design: Corner/validations/hazmat_routing_requires_a_certified_node
    """
    ctx = _commit_hazmat_demand_after_adding_certified_node()

    assignment = find_assignment(
        order_id=ctx["order"]["id"], store_id=ctx["certified"]["id"]
    )
    assert assignment["provisional_cost_cents"] == 1599, (
        f"the certified node's parcel prices at 1599 cents, got "
        f"{assignment['provisional_cost_cents']}"
    )

    order = read_order(ctx["order"]["id"])
    assert order["provisional_cost_cents"] == 1695, (
        f"the order-level provisional cost is 1695 cents, got "
        f"{order['provisional_cost_cents']}"
    )
    assert order["cost_index_bps"] == 8110, (
        f"the cost index against the zone-4 baseline is 8110 bps, got "
        f"{order['cost_index_bps']}"
    )


def test_certified_node_rescores_after_the_hazmat_commit():
    """PRD §3.3: "`eligibility_score` is the routing-time score, recomputed whenever the node's reservation levels change — on a routing-run commit, an accept, a reject, a cancel, a pick shortfall or a ship — on reactivation, on an inventory adjustment, on a posture adjustment, and at the final step of the operations run."
    PRD §3.3: "The score is the sum of three components, each rounded half-up to four decimal places, with the sum then rounded half-up to two decimal places."
    PRD §3.3: "The **capacity component** starts from capacity headroom: the larger of 0 and `daily_unit_capacity` minus `units_committed_epoch`."
    PRD §3.3: "That headroom is divided by a reference of 200 units, the quotient is capped at 1, and the result is multiplied by a weight of 40."
    PRD §3.3: "The **labour component** starts from labour headroom: the larger of 0 and `staffed_labor_minutes` minus `reserved_labor_minutes`."
    PRD §3.3: "That headroom is divided by a reference of eight staffed hours, the quotient is capped at 1, and the result is multiplied by a weight of 30."
    PRD §3.3: "The **performance component** is a weight of 30 multiplied by a performance ratio between 0 and 1."
    PRD §3.3: "A node with zero closed performance windows uses a flat performance ratio of 0.60 and records `eligibility_score_basis` as `COLD_START`."
    PRD §3.5: "`labor_minutes_reserved` is the node's `labor_standard_minutes_per_order` plus its `pick_labor_minutes_per_unit` multiplied by `assigned_units` — the labour standard, committed once and never rewritten."

    Design: Corner/validations/hazmat_routing_requires_a_certified_node
    """
    ctx = _commit_hazmat_demand_after_adding_certified_node()

    certified = read_store(ctx["certified"]["id"])
    assert certified["units_committed_epoch"] == 2, (
        f"the commit charges the node with two units, got "
        f"{certified['units_committed_epoch']}"
    )
    assert certified["reserved_labor_minutes"] == pytest.approx(23, abs=0.01), (
        f"the labour standard is 15 + 4 * 2 = 23 minutes, got "
        f"{certified['reserved_labor_minutes']}"
    )
    assert certified["eligibility_score"] == pytest.approx(46.91, abs=0.01), (
        f"the cold-start score after the commit is 46.91, got "
        f"{certified['eligibility_score']}"
    )


# ======================================================================
# The assignment must be loaded before its node can be compared
# ======================================================================


def test_accept_on_unknown_assignment_id_reports_assignment_not_found(api):
    """PRD §2.11: "Existence third: path identifiers left to right, then foreign keys supplied in the body."
    PRD §2.11: "Node-scope ownership fourth, as `ERR_STORE_SCOPE_VIOLATION`."
    PRD §2.11: "Checks run in these bands, in this sequence."
    PRD §2.4: "The per-identifier codes are `ERR_STORE_NOT_FOUND` for `store_id`, `ERR_SKU_NOT_FOUND` for `sku_id`, `ERR_INVENTORY_NOT_FOUND` for `inventory_id`, `ERR_PACKAGING_NOT_FOUND` for `supply_id`, `ERR_PICKUP_NOT_FOUND` for `pickup_id` (and for a `carrier_pickup_id` supplied in a body), `ERR_ORDER_NOT_FOUND` for `order_id`, `ERR_ORDER_LINE_NOT_FOUND` for `order_line_id`, `ERR_ROUTING_RUN_NOT_FOUND` for `routing_run_id`, `ERR_CANDIDATE_NOT_FOUND` for `candidate_id`, `ERR_ASSIGNMENT_NOT_FOUND` for `assignment_id`, `ERR_ASSIGNMENT_LINE_NOT_FOUND` for `assignment_line_id`, `ERR_WINDOW_NOT_FOUND` for `window_id` and `ERR_NOTIFICATION_NOT_FOUND` for `notification_id`."
    PRD §2.1: "Concretely, when a `StoreAssociate` accepts, rejects, picks, packs or ships an assignment, or posts an inventory adjustment, or restocks packaging, the `store_id` of the targeted assignment, inventory row or packaging row must equal `X-User-ID`; a mismatch is rejected with `ERR_STORE_SCOPE_VIOLATION` (HTTP 403)."
    PRD §3.1: "Registration seeds the node's derived state: `node_status` becomes `ELIGIBLE`, `units_committed_epoch` and `reserved_labor_minutes` are 0, `consecutive_breach_windows` is 0, `reactivation_count` is 0, `deactivated_at_epoch` is null, and `review_score` is 0."

    Design: Corner/validations/unknown_assignment_id_is_reported_before_the_store_scope_check
    """
    set_clock(CLOCK_OPEN)
    first = register_node("S1")
    third = register_node("S3")

    response = api.accept_assignment(
        NON_EXISTENT_UUID, make_store_associate_headers(first["id"])
    )

    validate_error(response, "ERR_ASSIGNMENT_NOT_FOUND")

    for node in (read_store(first["id"]), read_store(third["id"])):
        assert node["version"] == 1, (
            f"a refused accept mutates no node, but {node['store_code']} is at "
            f"version {node['version']}"
        )
        assert node["reserved_labor_minutes"] == pytest.approx(0, abs=0.01), (
            f"{node['store_code']} must still hold no reserved labour, got "
            f"{node['reserved_labor_minutes']}"
        )


def test_pick_on_unknown_assignment_id_outranks_the_unknown_line_and_the_scope_check(
    api,
):
    """PRD §2.11: "Existence third: path identifiers left to right, then foreign keys supplied in the body."
    PRD §2.11: "Node-scope ownership fourth, as `ERR_STORE_SCOPE_VIOLATION`."
    PRD §2.4: "The per-identifier codes are `ERR_STORE_NOT_FOUND` for `store_id`, `ERR_SKU_NOT_FOUND` for `sku_id`, `ERR_INVENTORY_NOT_FOUND` for `inventory_id`, `ERR_PACKAGING_NOT_FOUND` for `supply_id`, `ERR_PICKUP_NOT_FOUND` for `pickup_id` (and for a `carrier_pickup_id` supplied in a body), `ERR_ORDER_NOT_FOUND` for `order_id`, `ERR_ORDER_LINE_NOT_FOUND` for `order_line_id`, `ERR_ROUTING_RUN_NOT_FOUND` for `routing_run_id`, `ERR_CANDIDATE_NOT_FOUND` for `candidate_id`, `ERR_ASSIGNMENT_NOT_FOUND` for `assignment_id`, `ERR_ASSIGNMENT_LINE_NOT_FOUND` for `assignment_line_id`, `ERR_WINDOW_NOT_FOUND` for `window_id` and `ERR_NOTIFICATION_NOT_FOUND` for `notification_id`."
    PRD §2.4: "Foreign keys supplied in a request body resolve under the same codes: a `store_id` or `sku_id` on an inventory row, a `store_id` on a packaging row, a `sku_id` on a demand line, an `assignment_line_id` inside a pick payload, or a `carrier_pickup_id` on a ship request."
    PRD §2.1: "Concretely, when a `StoreAssociate` accepts, rejects, picks, packs or ships an assignment, or posts an inventory adjustment, or restocks packaging, the `store_id` of the targeted assignment, inventory row or packaging row must equal `X-User-ID`; a mismatch is rejected with `ERR_STORE_SCOPE_VIOLATION` (HTTP 403)."

    Design: Corner/validations/unknown_assignment_id_is_reported_before_the_store_scope_check
    """
    set_clock(CLOCK_OPEN)
    register_node("S1")
    third = register_node("S3")

    response = api.pick_assignment(
        NON_EXISTENT_UUID,
        pick_payload(1, [line_pick(NON_EXISTENT_UUID, 1)]),
        make_store_associate_headers(third["id"]),
    )

    validate_error(response, "ERR_ASSIGNMENT_NOT_FOUND")

    node = read_store(third["id"])
    assert node["version"] == 1, (
        f"a refused pick mutates no node, but {node['store_code']} is at version "
        f"{node['version']}"
    )
