"""Error catalogue: each refusal code fired at its own trigger.

Grouped by the kind of defect that produces the code — an unresolvable child
id, a re-posted natural key, a malformed pick or pack payload, a temporal
boundary, node posture, and the network-wide ops-run guard. Every refusal test
also proves the refusal was inert, because a rejected request must not move the
row it was aimed at.
"""

from datetime import datetime

import pytest

from test_helpers import (
    CARE,
    CARRIER,
    NON_EXISTENT_UUID,
    PLANNER,
    accept,
    close_windows,
    commit_routing,
    cancel_order,
    create_order_payload,
    create_packaging_supply_payload,
    create_sku_payload,
    create_store_inventory_payload,
    create_store_payload,
    find_assignment,
    find_assignment_lines,
    find_windows,
    line_pick,
    make_store_associate_headers,
    pick_full,
    pick_payload,
    read_assignment,
    read_assignment_line,
    read_inventory,
    read_order,
    read_packaging,
    read_store,
    register_node,
    register_sku,
    set_clock,
    setup_order_with_lines,
    stock_inventory,
    stock_packaging,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK_OPEN = "2026-08-03T09:00:00Z"
CLOCK_ONE_SECOND_BEFORE_DEADLINE = "2026-08-03T12:59:59Z"
CLOCK_AT_DEADLINE = "2026-08-03T13:00:00Z"
PICK_DEADLINE = "2026-08-03T13:00:00Z"
PROMISED_SHIP_BY = "2026-08-04T15:00:00Z"


def _instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant so two spellings of the same moment compare
    equal regardless of how many fractional digits the server printed."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _commit_one_line_order(
    sku: dict,
    order_code: str,
    customer_ref: str,
    quantity: int = 2,
    unit_price_cents: int = 4500,
) -> dict:
    """Intake a single-line GROUND order to zone 4 and commit it to the network."""
    built = setup_order_with_lines(
        [(sku["id"], quantity, unit_price_cents)],
        order_code=order_code,
        customer_ref=customer_ref,
        destination_zone=4,
        service_level="GROUND",
        promised_ship_by_utc=PROMISED_SHIP_BY,
    )
    commit_routing(built["order"]["id"])
    return built["order"]


# ======================================================================
# Unknown child ids: one 404 code per entity
# ======================================================================


def test_unknown_inventory_id_returns_inventory_not_found(api):
    """PRD §2.4: "Where a path does carry more than one identifier — a pickup being scheduled at a node, or a demand line being added to an order — the identifiers are resolved strictly left to right, and the first one that does not resolve determines the 404 that comes back."
    PRD §2.4: "The per-identifier codes are `ERR_STORE_NOT_FOUND` for `store_id`, `ERR_SKU_NOT_FOUND` for `sku_id`, `ERR_INVENTORY_NOT_FOUND` for `inventory_id`, `ERR_PACKAGING_NOT_FOUND` for `supply_id`, `ERR_PICKUP_NOT_FOUND` for `pickup_id` (and for a `carrier_pickup_id` supplied in a body), `ERR_ORDER_NOT_FOUND` for `order_id`, `ERR_ORDER_LINE_NOT_FOUND` for `order_line_id`, `ERR_ROUTING_RUN_NOT_FOUND` for `routing_run_id`, `ERR_CANDIDATE_NOT_FOUND` for `candidate_id`, `ERR_ASSIGNMENT_NOT_FOUND` for `assignment_id`, `ERR_ASSIGNMENT_LINE_NOT_FOUND` for `assignment_line_id`, `ERR_WINDOW_NOT_FOUND` for `window_id` and `ERR_NOTIFICATION_NOT_FOUND` for `notification_id`."

    Design: Corner/errors/unknown_child_ids_each_return_their_own_not_found_code
    """
    response = api.get_store_inventory(NON_EXISTENT_UUID, PLANNER)

    validate_error(response, "ERR_INVENTORY_NOT_FOUND")


def test_unknown_supply_id_returns_packaging_not_found(api):
    """PRD §2.4: "Where a path does carry more than one identifier — a pickup being scheduled at a node, or a demand line being added to an order — the identifiers are resolved strictly left to right, and the first one that does not resolve determines the 404 that comes back."
    PRD §2.4: "The per-identifier codes are `ERR_STORE_NOT_FOUND` for `store_id`, `ERR_SKU_NOT_FOUND` for `sku_id`, `ERR_INVENTORY_NOT_FOUND` for `inventory_id`, `ERR_PACKAGING_NOT_FOUND` for `supply_id`, `ERR_PICKUP_NOT_FOUND` for `pickup_id` (and for a `carrier_pickup_id` supplied in a body), `ERR_ORDER_NOT_FOUND` for `order_id`, `ERR_ORDER_LINE_NOT_FOUND` for `order_line_id`, `ERR_ROUTING_RUN_NOT_FOUND` for `routing_run_id`, `ERR_CANDIDATE_NOT_FOUND` for `candidate_id`, `ERR_ASSIGNMENT_NOT_FOUND` for `assignment_id`, `ERR_ASSIGNMENT_LINE_NOT_FOUND` for `assignment_line_id`, `ERR_WINDOW_NOT_FOUND` for `window_id` and `ERR_NOTIFICATION_NOT_FOUND` for `notification_id`."

    Design: Corner/errors/unknown_child_ids_each_return_their_own_not_found_code
    """
    response = api.get_packaging_supply(NON_EXISTENT_UUID, PLANNER)

    validate_error(response, "ERR_PACKAGING_NOT_FOUND")


def test_unknown_pickup_id_returns_pickup_not_found(api):
    """PRD §2.4: "Where a path does carry more than one identifier — a pickup being scheduled at a node, or a demand line being added to an order — the identifiers are resolved strictly left to right, and the first one that does not resolve determines the 404 that comes back."
    PRD §2.4: "The per-identifier codes are `ERR_STORE_NOT_FOUND` for `store_id`, `ERR_SKU_NOT_FOUND` for `sku_id`, `ERR_INVENTORY_NOT_FOUND` for `inventory_id`, `ERR_PACKAGING_NOT_FOUND` for `supply_id`, `ERR_PICKUP_NOT_FOUND` for `pickup_id` (and for a `carrier_pickup_id` supplied in a body), `ERR_ORDER_NOT_FOUND` for `order_id`, `ERR_ORDER_LINE_NOT_FOUND` for `order_line_id`, `ERR_ROUTING_RUN_NOT_FOUND` for `routing_run_id`, `ERR_CANDIDATE_NOT_FOUND` for `candidate_id`, `ERR_ASSIGNMENT_NOT_FOUND` for `assignment_id`, `ERR_ASSIGNMENT_LINE_NOT_FOUND` for `assignment_line_id`, `ERR_WINDOW_NOT_FOUND` for `window_id` and `ERR_NOTIFICATION_NOT_FOUND` for `notification_id`."

    Design: Corner/errors/unknown_child_ids_each_return_their_own_not_found_code
    """
    response = api.get_carrier_pickup(NON_EXISTENT_UUID, PLANNER)

    validate_error(response, "ERR_PICKUP_NOT_FOUND")


def test_unknown_order_line_id_returns_order_line_not_found(api):
    """PRD §2.4: "Where a path does carry more than one identifier — a pickup being scheduled at a node, or a demand line being added to an order — the identifiers are resolved strictly left to right, and the first one that does not resolve determines the 404 that comes back."
    PRD §2.4: "The per-identifier codes are `ERR_STORE_NOT_FOUND` for `store_id`, `ERR_SKU_NOT_FOUND` for `sku_id`, `ERR_INVENTORY_NOT_FOUND` for `inventory_id`, `ERR_PACKAGING_NOT_FOUND` for `supply_id`, `ERR_PICKUP_NOT_FOUND` for `pickup_id` (and for a `carrier_pickup_id` supplied in a body), `ERR_ORDER_NOT_FOUND` for `order_id`, `ERR_ORDER_LINE_NOT_FOUND` for `order_line_id`, `ERR_ROUTING_RUN_NOT_FOUND` for `routing_run_id`, `ERR_CANDIDATE_NOT_FOUND` for `candidate_id`, `ERR_ASSIGNMENT_NOT_FOUND` for `assignment_id`, `ERR_ASSIGNMENT_LINE_NOT_FOUND` for `assignment_line_id`, `ERR_WINDOW_NOT_FOUND` for `window_id` and `ERR_NOTIFICATION_NOT_FOUND` for `notification_id`."

    Design: Corner/errors/unknown_child_ids_each_return_their_own_not_found_code
    """
    response = api.get_order_line(NON_EXISTENT_UUID, PLANNER)

    validate_error(response, "ERR_ORDER_LINE_NOT_FOUND")


def test_unknown_routing_run_id_returns_routing_run_not_found(api):
    """PRD §2.4: "Where a path does carry more than one identifier — a pickup being scheduled at a node, or a demand line being added to an order — the identifiers are resolved strictly left to right, and the first one that does not resolve determines the 404 that comes back."
    PRD §2.4: "The per-identifier codes are `ERR_STORE_NOT_FOUND` for `store_id`, `ERR_SKU_NOT_FOUND` for `sku_id`, `ERR_INVENTORY_NOT_FOUND` for `inventory_id`, `ERR_PACKAGING_NOT_FOUND` for `supply_id`, `ERR_PICKUP_NOT_FOUND` for `pickup_id` (and for a `carrier_pickup_id` supplied in a body), `ERR_ORDER_NOT_FOUND` for `order_id`, `ERR_ORDER_LINE_NOT_FOUND` for `order_line_id`, `ERR_ROUTING_RUN_NOT_FOUND` for `routing_run_id`, `ERR_CANDIDATE_NOT_FOUND` for `candidate_id`, `ERR_ASSIGNMENT_NOT_FOUND` for `assignment_id`, `ERR_ASSIGNMENT_LINE_NOT_FOUND` for `assignment_line_id`, `ERR_WINDOW_NOT_FOUND` for `window_id` and `ERR_NOTIFICATION_NOT_FOUND` for `notification_id`."

    Design: Corner/errors/unknown_child_ids_each_return_their_own_not_found_code
    """
    response = api.get_routing_run(NON_EXISTENT_UUID, PLANNER)

    validate_error(response, "ERR_ROUTING_RUN_NOT_FOUND")


def test_unknown_candidate_id_returns_candidate_not_found(api):
    """PRD §2.4: "Where a path does carry more than one identifier — a pickup being scheduled at a node, or a demand line being added to an order — the identifiers are resolved strictly left to right, and the first one that does not resolve determines the 404 that comes back."
    PRD §2.4: "The per-identifier codes are `ERR_STORE_NOT_FOUND` for `store_id`, `ERR_SKU_NOT_FOUND` for `sku_id`, `ERR_INVENTORY_NOT_FOUND` for `inventory_id`, `ERR_PACKAGING_NOT_FOUND` for `supply_id`, `ERR_PICKUP_NOT_FOUND` for `pickup_id` (and for a `carrier_pickup_id` supplied in a body), `ERR_ORDER_NOT_FOUND` for `order_id`, `ERR_ORDER_LINE_NOT_FOUND` for `order_line_id`, `ERR_ROUTING_RUN_NOT_FOUND` for `routing_run_id`, `ERR_CANDIDATE_NOT_FOUND` for `candidate_id`, `ERR_ASSIGNMENT_NOT_FOUND` for `assignment_id`, `ERR_ASSIGNMENT_LINE_NOT_FOUND` for `assignment_line_id`, `ERR_WINDOW_NOT_FOUND` for `window_id` and `ERR_NOTIFICATION_NOT_FOUND` for `notification_id`."

    Design: Corner/errors/unknown_child_ids_each_return_their_own_not_found_code
    """
    response = api.get_routing_candidate(NON_EXISTENT_UUID, PLANNER)

    validate_error(response, "ERR_CANDIDATE_NOT_FOUND")


def test_unknown_assignment_line_id_returns_assignment_line_not_found(api):
    """PRD §2.4: "Where a path does carry more than one identifier — a pickup being scheduled at a node, or a demand line being added to an order — the identifiers are resolved strictly left to right, and the first one that does not resolve determines the 404 that comes back."
    PRD §2.4: "The per-identifier codes are `ERR_STORE_NOT_FOUND` for `store_id`, `ERR_SKU_NOT_FOUND` for `sku_id`, `ERR_INVENTORY_NOT_FOUND` for `inventory_id`, `ERR_PACKAGING_NOT_FOUND` for `supply_id`, `ERR_PICKUP_NOT_FOUND` for `pickup_id` (and for a `carrier_pickup_id` supplied in a body), `ERR_ORDER_NOT_FOUND` for `order_id`, `ERR_ORDER_LINE_NOT_FOUND` for `order_line_id`, `ERR_ROUTING_RUN_NOT_FOUND` for `routing_run_id`, `ERR_CANDIDATE_NOT_FOUND` for `candidate_id`, `ERR_ASSIGNMENT_NOT_FOUND` for `assignment_id`, `ERR_ASSIGNMENT_LINE_NOT_FOUND` for `assignment_line_id`, `ERR_WINDOW_NOT_FOUND` for `window_id` and `ERR_NOTIFICATION_NOT_FOUND` for `notification_id`."

    Design: Corner/errors/unknown_child_ids_each_return_their_own_not_found_code
    """
    response = api.get_assignment_line(NON_EXISTENT_UUID, PLANNER)

    validate_error(response, "ERR_ASSIGNMENT_LINE_NOT_FOUND")


def test_unknown_window_id_returns_window_not_found(api):
    """PRD §2.4: "Where a path does carry more than one identifier — a pickup being scheduled at a node, or a demand line being added to an order — the identifiers are resolved strictly left to right, and the first one that does not resolve determines the 404 that comes back."
    PRD §2.4: "The per-identifier codes are `ERR_STORE_NOT_FOUND` for `store_id`, `ERR_SKU_NOT_FOUND` for `sku_id`, `ERR_INVENTORY_NOT_FOUND` for `inventory_id`, `ERR_PACKAGING_NOT_FOUND` for `supply_id`, `ERR_PICKUP_NOT_FOUND` for `pickup_id` (and for a `carrier_pickup_id` supplied in a body), `ERR_ORDER_NOT_FOUND` for `order_id`, `ERR_ORDER_LINE_NOT_FOUND` for `order_line_id`, `ERR_ROUTING_RUN_NOT_FOUND` for `routing_run_id`, `ERR_CANDIDATE_NOT_FOUND` for `candidate_id`, `ERR_ASSIGNMENT_NOT_FOUND` for `assignment_id`, `ERR_ASSIGNMENT_LINE_NOT_FOUND` for `assignment_line_id`, `ERR_WINDOW_NOT_FOUND` for `window_id` and `ERR_NOTIFICATION_NOT_FOUND` for `notification_id`."

    Design: Corner/errors/unknown_child_ids_each_return_their_own_not_found_code
    """
    response = api.get_performance_window(NON_EXISTENT_UUID, PLANNER)

    validate_error(response, "ERR_WINDOW_NOT_FOUND")


def test_unknown_notification_id_returns_notification_not_found(api):
    """PRD §2.4: "Where a path does carry more than one identifier — a pickup being scheduled at a node, or a demand line being added to an order — the identifiers are resolved strictly left to right, and the first one that does not resolve determines the 404 that comes back."
    PRD §2.4: "The per-identifier codes are `ERR_STORE_NOT_FOUND` for `store_id`, `ERR_SKU_NOT_FOUND` for `sku_id`, `ERR_INVENTORY_NOT_FOUND` for `inventory_id`, `ERR_PACKAGING_NOT_FOUND` for `supply_id`, `ERR_PICKUP_NOT_FOUND` for `pickup_id` (and for a `carrier_pickup_id` supplied in a body), `ERR_ORDER_NOT_FOUND` for `order_id`, `ERR_ORDER_LINE_NOT_FOUND` for `order_line_id`, `ERR_ROUTING_RUN_NOT_FOUND` for `routing_run_id`, `ERR_CANDIDATE_NOT_FOUND` for `candidate_id`, `ERR_ASSIGNMENT_NOT_FOUND` for `assignment_id`, `ERR_ASSIGNMENT_LINE_NOT_FOUND` for `assignment_line_id`, `ERR_WINDOW_NOT_FOUND` for `window_id` and `ERR_NOTIFICATION_NOT_FOUND` for `notification_id`."

    Design: Corner/errors/unknown_child_ids_each_return_their_own_not_found_code
    """
    response = api.get_notification(NON_EXISTENT_UUID, PLANNER)

    validate_error(response, "ERR_NOTIFICATION_NOT_FOUND")


# ======================================================================
# Duplicate natural keys, one code per row type
# ======================================================================


def _network_with_one_of_every_keyed_row():
    """One node, one SKU, one inventory row, one packaging row and one order,
    each carrying the natural key that the tests below re-post."""
    set_clock(CLOCK_OPEN)
    store = register_node("S1")
    sku = register_sku("SKU-A")
    inventory = stock_inventory(store["id"], sku["id"], 12, 2)
    supply = stock_packaging(store["id"], "MEDIUM_BOX", 4, 1)
    order = read_order(
        setup_order_with_lines(
            [],
            order_code="O-D001",
            customer_ref="C-900",
            destination_zone=4,
            service_level="GROUND",
            promised_ship_by_utc=PROMISED_SHIP_BY,
        )["order"]["id"]
    )
    return {
        "store": store,
        "sku": sku,
        "inventory": inventory,
        "supply": supply,
        "order": order,
    }


def test_duplicate_store_code_is_refused_and_the_stored_node_is_untouched(api):
    """PRD §3.1: "A `NetworkPlanner` registers a fulfillment node by supplying its `store_code` — a human-readable node code between 1 and 16 characters that must be unique across all nodes, with a duplicate rejected as `ERR_DUPLICATE_STORE_CODE` — its `region_code` for reporting, and its `origin_zone`, an integer from 1 to 8 giving the carrier origin zone used for transit and rate arithmetic."
    PRD §2.5: "Most resources — nodes, SKUs, inventory rows, packaging rows, carrier pickups, customer orders, demand lines, routing runs, fulfillment assignments and performance windows — additionally carry `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation, and `version`, an integer that starts at 1 on creation and increments by exactly 1 on every mutation of that row."
    PRD §2.3: "Every list response repeats `limit` and `offset` in the envelope's `meta` object alongside `total_count` (the number of rows matching the filters before pagination) and `has_more` (true when rows remain beyond the current page)."

    Design: Corner/errors/duplicate_natural_keys_are_rejected_per_row_type
    """
    net = _network_with_one_of_every_keyed_row()

    response = api.create_store(
        create_store_payload(
            "S1",
            region_code="EAST",
            origin_zone=2,
            daily_unit_capacity=55,
            staffed_labor_minutes=200,
            labor_standard_minutes_per_order=9,
            pick_labor_minutes_per_unit=2,
            labor_rate_cents_per_minute=31,
            cutoff_utc_minutes=960,
            hazmat_certified=True,
        ),
        PLANNER,
    )

    validate_error(response, "ERR_DUPLICATE_STORE_CODE")

    stored = read_store(net["store"]["id"])
    assert stored["region_code"] == "WEST", "the refused re-post must not rewrite region_code"
    assert stored["origin_zone"] == 4, "the refused re-post must not rewrite origin_zone"
    assert stored["daily_unit_capacity"] == 120, (
        "the refused re-post must not rewrite daily_unit_capacity"
    )
    assert stored["hazmat_certified"] is False, (
        "the refused re-post must not rewrite hazmat_certified"
    )
    assert stored["version"] == 1, "a refused duplicate mutates nothing, so version stays 1"

    rows, meta = validate_paginated(api.list_stores(PLANNER))
    assert meta["total_count"] == 1, "the duplicate store_code must not create a second node"
    assert meta["has_more"] is False, "one node fits on the first page"
    assert len(rows) == 1, "exactly one node exists"


def test_duplicate_sku_code_is_refused(api):
    """PRD §3.1: "A planner creates one with a `sku_code` unique across all SKUs (`ERR_DUPLICATE_SKU_CODE` otherwise), a `unit_weight_grams` of at least 1 gram used for shipping weight, a `unit_price_cents` of at least 0 as list price, a `package_class` of `SMALL`, `MEDIUM` or `LARGE` naming the smallest package family that can hold one unit, and an optional `hazmat_flag` defaulting to false."
    PRD §2.3: "Every list response repeats `limit` and `offset` in the envelope's `meta` object alongside `total_count` (the number of rows matching the filters before pagination) and `has_more` (true when rows remain beyond the current page)."

    Design: Corner/errors/duplicate_natural_keys_are_rejected_per_row_type
    """
    net = _network_with_one_of_every_keyed_row()

    response = api.create_sku(
        create_sku_payload(
            "SKU-A", unit_weight_grams=250, unit_price_cents=1900, package_class="SMALL"
        ),
        PLANNER,
    )

    validate_error(response, "ERR_DUPLICATE_SKU_CODE")

    stored = validate_success(api.get_sku(net["sku"]["id"], PLANNER))
    assert stored["unit_weight_grams"] == 800, "the stored SKU keeps its own weight"
    assert stored["package_class"] == "MEDIUM", "the stored SKU keeps its own package_class"
    assert stored["version"] == 1, "a refused duplicate mutates nothing, so version stays 1"

    _rows, meta = validate_paginated(api.list_skus(PLANNER))
    assert meta["total_count"] == 1, "the duplicate sku_code must not create a second SKU"


def test_duplicate_order_code_is_refused_and_creates_no_second_order(api):
    """PRD §3.2: "A `CustomerCare` agent takes an order with an `order_code` unique across all orders (`ERR_DUPLICATE_ORDER_CODE` otherwise), a `customer_ref` opaque handle used on customer notifications, a `destination_zone` from 1 to 8 giving the carrier destination zone of the ship-to address, a `service_level` of either `GROUND` or `EXPEDITED`, and a `promised_ship_by_utc` instant echoed onto notifications."
    PRD §2.3: "Every list response repeats `limit` and `offset` in the envelope's `meta` object alongside `total_count` (the number of rows matching the filters before pagination) and `has_more` (true when rows remain beyond the current page)."

    Design: Corner/errors/duplicate_natural_keys_are_rejected_per_row_type
    """
    net = _network_with_one_of_every_keyed_row()

    response = api.create_order(
        create_order_payload(
            order_code="O-D001",
            customer_ref="C-901",
            destination_zone=2,
            service_level="EXPEDITED",
            promised_ship_by_utc="2026-08-05T15:00:00Z",
        ),
        CARE,
    )

    validate_error(response, "ERR_DUPLICATE_ORDER_CODE")

    rows, meta = validate_paginated(api.list_orders(CARE))
    assert meta["total_count"] == 1, "the duplicate order_code must not create a second order"
    survivor = read_order(net["order"]["id"])
    assert survivor["service_level"] == "GROUND", (
        "the surviving order keeps its own service_level"
    )
    assert survivor["destination_zone"] == 4, (
        "the surviving order keeps its own destination_zone"
    )
    assert len(rows) == 1, "exactly one order exists"


def test_duplicate_inventory_row_for_the_same_node_and_sku_is_refused(api):
    """PRD §3.1: "At most one inventory row may exist per node-and-SKU pairing; a second attempt is rejected with `ERR_DUPLICATE_INVENTORY_ROW`."
    PRD §3.1: "Creation sets `reserved_units` to 0, leaves `last_adjustment_reason` null, and derives `available_to_promise_units` as the larger of 0 and the result of taking `on_hand_units`, subtracting `reserved_units`, then subtracting `safety_stock_units`."
    PRD §2.5: "Most resources — nodes, SKUs, inventory rows, packaging rows, carrier pickups, customer orders, demand lines, routing runs, fulfillment assignments and performance windows — additionally carry `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation, and `version`, an integer that starts at 1 on creation and increments by exactly 1 on every mutation of that row."

    Design: Corner/errors/duplicate_natural_keys_are_rejected_per_row_type
    """
    net = _network_with_one_of_every_keyed_row()

    response = api.create_store_inventory(
        create_store_inventory_payload(
            net["store"]["id"], net["sku"]["id"], on_hand_units=99, safety_stock_units=0
        ),
        PLANNER,
    )

    validate_error(response, "ERR_DUPLICATE_INVENTORY_ROW")

    stored = read_inventory(net["inventory"]["id"])
    assert stored["on_hand_units"] == 12, "the refused duplicate must not overwrite on_hand_units"
    assert stored["safety_stock_units"] == 2, (
        "the refused duplicate must not overwrite safety_stock_units"
    )
    assert stored["available_to_promise_units"] == 10, (
        "available_to_promise_units stays max(0, 12 - 0 - 2) = 10"
    )
    assert stored["version"] == 1, "a refused duplicate mutates nothing, so version stays 1"


def test_duplicate_packaging_row_for_the_same_node_and_package_type_is_refused(api):
    """PRD §3.1: "Only one row may exist per node-and-package-type pairing, with `ERR_DUPLICATE_PACKAGING_ROW` for a second attempt."
    PRD §3.1: "Creation sets `lifetime_consumed_units` to 0 and derives `reorder_flag` as true exactly when `on_hand_units` is less than or equal to `reorder_point_units`."
    PRD §2.5: "Most resources — nodes, SKUs, inventory rows, packaging rows, carrier pickups, customer orders, demand lines, routing runs, fulfillment assignments and performance windows — additionally carry `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation, and `version`, an integer that starts at 1 on creation and increments by exactly 1 on every mutation of that row."

    Design: Corner/errors/duplicate_natural_keys_are_rejected_per_row_type
    """
    net = _network_with_one_of_every_keyed_row()

    response = api.create_packaging_supply(
        create_packaging_supply_payload(
            net["store"]["id"], "MEDIUM_BOX", on_hand_units=99, reorder_point_units=50
        ),
        PLANNER,
    )

    validate_error(response, "ERR_DUPLICATE_PACKAGING_ROW")

    stored = read_packaging(net["supply"]["id"])
    assert stored["on_hand_units"] == 4, "the refused duplicate must not overwrite on_hand_units"
    assert stored["reorder_point_units"] == 1, (
        "the refused duplicate must not overwrite reorder_point_units"
    )
    assert stored["reorder_flag"] is False, "4 on hand is above the reorder point of 1"
    assert stored["version"] == 1, "a refused duplicate mutates nothing, so version stays 1"


# ======================================================================
# Malformed pick and pack payloads on one ACCEPTED assignment
# ======================================================================


def _accepted_assignment_beside_a_foreign_assignment():
    """S1 stocks two SKUs and both a MEDIUM_BOX and a SMALL_BOX row. Two orders
    are committed to it; the first assignment is accepted, and the second one's
    assignment line is the foreign line used by the mismatch probe."""
    set_clock(CLOCK_OPEN)
    store = register_node("S1")
    sku_a = register_sku("SKU-A")
    sku_b = register_sku("SKU-B")
    stock_inventory(store["id"], sku_a["id"], 12, 2)
    stock_inventory(store["id"], sku_b["id"], 6, 1)
    supply_medium = stock_packaging(store["id"], "MEDIUM_BOX", 4, 1)
    supply_small = stock_packaging(store["id"], "SMALL_BOX", 3, 1)

    first_order = _commit_one_line_order(sku_a, "O-E001", "C-910", quantity=2)
    first = find_assignment(order_id=first_order["id"], store_id=store["id"])
    first_line = find_assignment_lines(first["id"])[0]

    second_order = _commit_one_line_order(
        sku_b, "O-E002", "C-911", quantity=1, unit_price_cents=1900
    )
    second = find_assignment(order_id=second_order["id"], store_id=store["id"])
    second_line = find_assignment_lines(second["id"])[0]

    accept(first["id"], store["id"])

    return {
        "store": store,
        "supply_medium": supply_medium,
        "supply_small": supply_small,
        "assignment": read_assignment(first["id"]),
        "line": first_line,
        "foreign_line": second_line,
    }


def _assert_pick_refusal_was_inert(ctx):
    """A refused pick leaves the assignment where accept left it."""
    after = read_assignment(ctx["assignment"]["id"])
    assert after["status"] == "ACCEPTED", "a refused pick must not move the assignment"
    assert after["picked_units"] == 0, "a refused pick must not store picked_units"
    assert after["version"] == 2, (
        "creation wrote version 1 and the accept wrote version 2; a refused pick adds nothing"
    )
    assert read_assignment_line(ctx["line"]["id"])["units_picked"] == 0, (
        "a refused pick must not move the assignment line's units_picked"
    )


def test_zero_pick_is_refused_with_its_own_code(api):
    """PRD §3.5: "A `picked_units` of 0 is never acceptable: the associate must reject the task instead so the failure is attributed to the node, and a zero pick is refused with `ERR_ZERO_PICK_NOT_ALLOWED`."
    PRD §2.5: "Most resources — nodes, SKUs, inventory rows, packaging rows, carrier pickups, customer orders, demand lines, routing runs, fulfillment assignments and performance windows — additionally carry `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation, and `version`, an integer that starts at 1 on creation and increments by exactly 1 on every mutation of that row."

    Design: Corner/errors/zero_over_and_foreign_line_picks_are_rejected_before_a_clean_pick_succeeds
    """
    ctx = _accepted_assignment_beside_a_foreign_assignment()

    response = api.pick_assignment(
        ctx["assignment"]["id"],
        pick_payload(0, [line_pick(ctx["line"]["id"], 0)]),
        make_store_associate_headers(ctx["store"]["id"]),
    )

    validate_error(response, "ERR_ZERO_PICK_NOT_ALLOWED")
    _assert_pick_refusal_was_inert(ctx)


def test_pick_above_assigned_units_is_refused_as_invalid_arithmetic(api):
    """PRD §3.5: "The arithmetic must hold: `picked_units` may not exceed `assigned_units`, no entry's `units_picked` may exceed its line's `units_assigned`, no line may be named more than once, and the entries' `units_picked` must sum to exactly `picked_units` — any violation is `ERR_PICK_UNITS_INVALID`."
    PRD §2.5: "Most resources — nodes, SKUs, inventory rows, packaging rows, carrier pickups, customer orders, demand lines, routing runs, fulfillment assignments and performance windows — additionally carry `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation, and `version`, an integer that starts at 1 on creation and increments by exactly 1 on every mutation of that row."

    Design: Corner/errors/zero_over_and_foreign_line_picks_are_rejected_before_a_clean_pick_succeeds
    """
    ctx = _accepted_assignment_beside_a_foreign_assignment()

    response = api.pick_assignment(
        ctx["assignment"]["id"],
        pick_payload(3, [line_pick(ctx["line"]["id"], 3)]),
        make_store_associate_headers(ctx["store"]["id"]),
    )

    validate_error(response, "ERR_PICK_UNITS_INVALID")
    _assert_pick_refusal_was_inert(ctx)


def test_line_picks_that_do_not_sum_to_picked_units_are_refused(api):
    """PRD §3.5: "The arithmetic must hold: `picked_units` may not exceed `assigned_units`, no entry's `units_picked` may exceed its line's `units_assigned`, no line may be named more than once, and the entries' `units_picked` must sum to exactly `picked_units` — any violation is `ERR_PICK_UNITS_INVALID`."
    PRD §2.5: "Most resources — nodes, SKUs, inventory rows, packaging rows, carrier pickups, customer orders, demand lines, routing runs, fulfillment assignments and performance windows — additionally carry `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation, and `version`, an integer that starts at 1 on creation and increments by exactly 1 on every mutation of that row."

    Design: Corner/errors/zero_over_and_foreign_line_picks_are_rejected_before_a_clean_pick_succeeds
    """
    ctx = _accepted_assignment_beside_a_foreign_assignment()

    response = api.pick_assignment(
        ctx["assignment"]["id"],
        pick_payload(2, [line_pick(ctx["line"]["id"], 1)]),
        make_store_associate_headers(ctx["store"]["id"]),
    )

    validate_error(response, "ERR_PICK_UNITS_INVALID")
    _assert_pick_refusal_was_inert(ctx)


def test_unresolvable_assignment_line_id_in_a_pick_is_a_404_not_a_mismatch(api):
    """PRD §2.4: "Foreign keys supplied in a request body resolve under the same codes: a `store_id` or `sku_id` on an inventory row, a `store_id` on a packaging row, a `sku_id` on a demand line, an `assignment_line_id` inside a pick payload, or a `carrier_pickup_id` on a ship request."
    PRD §2.4: "The per-identifier codes are `ERR_STORE_NOT_FOUND` for `store_id`, `ERR_SKU_NOT_FOUND` for `sku_id`, `ERR_INVENTORY_NOT_FOUND` for `inventory_id`, `ERR_PACKAGING_NOT_FOUND` for `supply_id`, `ERR_PICKUP_NOT_FOUND` for `pickup_id` (and for a `carrier_pickup_id` supplied in a body), `ERR_ORDER_NOT_FOUND` for `order_id`, `ERR_ORDER_LINE_NOT_FOUND` for `order_line_id`, `ERR_ROUTING_RUN_NOT_FOUND` for `routing_run_id`, `ERR_CANDIDATE_NOT_FOUND` for `candidate_id`, `ERR_ASSIGNMENT_NOT_FOUND` for `assignment_id`, `ERR_ASSIGNMENT_LINE_NOT_FOUND` for `assignment_line_id`, `ERR_WINDOW_NOT_FOUND` for `window_id` and `ERR_NOTIFICATION_NOT_FOUND` for `notification_id`."
    PRD §2.11: "Existence third: path identifiers left to right, then foreign keys supplied in the body."
    PRD §2.11: "Referential coupling tenth: whether a pickup belongs to the assignment's node, whether a pick line belongs to the assignment, whether a pickup is empty enough to cancel."

    The pick names the assignment's own line with a legal count, so only the
    unresolvable second entry can be refused.

    Design: Corner/errors/zero_over_and_foreign_line_picks_are_rejected_before_a_clean_pick_succeeds
    """
    ctx = _accepted_assignment_beside_a_foreign_assignment()

    response = api.pick_assignment(
        ctx["assignment"]["id"],
        pick_payload(
            2, [line_pick(ctx["line"]["id"], 1), line_pick(NON_EXISTENT_UUID, 1)]
        ),
        make_store_associate_headers(ctx["store"]["id"]),
    )

    validate_error(response, "ERR_ASSIGNMENT_LINE_NOT_FOUND")
    _assert_pick_refusal_was_inert(ctx)


def test_pick_line_belonging_to_another_assignment_is_refused_as_mismatch(api):
    """PRD §3.5: "Every `assignment_line_id` must belong to the assignment being picked, or the request is refused with `ERR_ASSIGNMENT_LINE_MISMATCH`."
    PRD §3.5: "The arithmetic must hold: `picked_units` may not exceed `assigned_units`, no entry's `units_picked` may exceed its line's `units_assigned`, no line may be named more than once, and the entries' `units_picked` must sum to exactly `picked_units` — any violation is `ERR_PICK_UNITS_INVALID`."

    The payload is arithmetically clean — 2 picked units against 2 assigned, the
    entries summing to exactly 2, the assignment's own line named once — so the
    only defect left is the entry that resolves to the other assignment's line.

    Design: Corner/errors/zero_over_and_foreign_line_picks_are_rejected_before_a_clean_pick_succeeds
    """
    ctx = _accepted_assignment_beside_a_foreign_assignment()

    response = api.pick_assignment(
        ctx["assignment"]["id"],
        pick_payload(
            2,
            [line_pick(ctx["line"]["id"], 1), line_pick(ctx["foreign_line"]["id"], 1)],
        ),
        make_store_associate_headers(ctx["store"]["id"]),
    )

    validate_error(response, "ERR_ASSIGNMENT_LINE_MISMATCH")
    _assert_pick_refusal_was_inert(ctx)


def test_corrected_pick_succeeds_after_a_refused_zero_pick(api):
    """PRD §3.5: "A `picked_units` of 0 is never acceptable: the associate must reject the task instead so the failure is attributed to the node, and a zero pick is refused with `ERR_ZERO_PICK_NOT_ALLOWED`."
    PRD §3.5: "When `picked_units` equals `assigned_units` the assignment moves `ACCEPTED → PICKED`: `picked_at` is set to the clock instant, `picked_units` is stored, `shortfall_units` stays 0, each line's `units_picked` is set from `line_picks`, and `billable_weight_grams` is recomputed from the picked units."
    PRD §2.5: "Most resources — nodes, SKUs, inventory rows, packaging rows, carrier pickups, customer orders, demand lines, routing runs, fulfillment assignments and performance windows — additionally carry `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation, and `version`, an integer that starts at 1 on creation and increments by exactly 1 on every mutation of that row."

    Design: Corner/errors/zero_over_and_foreign_line_picks_are_rejected_before_a_clean_pick_succeeds
    """
    ctx = _accepted_assignment_beside_a_foreign_assignment()
    headers = make_store_associate_headers(ctx["store"]["id"])

    refused = api.pick_assignment(
        ctx["assignment"]["id"],
        pick_payload(0, [line_pick(ctx["line"]["id"], 0)]),
        headers,
    )
    validate_error(refused, "ERR_ZERO_PICK_NOT_ALLOWED")

    corrected = api.pick_assignment(
        ctx["assignment"]["id"],
        pick_payload(2, [line_pick(ctx["line"]["id"], 2)]),
        headers,
    )

    picked = validate_success(corrected)
    assert picked["status"] == "PICKED", "a full pick moves ACCEPTED → PICKED"
    assert picked["picked_units"] == 2, "picked_units is stored from the payload"
    assert picked["shortfall_units"] == 0, "a full pick leaves shortfall_units at 0"
    assert picked["version"] == 3, (
        "version 1 at creation, 2 at accept, 3 at pick — the refused pick added nothing"
    )
    assert read_assignment_line(ctx["line"]["id"])["units_picked"] == 2, (
        "the line's units_picked is set from line_picks"
    )


def test_pack_below_the_derived_package_rank_is_refused_on_rank(api):
    """PRD §3.5: "The chosen package must also be big enough: package ranks run `POLY_MAILER` at 1, `SMALL_BOX` at 2, `MEDIUM_BOX` at 3 and `LARGE_BOX` at 4, and the chosen `package_type`'s rank must be greater than or equal to the rank of the assignment's `derived_package_type`, otherwise `ERR_PACKAGE_TYPE_TOO_SMALL`."
    PRD §3.5: "`derived_package_type` is the package the provisional cost assumes: take the heaviest `package_class` among the allocation's SKUs by package rank and map it, so `SMALL` becomes `SMALL_BOX`, `MEDIUM` becomes `MEDIUM_BOX` and `LARGE` becomes `LARGE_BOX`."
    PRD §3.5: "A packaging row must exist at that node for the chosen `package_type` with `on_hand_units` of at least 1, or the request is refused with `ERR_PACKAGING_DEPLETED`."
    PRD §3.1: "Creation sets `lifetime_consumed_units` to 0 and derives `reorder_flag` as true exactly when `on_hand_units` is less than or equal to `reorder_point_units`."

    Design: Corner/errors/zero_over_and_foreign_line_picks_are_rejected_before_a_clean_pick_succeeds
    """
    ctx = _accepted_assignment_beside_a_foreign_assignment()
    pick_full(ctx["assignment"]["id"], ctx["store"]["id"])

    assignment = read_assignment(ctx["assignment"]["id"])
    assert assignment["derived_package_type"] == "MEDIUM_BOX", (
        "the allocation's only package_class is MEDIUM, which maps to MEDIUM_BOX"
    )

    response = api.pack_assignment(
        ctx["assignment"]["id"],
        {"package_type": "SMALL_BOX"},
        make_store_associate_headers(ctx["store"]["id"]),
    )

    validate_error(response, "ERR_PACKAGE_TYPE_TOO_SMALL")

    after = read_assignment(ctx["assignment"]["id"])
    assert after["status"] == "PICKED", "a refused pack must not move the assignment"
    assert after["package_type"] is None, "a refused pack must not store package_type"

    supply = read_packaging(ctx["supply_small"]["id"])
    assert supply["on_hand_units"] == 3, (
        "the SMALL_BOX row was stocked, so the refusal is about rank and not depletion"
    )
    assert supply["lifetime_consumed_units"] == 0, "a refused pack consumes nothing"
    assert supply["version"] == 1, "a refused pack does not mutate the packaging row"


def test_pack_at_the_derived_package_type_consumes_exactly_one_unit(api):
    """PRD §3.5: "On success `packed_at` is set to the clock instant, `package_type` is stored, and `labor_minutes_actual` is computed as the elapsed time from `accepted_at` to `packed_at` expressed in whole minutes with any remaining seconds discarded."
    PRD §3.5: "The packaging row's `on_hand_units` is decremented by 1, its `lifetime_consumed_units` is incremented by 1, and its `reorder_flag` is re-derived."
    PRD §3.1: "Creation sets `lifetime_consumed_units` to 0 and derives `reorder_flag` as true exactly when `on_hand_units` is less than or equal to `reorder_point_units`."
    PRD §2.5: "Most resources — nodes, SKUs, inventory rows, packaging rows, carrier pickups, customer orders, demand lines, routing runs, fulfillment assignments and performance windows — additionally carry `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation, and `version`, an integer that starts at 1 on creation and increments by exactly 1 on every mutation of that row."

    Design: Corner/errors/zero_over_and_foreign_line_picks_are_rejected_before_a_clean_pick_succeeds
    """
    ctx = _accepted_assignment_beside_a_foreign_assignment()
    pick_full(ctx["assignment"]["id"], ctx["store"]["id"])

    response = api.pack_assignment(
        ctx["assignment"]["id"],
        {"package_type": "MEDIUM_BOX"},
        make_store_associate_headers(ctx["store"]["id"]),
    )

    packed = validate_success(response)
    assert packed["status"] == "PACKED", "packing moves PICKED → PACKED"
    assert packed["package_type"] == "MEDIUM_BOX", "the recorded package_type is stored"
    assert packed["version"] == 4, (
        "version 1 at creation, 2 at accept, 3 at pick, 4 at pack"
    )
    assert packed["labor_minutes_actual"] == 0, (
        "the clock never advanced past accepted_at, so no whole minute elapsed"
    )

    supply = read_packaging(ctx["supply_medium"]["id"])
    assert supply["on_hand_units"] == 3, "the pack consumed exactly one of the four boxes"
    assert supply["lifetime_consumed_units"] == 1, "lifetime_consumed_units rises by 1"
    assert supply["reorder_flag"] is False, "3 on hand is still above the reorder point of 1"
    assert supply["version"] == 2, "the packaging row was mutated exactly once"


# ======================================================================
# The pick deadline is an exclusive bound
# ======================================================================


def _two_assignments_minted_at_nine():
    """Node S1 holds two committed two-unit assignments, both created at 09:00Z."""
    set_clock(CLOCK_OPEN)
    store = register_node("S1")
    sku = register_sku("SKU-A")
    stock_inventory(store["id"], sku["id"], 12, 2)

    first_order = _commit_one_line_order(sku, "O-F001", "C-920")
    first = find_assignment(order_id=first_order["id"], store_id=store["id"])
    second_order = _commit_one_line_order(sku, "O-F002", "C-921")
    second = find_assignment(order_id=second_order["id"], store_id=store["id"])

    return {"store": store, "sku": sku, "first": first, "second": second}


def test_pick_deadline_is_the_earlier_of_the_four_hour_bound_and_the_cutoff_instant():
    """PRD §3.5: "And `pick_deadline_utc` is the earlier of two instants: four hours after the assignment's `created_at`, and the instant on the creation date's UTC calendar day that falls `cutoff_utc_minutes` minutes after midnight UTC."

    Design: Corner/errors/accept_is_refused_at_the_pick_deadline_instant_and_allowed_one_second_before
    """
    ctx = _two_assignments_minted_at_nine()

    for label, assignment in (("first", ctx["first"]), ("second", ctx["second"])):
        assert _instant(assignment["pick_deadline_utc"]) == _instant(PICK_DEADLINE), (
            f"the {label} assignment was created at 09:00:00Z, so its deadline is the "
            f"13:00:00Z four-hour bound rather than the 17:00:00Z cutoff instant, got "
            f"{assignment['pick_deadline_utc']}"
        )


def test_accept_one_second_before_the_pick_deadline_succeeds(api):
    """PRD §3.5: "Acceptance requires, in this order, the acting associate's node to match the assignment's node, the assignment to be at `ASSIGNED`, the owning order's `fulfillment_status` to be anything other than `CANCELLED`, the node's `node_status` to be `ELIGIBLE` or `PROBATION`, the node to have a performance window at `status` `OPEN` (else `ERR_NO_OPEN_WINDOW`), the clock's minute-of-day to be within the node's cutoff, the clock to be strictly before `pick_deadline_utc` (at or after it, the request is refused with `ERR_PICK_DEADLINE_PASSED`), and finally the node's concurrent pick labour to stay within its cap."
    PRD §3.5: "A `StoreAssociate` takes ownership of the task by accepting it, moving `ASSIGNED → ACCEPTED` and setting `accepted_at` to the clock instant."
    PRD §2.5: "Most resources — nodes, SKUs, inventory rows, packaging rows, carrier pickups, customer orders, demand lines, routing runs, fulfillment assignments and performance windows — additionally carry `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation, and `version`, an integer that starts at 1 on creation and increments by exactly 1 on every mutation of that row."

    Design: Corner/errors/accept_is_refused_at_the_pick_deadline_instant_and_allowed_one_second_before
    """
    ctx = _two_assignments_minted_at_nine()
    set_clock(CLOCK_ONE_SECOND_BEFORE_DEADLINE)

    response = api.accept_assignment(
        ctx["first"]["id"], make_store_associate_headers(ctx["store"]["id"])
    )

    accepted = validate_success(response)
    assert accepted["status"] == "ACCEPTED", (
        "one second before the deadline the clock is still strictly before it"
    )
    assert _instant(accepted["accepted_at"]) == _instant(CLOCK_ONE_SECOND_BEFORE_DEADLINE), (
        "accepted_at is the clock instant"
    )
    assert accepted["version"] == 2, "the accept is the row's first mutation after creation"


def test_accept_at_the_pick_deadline_instant_is_refused(api):
    """PRD §3.5: "Acceptance requires, in this order, the acting associate's node to match the assignment's node, the assignment to be at `ASSIGNED`, the owning order's `fulfillment_status` to be anything other than `CANCELLED`, the node's `node_status` to be `ELIGIBLE` or `PROBATION`, the node to have a performance window at `status` `OPEN` (else `ERR_NO_OPEN_WINDOW`), the clock's minute-of-day to be within the node's cutoff, the clock to be strictly before `pick_deadline_utc` (at or after it, the request is refused with `ERR_PICK_DEADLINE_PASSED`), and finally the node's concurrent pick labour to stay within its cap."
    PRD §2.6: "In-store work — accepting, picking, packing and shipping — is permitted only while the clock's minute-of-day, taken as the whole number of minutes elapsed since midnight UTC with any seconds discarded, is less than or equal to that node's `cutoff_utc_minutes`."
    PRD §3.5: "`picked_units` and `shortfall_units` both start at 0; `labor_minutes_actual`, `package_type`, `final_cost_cents`, `cycle_time_minutes`, `accepted_at`, `picked_at`, `packed_at`, `shipped_at`, `reject_reason_code` and `cancel_reason_code` all start null."
    PRD §2.9: "A node's `reserved_labor_minutes` equals the sum of `labor_minutes_reserved` over that node's assignments whose `status` is one of `ASSIGNED`, `ACCEPTED`, `PICKED`, `SHORT_PICKED` or `PACKED`."
    PRD §3.5: "`labor_minutes_reserved` is the node's `labor_standard_minutes_per_order` plus its `pick_labor_minutes_per_unit` multiplied by `assigned_units` — the labour standard, committed once and never rewritten."

    The node's 17:00Z cutoff is still hours away at 13:00Z, so the cutoff gate
    is satisfied and the deadline gate is the only one that can refuse.

    Design: Corner/errors/accept_is_refused_at_the_pick_deadline_instant_and_allowed_one_second_before
    """
    ctx = _two_assignments_minted_at_nine()
    set_clock(CLOCK_ONE_SECOND_BEFORE_DEADLINE)
    accept(ctx["first"]["id"], ctx["store"]["id"])
    set_clock(CLOCK_AT_DEADLINE)

    response = api.accept_assignment(
        ctx["second"]["id"], make_store_associate_headers(ctx["store"]["id"])
    )

    validate_error(response, "ERR_PICK_DEADLINE_PASSED")

    refused = read_assignment(ctx["second"]["id"])
    assert refused["status"] == "ASSIGNED", "the refused accept leaves the assignment at ASSIGNED"
    assert refused["accepted_at"] is None, "the refused accept writes no accepted_at"
    assert refused["version"] == 1, "the refused accept mutates nothing"

    store = read_store(ctx["store"]["id"])
    assert store["reserved_labor_minutes"] == pytest.approx(36, abs=0.01), (
        "each of the two live assignments reserved 12 + 3 x 2 = 18 minutes at commit "
        "time; accepting reserves nothing further and the refusal reserves nothing"
    )


# ======================================================================
# Node posture: deactivation and reactivation are exact mirrors
# ======================================================================


def _commit_then_cancel_one_order(sku, order_code, customer_ref):
    """A two-unit order committed to the node and then cancelled by the customer,
    which is what makes the epoch's window breach on cancellation rate."""
    order = _commit_one_line_order(sku, order_code, customer_ref)
    cancel_order(order["id"])
    return order


def _node_after_one_breached_epoch():
    """S1 is the only node. Its epoch-1 window holds one cancelled assignment,
    and the ops-run then closes that epoch."""
    set_clock(CLOCK_OPEN)
    store = register_node("S1")
    sku = register_sku("SKU-A")
    inventory = stock_inventory(store["id"], sku["id"], 12, 2)
    _commit_then_cancel_one_order(sku, "O-G001", "C-930")
    first_closed = close_windows()
    return {
        "store": store,
        "sku": sku,
        "inventory": inventory,
        "first_closed": first_closed,
    }


def _node_after_two_breached_epochs():
    """The epoch-1 breach is repeated in epoch 2, which is the second
    consecutive breached window."""
    ctx = _node_after_one_breached_epoch()
    _commit_then_cancel_one_order(ctx["sku"], "O-G002", "C-931")
    ctx["second_closed"] = close_windows()
    return ctx


def test_first_breached_window_puts_the_node_on_probation():
    """PRD §3.9: "`cancellation_rate` is exactly 0.0000 when `assignments_created` is 0, and otherwise `assignments_rejected` plus `assignments_cancelled`, divided by `assignments_created`, rounded half-up to four decimal places."
    PRD §3.9: "`breach_flags` is then built as a subset of three markers appended in this fixed order: `FILL_RATE` when `assignments_shipped` is at least 1 and `fill_rate` is strictly below 0.9000; `CYCLE_TIME` when `assignments_shipped` is at least 1 and `avg_cycle_time_minutes` is strictly greater than four hours; and `CANCELLATION_RATE` when `assignments_created` is at least 1 and `cancellation_rate` is strictly greater than 0.0500."
    PRD §3.9: "A `PROBATION` action moves the node `ELIGIBLE → PROBATION` and sets `consecutive_breach_windows` to 1."

    Design: Corner/errors/two_breached_windows_deactivate_the_node_and_only_a_deactivated_node_reactivates
    """
    ctx = _node_after_one_breached_epoch()

    assert len(ctx["first_closed"]) == 1, "the only node's only open window was closed"
    window = ctx["first_closed"][0]
    assert window["epoch"] == 1, "registration opened the node's first window at epoch 1"
    assert window["assignments_created"] == 1, "one assignment was stamped with epoch 1"
    assert window["assignments_cancelled"] == 1, "the order cancel cancelled that assignment"
    assert window["cancellation_rate"] == pytest.approx(1.0, abs=0.01), (
        "one cancellation over one created assignment is a rate of 1.0000"
    )
    assert window["breach_flags"] == ["CANCELLATION_RATE"], (
        "no FILL_RATE or CYCLE_TIME marker is appended because assignments_shipped is 0"
    )
    assert window["breached"] is True, "a non-empty breach_flags list means breached"
    assert window["node_action"] == "PROBATION", (
        "a first breach at an ELIGIBLE node is a PROBATION action"
    )

    store = read_store(ctx["store"]["id"])
    assert store["node_status"] == "PROBATION", "the PROBATION action moves the posture"
    assert store["consecutive_breach_windows"] == 1, (
        "the PROBATION action sets consecutive_breach_windows to 1"
    )


def test_second_consecutive_breached_window_deactivates_the_node_without_a_successor():
    """PRD §3.9: "Otherwise it is `DEACTIVATION` when the window is breached and the node's `consecutive_breach_windows` plus 1 reaches 2; `PROBATION` when the window is breached, the node's `node_status` is `ELIGIBLE`, and `consecutive_breach_windows` plus 1 is still below 2; `RECOVERY` when the window is not breached and the node's `node_status` is `PROBATION`; and `NONE` in every other case."
    PRD §3.9: "A `DEACTIVATION` action moves the node `PROBATION → DEACTIVATED` on a second consecutive breached window, sets `node_status` to `DEACTIVATED` and records `deactivated_at_epoch` as the closing window's `epoch`."
    PRD §3.9: "A new performance window at `status` `OPEN` and at the previous `epoch` plus 1 is created for every node whose `node_status` is `ELIGIBLE` or `PROBATION`, with `opened_at_utc` at the clock instant and `closed_at_utc` null. Deactivated nodes get none."
    PRD §3.1: "Registration seeds the node's derived state: `node_status` becomes `ELIGIBLE`, `units_committed_epoch` and `reserved_labor_minutes` are 0, `consecutive_breach_windows` is 0, `reactivation_count` is 0, `deactivated_at_epoch` is null, and `review_score` is 0."

    Design: Corner/errors/two_breached_windows_deactivate_the_node_and_only_a_deactivated_node_reactivates
    """
    ctx = _node_after_two_breached_epochs()

    assert len(ctx["second_closed"]) == 1, "the second ops-run closed exactly one window"
    window = ctx["second_closed"][0]
    assert window["epoch"] == 2, "the successor window opened at epoch 2"
    assert window["breached"] is True, "the epoch-2 window breached on cancellation rate too"
    assert window["node_action"] == "DEACTIVATION", (
        "consecutive_breach_windows 1 plus 1 reaches 2, so the PROBATION branch is unreachable"
    )

    store = read_store(ctx["store"]["id"])
    assert store["node_status"] == "DEACTIVATED", "the DEACTIVATION action deactivates the node"
    assert store["deactivated_at_epoch"] == 2, (
        "deactivated_at_epoch records the closing window's epoch"
    )
    assert store["consecutive_breach_windows"] == 2, "the second breach increments the counter"
    assert store["reactivation_count"] == 0, "no human has reactivated the node yet"

    assert find_windows(store_id=ctx["store"]["id"], status="OPEN") == [], (
        "a deactivated node gets no successor window"
    )


def test_scheduling_a_pickup_at_a_deactivated_node_is_refused(api):
    """PRD §2.10: "`ELIGIBLE` and `PROBATION` nodes are routable and may do in-store work; a `DEACTIVATED` node may do neither, and any attempt to accept, pick, pack or ship at it, or to schedule a carrier pickup for it, is rejected with `ERR_STORE_NODE_DEACTIVATED` (HTTP 409)."
    PRD §3.6: "Scheduling is refused at a node whose `node_status` is `DEACTIVATED`."

    Design: Corner/errors/two_breached_windows_deactivate_the_node_and_only_a_deactivated_node_reactivates
    """
    ctx = _node_after_two_breached_epochs()
    assert read_store(ctx["store"]["id"])["node_status"] == "DEACTIVATED", (
        "precondition: two consecutive breached windows deactivated the node"
    )

    response = api.create_carrier_pickup(
        ctx["store"]["id"],
        {
            "carrier_code": "UPS",
            "window_start_utc": "2026-08-03T15:00:00Z",
            "window_end_utc": "2026-08-03T16:00:00Z",
            "parcel_capacity": 5,
        },
        CARRIER,
    )

    validate_error(response, "ERR_STORE_NODE_DEACTIVATED")

    rows, meta = validate_paginated(
        api.list_carrier_pickups(PLANNER, params={"store_id": ctx["store"]["id"]})
    )
    assert meta["total_count"] == 0, "the refused scheduling creates no CarrierPickup row"
    assert rows == [], "the refused scheduling creates no CarrierPickup row"


def test_reactivating_a_deactivated_node_restores_it_and_opens_a_fresh_epoch(api):
    """PRD §3.9: "A `NetworkPlanner` returns a node from `DEACTIVATED → ELIGIBLE`; a node whose `node_status` is not `DEACTIVATED` is refused with `ERR_STORE_NOT_DEACTIVATED`."
    PRD §3.9: "Reactivation sets `node_status` to `ELIGIBLE`, resets `consecutive_breach_windows` to 0, clears `deactivated_at_epoch` back to null, and increments `reactivation_count` by 1."
    PRD §3.9: "When the node has no open window, one is created at an `epoch` equal to the greater of the network's current epoch and this node's highest existing epoch plus 1 — epochs are unique per node, so a reactivated node never re-uses a closed epoch."

    Design: Corner/errors/two_breached_windows_deactivate_the_node_and_only_a_deactivated_node_reactivates
    """
    ctx = _node_after_two_breached_epochs()

    response = api.reactivate_store(ctx["store"]["id"], PLANNER)

    reactivated = validate_success(response)
    assert reactivated["node_status"] == "ELIGIBLE", "reactivation returns the node to ELIGIBLE"
    assert reactivated["consecutive_breach_windows"] == 0, (
        "reactivation resets the breach counter"
    )
    assert reactivated["deactivated_at_epoch"] is None, (
        "reactivation clears deactivated_at_epoch"
    )
    assert reactivated["reactivation_count"] == 1, "reactivation_count rises by exactly 1"

    open_windows = find_windows(store_id=ctx["store"]["id"], status="OPEN")
    assert len(open_windows) == 1, "reactivation re-opens exactly one window for the node"
    assert open_windows[0]["epoch"] == 3, (
        "the node's highest existing epoch is 2, so the fresh window opens at epoch 3 "
        "and never re-uses a closed epoch"
    )


def test_reactivating_a_node_that_is_not_deactivated_is_refused(api):
    """PRD §3.9: "A `NetworkPlanner` returns a node from `DEACTIVATED → ELIGIBLE`; a node whose `node_status` is not `DEACTIVATED` is refused with `ERR_STORE_NOT_DEACTIVATED`."
    PRD §3.9: "Reactivation sets `node_status` to `ELIGIBLE`, resets `consecutive_breach_windows` to 0, clears `deactivated_at_epoch` back to null, and increments `reactivation_count` by 1."

    Design: Corner/errors/two_breached_windows_deactivate_the_node_and_only_a_deactivated_node_reactivates
    """
    ctx = _node_after_two_breached_epochs()
    first = validate_success(api.reactivate_store(ctx["store"]["id"], PLANNER))
    assert first["node_status"] == "ELIGIBLE", "precondition: the node is ELIGIBLE again"

    response = api.reactivate_store(ctx["store"]["id"], PLANNER)

    validate_error(response, "ERR_STORE_NOT_DEACTIVATED")

    store = read_store(ctx["store"]["id"])
    assert store["node_status"] == "ELIGIBLE", "the refused reactivation changes no posture"
    assert store["reactivation_count"] == 1, (
        "the refused second reactivation leaves reactivation_count at 1"
    )


def test_two_cancelled_epochs_leave_the_inventory_row_whole():
    """PRD §2.9: "A forward action such as a routing commit and its compensating action — a reject, a cancel, or a supersede — must return `available_to_promise_units` to exactly its pre-action value."
    PRD §3.2: "A full cancel moves `fulfillment_status` from `PENDING` to `CANCELLED`, cancels every non-terminal assignment of the order with cancellation reason `CUSTOMER_REQUEST` and no reroute, turns all released units into each line's `cancelled_units` so that every line ends with `open_units` 0 and `line_status` `CANCELLED`, releases each affected node's inventory reservations along with its `units_committed_epoch` and `reserved_labor_minutes`, recomputes each affected node's `eligibility_score`, emits exactly one customer notification of type `CANCELLATION_FULL`, leaves `final_cost_cents` null, recomputes `provisional_cost_cents` and `cost_index_bps`, and increments the order's `version`."

    Design: Corner/errors/two_breached_windows_deactivate_the_node_and_only_a_deactivated_node_reactivates
    """
    ctx = _node_after_two_breached_epochs()

    inventory = read_inventory(ctx["inventory"]["id"])
    assert inventory["reserved_units"] == 0, "both cancellations released their reservations"
    assert inventory["available_to_promise_units"] == 10, (
        "available_to_promise_units is back at max(0, 12 - 0 - 2) = 10"
    )
    assert inventory["on_hand_units"] == 12, "a cancel leaves on_hand_units untouched"


# ======================================================================
# The ops run is guarded network-wide
# ======================================================================


def test_ops_run_with_no_open_window_anywhere_is_refused(api):
    """PRD §3.9: "It requires at least one performance window somewhere in the network at `status` `OPEN`, or it is refused with `ERR_NO_OPEN_WINDOW`."

    Design: Corner/errors/the_ops_run_on_a_network_with_no_open_window_is_refused
    """
    set_clock(CLOCK_OPEN)

    response = api.close_performance_windows(PLANNER)

    validate_error(response, "ERR_NO_OPEN_WINDOW")

    _rows, meta = validate_paginated(api.list_performance_windows(PLANNER))
    assert meta["total_count"] == 0, "no node exists, so no performance window exists"


def test_ops_run_succeeds_once_a_node_registration_opens_the_first_window(api):
    """PRD §3.1: "Registration also opens the node's first performance window at the network's current epoch — the highest `epoch` across all existing windows, or 1 when no window exists anywhere yet — with `opened_at_utc` set to the clock instant and `closed_at_utc` null."
    PRD §3.9: "Each window's `status` becomes `CLOSED`, its `closed_at_utc` is set to the clock instant, and each node's `units_committed_epoch` is reset to 0."
    PRD §3.9: "It executes seven steps in exactly this order, and it answers with the windows it closed, in ascending node `created_at` order."

    Design: Corner/errors/the_ops_run_on_a_network_with_no_open_window_is_refused
    """
    set_clock(CLOCK_OPEN)
    refused = api.close_performance_windows(PLANNER)
    validate_error(refused, "ERR_NO_OPEN_WINDOW")

    store = register_node("S3")

    closed = validate_success(api.close_performance_windows(PLANNER))
    assert isinstance(closed, list), "the ops-run answers with the windows it closed"
    assert len(closed) == 1, "registering the one node opened the one window this run closes"
    window = closed[0]
    assert window["store_id"] == store["id"], "the closed window belongs to the new node"
    assert window["epoch"] == 1, "no window existed anywhere, so the first one opened at epoch 1"
    assert window["status"] == "CLOSED", "the ops-run closes the window"
    assert _instant(window["closed_at_utc"]) == _instant(CLOCK_OPEN), (
        "closed_at_utc is the clock instant"
    )


def test_an_empty_closed_window_is_inert():
    """PRD §3.9: "`fill_rate` is exactly 1.0000 when `units_promised` is 0, and otherwise `units_shipped` divided by `units_promised` rounded half-up to four decimal places."
    PRD §3.9: "`avg_cycle_time_minutes` is exactly 0.00 when `assignments_shipped` is 0, and otherwise the sum of `cycle_time_minutes` over the shipped assignments divided by `assignments_shipped`, rounded half-up to two decimal places."
    PRD §3.9: "`cancellation_rate` is exactly 0.0000 when `assignments_created` is 0, and otherwise `assignments_rejected` plus `assignments_cancelled`, divided by `assignments_created`, rounded half-up to four decimal places."
    PRD §3.9: "`node_action` is `NONE` when `assignments_created` is 0 — an empty window is inert."
    PRD §3.9: "`consecutive_breach_windows` is then set to 0 when the window was non-empty and not breached, incremented by 1 when the window was non-empty and breached, and left completely unchanged when the window was empty — so an empty window never changes posture and never resets the breach counter."

    Design: Corner/errors/the_ops_run_on_a_network_with_no_open_window_is_refused
    """
    set_clock(CLOCK_OPEN)
    store = register_node("S3")

    closed = close_windows()

    window = closed[0]
    assert window["assignments_created"] == 0, "no assignment was ever created at this node"
    assert window["fill_rate"] == pytest.approx(1.0, abs=0.01), (
        "units_promised is 0, so fill_rate is exactly 1.0000"
    )
    assert window["cancellation_rate"] == pytest.approx(0.0, abs=0.01), (
        "assignments_created is 0, so cancellation_rate is exactly 0.0000"
    )
    assert window["avg_cycle_time_minutes"] == pytest.approx(0.0, abs=0.01), (
        "assignments_shipped is 0, so avg_cycle_time_minutes is exactly 0.00"
    )
    assert window["breach_flags"] == [], "an empty window appends no breach marker"
    assert window["breached"] is False, "an empty breach_flags list means not breached"
    assert window["node_action"] == "NONE", "an empty window is inert"
    assert read_store(store["id"])["consecutive_breach_windows"] == 0, (
        "an empty window leaves the breach counter completely unchanged"
    )


def test_ops_run_opens_the_next_epoch_window_for_the_still_eligible_node():
    """PRD §3.9: "A new performance window at `status` `OPEN` and at the previous `epoch` plus 1 is created for every node whose `node_status` is `ELIGIBLE` or `PROBATION`, with `opened_at_utc` at the clock instant and `closed_at_utc` null. Deactivated nodes get none."

    Design: Corner/errors/the_ops_run_on_a_network_with_no_open_window_is_refused
    """
    set_clock(CLOCK_OPEN)
    store = register_node("S3")
    close_windows()

    open_windows = find_windows(store_id=store["id"], status="OPEN")
    assert len(open_windows) == 1, "the ELIGIBLE node gets exactly one successor window"
    assert open_windows[0]["epoch"] == 2, "the successor window sits at the previous epoch plus 1"
    assert open_windows[0]["closed_at_utc"] is None, "a freshly opened window has no closed_at_utc"
    assert _instant(open_windows[0]["opened_at_utc"]) == _instant(CLOCK_OPEN), (
        "opened_at_utc is the clock instant"
    )
