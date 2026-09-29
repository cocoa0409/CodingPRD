"""Network records: node / SKU / inventory / order creation, reads and refusals.

Every test starts against an empty database and builds its own state through
declared endpoints only.
"""

import pytest

from test_helpers import (
    CARE,
    CARRIER,
    PLANNER,
    api_client,
    assert_assignment_line,
    assert_customer_notification,
    assert_customer_order,
    assert_order_line,
    assert_routing_candidate,
    assert_sku,
    assert_store,
    assert_store_inventory,
    assert_timestamp_format,
    cancel_order,
    create_order_line_payload,
    create_order_payload,
    create_sku_payload,
    create_store_inventory_payload,
    create_store_payload,
    find_assignment_lines,
    find_notifications,
    find_routing_candidates,
    inventory_adjustment_payload,
    is_valid_uuid,
    make_store_associate_headers,
    read_assignment_line,
    read_store,
    register_node,
    register_nodes,
    register_sku,
    set_clock,
    setup_committed_assignment,
    setup_order_with_lines,
    stock_inventory,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK = "2026-08-03T09:00:00Z"
UNKNOWN_STORE_ID = "00000000-0000-4000-8000-000000000001"
UNKNOWN_ORDER_ID = "00000000-0000-4000-8000-000000000002"
UNKNOWN_SKU_ID = "00000000-0000-4000-8000-000000000003"
UNOWNED_ASSOCIATE_ID = "00000000-0000-4000-8000-000000000009"


def _at_second(timestamp: str) -> str:
    """An ISO 8601 UTC timestamp truncated to whole seconds, so a stored instant
    can be compared to the clock instant regardless of fractional digits."""
    return timestamp[:19]


def _two_line_order() -> dict:
    """Clock at 09:00, SKU-A and SKU-B registered, and a never-routed zone-4
    GROUND order carrying SKU-A x3 then SKU-B x1."""
    set_clock(CLOCK)
    sku_a = register_sku("SKU-A")
    sku_b = register_sku("SKU-B")
    built = setup_order_with_lines(
        [(sku_a["id"], 3, 4500), (sku_b["id"], 1, 1900)],
        order_code="O-9001",
        customer_ref="C-101",
        destination_zone=4,
        service_level="GROUND",
        promised_ship_by_utc="2026-08-03T15:00:00Z",
    )
    return {"sku_a": sku_a, "sku_b": sku_b, **built}


def _cancelled_committed_order() -> dict:
    """One node, one SKU, a single-line order committed to that node and then
    cancelled by care — which yields one assignment line, one routing candidate
    and one customer notification to read back."""
    ctx = setup_committed_assignment(
        node_preset="S1",
        sku_preset="SKU-A",
        on_hand_units=20,
        safety_stock_units=2,
        quantity=2,
        order_code="O-9201",
        customer_ref="C-121",
        clock=CLOCK,
        with_packaging=False,
        with_pickup=False,
    )
    cancel_order(ctx["order"]["id"])
    return ctx


# ======================================================================
# Node registration
# ======================================================================


def test_store_registration_returns_eligible_node_with_cold_start_score():
    """PRD §4: "Operations that bring a new resource into existence — registering a node, creating a SKU, stocking inventory or packaging, scheduling a pickup, taking an order, adding a demand line, starting a routing run — answer with `201 Created`."
    PRD §3.1: "Registration seeds the node's derived state: `node_status` becomes `ELIGIBLE`, `units_committed_epoch` and `reserved_labor_minutes` are 0, `consecutive_breach_windows` is 0, `reactivation_count` is 0, `deactivated_at_epoch` is null, and `review_score` is 0."
    PRD §3.1: "Finally, the node's `eligibility_score` is computed on the cold-start basis described in §3.3, and `eligibility_score_basis` is recorded as `COLD_START`."
    PRD §3.3: "The score is the sum of three components, each rounded half-up to four decimal places, with the sum then rounded half-up to two decimal places."
    PRD §3.3: "The **capacity component** starts from capacity headroom: the larger of 0 and `daily_unit_capacity` minus `units_committed_epoch`."
    PRD §3.3: "That headroom is divided by a reference of 200 units, the quotient is capped at 1, and the result is multiplied by a weight of 40."
    PRD §3.3: "The **labour component** starts from labour headroom: the larger of 0 and `staffed_labor_minutes` minus `reserved_labor_minutes`."
    PRD §3.3: "That headroom is divided by a reference of eight staffed hours, the quotient is capped at 1, and the result is multiplied by a weight of 30."
    PRD §3.3: "The **performance component** is a weight of 30 multiplied by a performance ratio between 0 and 1."
    PRD §3.3: "A node with zero closed performance windows uses a flat performance ratio of 0.60 and records `eligibility_score_basis` as `COLD_START`."
    PRD §2.5: "Every persisted resource carries an `id`: a server-minted UUID with no type prefix."
    PRD §2.5: "Most resources — nodes, SKUs, inventory rows, packaging rows, carrier pickups, customer orders, demand lines, routing runs, fulfillment assignments and performance windows — additionally carry `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation, and `version`, an integer that starts at 1 on creation and increments by exactly 1 on every mutation of that row."

    Design: Corner/entities/store_creation_returns_eligible_node_with_cold_start_score
    """
    set_clock(CLOCK)

    response = api_client.create_store(create_store_payload("S1"), PLANNER)
    store = validate_success(response, expected_status=201)
    assert_store(store)

    body = response.json()
    assert body["response_type"] == "object", (
        "a single created node is an object envelope, not an array"
    )
    assert body["meta"]["api_request_id"].startswith("req_"), (
        "meta.api_request_id must be a server-generated id starting with req_"
    )
    assert_timestamp_format(body["meta"]["api_request_timestamp"])

    assert store["node_status"] == "ELIGIBLE", (
        f"a freshly registered node begins ELIGIBLE, got {store['node_status']}"
    )
    assert store["eligibility_score_basis"] == "COLD_START", (
        "a node with zero closed windows records eligibility_score_basis COLD_START"
    )
    assert store["eligibility_score"] == pytest.approx(72.00, abs=0.01), (
        "cold-start score is 40 * min(1, 120/200) + 30 * min(1, 480/480) + 30 * 0.60 "
        f"= 72.00, got {store['eligibility_score']}"
    )
    assert store["units_committed_epoch"] == 0, "units_committed_epoch is seeded to 0"
    assert store["reserved_labor_minutes"] == pytest.approx(0.00, abs=0.01), (
        "reserved_labor_minutes is seeded to 0"
    )
    assert store["consecutive_breach_windows"] == 0, (
        "consecutive_breach_windows is seeded to 0"
    )
    assert store["deactivated_at_epoch"] is None, (
        "deactivated_at_epoch is seeded to null"
    )
    assert store["reactivation_count"] == 0, "reactivation_count is seeded to 0"
    assert store["review_score"] == pytest.approx(0.00, abs=0.01), (
        "review_score is seeded to 0 and only written by the operations run"
    )

    assert is_valid_uuid(store["id"]), "id is a server-minted UUID with no type prefix"
    assert_timestamp_format(store["created_at"])
    assert_timestamp_format(store["updated_at"])
    assert store["version"] == 1, (
        f"version starts at 1 on creation, got {store['version']}"
    )


def test_store_registration_opens_first_performance_window_at_epoch_1():
    """PRD §3.1: "Registration also opens the node's first performance window at the network's current epoch — the highest `epoch` across all existing windows, or 1 when no window exists anywhere yet — with `opened_at_utc` set to the clock instant and `closed_at_utc` null."
    PRD §2.6: "Every temporal rule in this system — pick deadlines, same-day cutoffs, carrier pickup windows, cycle times, notification timestamps — reads a single server-side logical clock rather than wall-clock time."
    PRD §2.3: "Every list response repeats `limit` and `offset` in the envelope's `meta` object alongside `total_count` (the number of rows matching the filters before pagination) and `has_more` (true when rows remain beyond the current page)."

    Design: Corner/entities/store_creation_returns_eligible_node_with_cold_start_score
    """
    set_clock(CLOCK)
    store = register_node("S1")

    rows, meta = validate_paginated(
        api_client.list_performance_windows(PLANNER, params={"store_id": store["id"]})
    )
    assert meta["total_count"] == 1, (
        f"registration opens exactly one window for the node, got {meta['total_count']}"
    )
    assert meta["has_more"] is False, "a single window leaves no further page"
    assert len(rows) == 1, f"expected one window row, got {len(rows)}"

    window = rows[0]
    assert window["store_id"] == store["id"], "the window belongs to the new node"
    assert window["status"] == "OPEN", (
        f"the first window is opened, got status {window['status']}"
    )
    assert window["epoch"] == 1, (
        f"with no window anywhere yet the network epoch is 1, got {window['epoch']}"
    )
    assert _at_second(window["opened_at_utc"]) == "2026-08-03T09:00:00", (
        f"opened_at_utc is the clock instant, got {window['opened_at_utc']}"
    )
    assert window["closed_at_utc"] is None, "an open window has closed_at_utc null"


def test_store_creation_missing_staffed_labor_minutes_returns_invalid_request():
    """PRD §3.1: "The node's throughput envelope is declared with `daily_unit_capacity` (at least 1), the units it may commit inside one epoch, and `staffed_labor_minutes` (at least 1), the fulfillment labour minutes staffed for the epoch."
    PRD §2.11: "Request shape second: required fields present, types correct, enum members inside their declared sets, integers inside their declared ranges — `limit` from 1 to 100, `offset` at least 0, `quantity` at least 1, `picked_units` at least 0, `parcel_capacity` at least 1, and both `origin_zone` and `destination_zone` from 1 to 8 — all reported as `ERR_INVALID_REQUEST`."

    Design: Corner/entities/store_creation_missing_staffed_labor_minutes_returns_invalid_request
    """
    set_clock(CLOCK)

    payload = create_store_payload("S1")
    payload.pop("staffed_labor_minutes")

    validate_error(
        api_client.create_store(payload, PLANNER), "ERR_INVALID_REQUEST"
    )

    _rows, meta = validate_paginated(api_client.list_stores(PLANNER))
    assert meta["total_count"] == 0, (
        "a request refused on shape must not write a node row, "
        f"but the registry holds {meta['total_count']}"
    )


def test_omitted_hazmat_flags_default_to_false_on_store_and_sku():
    """PRD §3.1: "The node also declares `cutoff_utc_minutes` and, optionally, `hazmat_certified`, which defaults to false and, when true, allows the node to fulfill SKUs flagged as hazardous."
    PRD §3.1: "A planner creates one with a `sku_code` unique across all SKUs (`ERR_DUPLICATE_SKU_CODE` otherwise), a `unit_weight_grams` of at least 1 gram used for shipping weight, a `unit_price_cents` of at least 0 as list price, a `package_class` of `SMALL`, `MEDIUM` or `LARGE` naming the smallest package family that can hold one unit, and an optional `hazmat_flag` defaulting to false."
    PRD §3.3: "A node with zero closed performance windows uses a flat performance ratio of 0.60 and records `eligibility_score_basis` as `COLD_START`."

    Design: Corner/entities/omitted_hazmat_flags_default_to_false_on_store_and_sku
    """
    set_clock(CLOCK)

    store_payload = create_store_payload("S1")
    store_payload.pop("hazmat_certified")
    store = validate_success(
        api_client.create_store(store_payload, PLANNER), expected_status=201
    )

    sku_payload = create_sku_payload("SKU-A")
    sku_payload.pop("hazmat_flag")
    sku = validate_success(
        api_client.create_sku(sku_payload, PLANNER), expected_status=201
    )

    assert store["hazmat_certified"] is False, (
        "an omitted hazmat_certified defaults to false, not null, "
        f"got {store['hazmat_certified']!r}"
    )
    assert sku["hazmat_flag"] is False, (
        f"an omitted hazmat_flag defaults to false, not null, got {sku['hazmat_flag']!r}"
    )
    assert store["eligibility_score"] == pytest.approx(72.00, abs=0.01), (
        "the omitted flag is not an input to the cold-start score, which stays 72.00"
    )


# ======================================================================
# Node reads
# ======================================================================


def test_store_listing_pages_with_limit_and_offset():
    """PRD §2.3: "`limit` caps the number of rows returned; it defaults to 10, may not be lower than 1 and may not exceed 100."
    PRD §2.3: "`offset` is the number of rows to skip; it defaults to 0 and may not be negative."
    PRD §2.3: "Every list response repeats `limit` and `offset` in the envelope's `meta` object alongside `total_count` (the number of rows matching the filters before pagination) and `has_more` (true when rows remain beyond the current page)."
    PRD §2.3: "Unless a specific endpoint states otherwise, list endpoints return rows sorted by `created_at` in ascending order."

    Design: Corner/entities/store_listing_honours_limit_offset_and_reports_total_count
    """
    set_clock(CLOCK)
    s1, s2, s3, s5 = register_nodes("S1", "S2", "S3", "S5")

    first, first_meta = validate_paginated(
        api_client.list_stores(CARRIER, params={"limit": 2, "offset": 0})
    )
    assert first_meta["limit"] == 2, "meta echoes the requested limit"
    assert first_meta["offset"] == 0, "meta echoes the requested offset"
    assert first_meta["total_count"] == 4, (
        f"total_count counts all matching rows before paging, got {first_meta['total_count']}"
    )
    assert first_meta["has_more"] is True, "two of four rows leaves rows beyond the page"
    assert [row["id"] for row in first] == [s1["id"], s2["id"]], (
        "the first page is the two oldest nodes in ascending created_at order"
    )

    second, second_meta = validate_paginated(
        api_client.list_stores(CARRIER, params={"limit": 2, "offset": 2})
    )
    assert second_meta["limit"] == 2, "meta echoes the requested limit"
    assert second_meta["offset"] == 2, "meta echoes the requested offset"
    assert second_meta["total_count"] == 4, (
        f"total_count is unaffected by the offset, got {second_meta['total_count']}"
    )
    assert second_meta["has_more"] is False, "the second page exhausts the four rows"
    assert [row["id"] for row in second] == [s3["id"], s5["id"]], (
        "the second page is the two newest nodes in ascending created_at order"
    )


def test_store_listing_filters_and_applies_default_pagination():
    """PRD §2.4: "Nodes may be filtered by `node_status` and `region_code`."
    PRD §2.3: "`limit` caps the number of rows returned; it defaults to 10, may not be lower than 1 and may not exceed 100."
    PRD §2.3: "`offset` is the number of rows to skip; it defaults to 0 and may not be negative."
    PRD §2.10: "A node's posture is carried by `node_status`, which is one of `ELIGIBLE`, `PROBATION` or `DEACTIVATED` and begins at `ELIGIBLE`."

    Design: Corner/entities/store_listing_honours_limit_offset_and_reports_total_count
    """
    set_clock(CLOCK)
    _s1, s2, _s3, s5 = register_nodes("S1", "S2", "S3", "S5")

    east, east_meta = validate_paginated(
        api_client.list_stores(CARRIER, params={"region_code": "EAST"})
    )
    assert east_meta["total_count"] == 2, (
        f"two of the four nodes report region_code EAST, got {east_meta['total_count']}"
    )
    assert [row["id"] for row in east] == [s2["id"], s5["id"]], (
        "the region_code filter returns exactly the two EAST nodes"
    )

    deactivated, deactivated_meta = validate_paginated(
        api_client.list_stores(CARRIER, params={"node_status": "DEACTIVATED"})
    )
    assert deactivated_meta["total_count"] == 0, (
        "every node begins ELIGIBLE, so the DEACTIVATED filter matches nothing"
    )
    assert deactivated_meta["has_more"] is False, "an empty match leaves no further page"
    assert deactivated == [], f"expected no rows, got {len(deactivated)}"

    response = api_client.list_stores(CARRIER)
    everything, default_meta = validate_paginated(response)
    assert response.json()["response_type"] == "array", (
        "a list read answers with an array envelope"
    )
    assert default_meta["limit"] == 10, (
        f"an unparameterised list defaults limit to 10, got {default_meta['limit']}"
    )
    assert default_meta["offset"] == 0, (
        f"an unparameterised list defaults offset to 0, got {default_meta['offset']}"
    )
    assert default_meta["total_count"] == 4, "all four nodes match no filter"
    assert default_meta["has_more"] is False, "four rows fit inside the default limit of 10"
    assert len(everything) == 4, f"expected all four nodes on one page, got {len(everything)}"


def test_store_detail_read_with_unknown_id_returns_store_not_found():
    """PRD §2.4: "The per-identifier codes are `ERR_STORE_NOT_FOUND` for `store_id`, `ERR_SKU_NOT_FOUND` for `sku_id`, `ERR_INVENTORY_NOT_FOUND` for `inventory_id`, `ERR_PACKAGING_NOT_FOUND` for `supply_id`, `ERR_PICKUP_NOT_FOUND` for `pickup_id` (and for a `carrier_pickup_id` supplied in a body), `ERR_ORDER_NOT_FOUND` for `order_id`, `ERR_ORDER_LINE_NOT_FOUND` for `order_line_id`, `ERR_ROUTING_RUN_NOT_FOUND` for `routing_run_id`, `ERR_CANDIDATE_NOT_FOUND` for `candidate_id`, `ERR_ASSIGNMENT_NOT_FOUND` for `assignment_id`, `ERR_ASSIGNMENT_LINE_NOT_FOUND` for `assignment_line_id`, `ERR_WINDOW_NOT_FOUND` for `window_id` and `ERR_NOTIFICATION_NOT_FOUND` for `notification_id`."
    PRD §2.2: "The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."
    PRD §2.2: "The `message` provides a human-readable explanation of what went wrong."

    Design: Corner/entities/store_detail_read_with_unknown_id_returns_store_not_found
    """
    set_clock(CLOCK)
    store = register_node("S1")
    assert store["id"] != UNKNOWN_STORE_ID, "the probed id must not be the real node's id"

    response = api_client.get_store(UNKNOWN_STORE_ID, PLANNER)
    error = validate_error(response, "ERR_STORE_NOT_FOUND")

    body = response.json()
    assert body["response_type"] == "error", (
        "an unresolved store_id answers with the error envelope, not an empty 200 body"
    )
    assert set(body["meta"].keys()) == {"api_request_id", "api_request_timestamp"}, (
        f"error meta carries only the two request fields, got {sorted(body['meta'])}"
    )
    assert set(error.keys()) == {"error_id", "message"}, (
        f"error data carries only error_id and message, got {sorted(error)}"
    )
    assert error["message"].strip(), "the error message must be human-readable"

    _rows, meta = validate_paginated(api_client.list_stores(PLANNER))
    assert meta["total_count"] == 1, (
        f"the failed probe created nothing, so one node remains, got {meta['total_count']}"
    )


# ======================================================================
# SKU system fields and type constraints
# ======================================================================


def test_sku_creation_mints_system_fields_readable_network_wide():
    """PRD §2.5: "Every persisted resource carries an `id`: a server-minted UUID with no type prefix."
    PRD §2.5: "Every resource also carries `created_at`, an ISO 8601 UTC timestamp with three fractional digits recording when the row was first written."
    PRD §2.5: "Most resources — nodes, SKUs, inventory rows, packaging rows, carrier pickups, customer orders, demand lines, routing runs, fulfillment assignments and performance windows — additionally carry `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation, and `version`, an integer that starts at 1 on creation and increments by exactly 1 on every mutation of that row."
    PRD §2.1: "Reads are exempt: every list and detail endpoint is network-wide and is not scope-checked."

    Design: Corner/entities/system_fields_are_minted_by_the_server_on_sku_creation
    """
    set_clock(CLOCK)

    created = validate_success(
        api_client.create_sku(create_sku_payload("SKU-A"), PLANNER), expected_status=201
    )
    assert_sku(created)
    assert is_valid_uuid(created["id"]), "id is a server-minted UUID with no type prefix"
    assert_timestamp_format(created["created_at"])
    assert_timestamp_format(created["updated_at"])
    assert created["version"] == 1, (
        f"version starts at 1 on creation, got {created['version']}"
    )

    # A StoreAssociate whose X-User-ID is not any node's id: reads are not scoped.
    read = validate_success(
        api_client.get_sku(
            created["id"], make_store_associate_headers(UNOWNED_ASSOCIATE_ID)
        )
    )
    assert read["id"] == created["id"], "the detail read returns the same minted id"
    assert read["created_at"] == created["created_at"], (
        "created_at records when the row was first written and never moves"
    )
    assert read["version"] == 1, (
        f"an unmutated SKU still reads version 1, got {read['version']}"
    )
    assert read["sku_code"] == "SKU-A", "sku_code reads back as supplied"
    assert read["unit_weight_grams"] == 800, "unit_weight_grams reads back as supplied"
    assert read["unit_price_cents"] == 4500, "unit_price_cents reads back as supplied"
    assert read["package_class"] == "MEDIUM", "package_class reads back as supplied"


def test_unknown_enum_members_are_rejected_as_invalid_request():
    """PRD §2.11: "Request shape second: required fields present, types correct, enum members inside their declared sets, integers inside their declared ranges — `limit` from 1 to 100, `offset` at least 0, `quantity` at least 1, `picked_units` at least 0, `parcel_capacity` at least 1, and both `origin_zone` and `destination_zone` from 1 to 8 — all reported as `ERR_INVALID_REQUEST`."
    PRD §3.1: "A planner creates one with a `sku_code` unique across all SKUs (`ERR_DUPLICATE_SKU_CODE` otherwise), a `unit_weight_grams` of at least 1 gram used for shipping weight, a `unit_price_cents` of at least 0 as list price, a `package_class` of `SMALL`, `MEDIUM` or `LARGE` naming the smallest package family that can hold one unit, and an optional `hazmat_flag` defaulting to false."
    PRD §3.2: "A `CustomerCare` agent takes an order with an `order_code` unique across all orders (`ERR_DUPLICATE_ORDER_CODE` otherwise), a `customer_ref` opaque handle used on customer notifications, a `destination_zone` from 1 to 8 giving the carrier destination zone of the ship-to address, a `service_level` of either `GROUND` or `EXPEDITED`, and a `promised_ship_by_utc` instant echoed onto notifications."

    Design: Corner/entities/unknown_enum_members_and_out_of_range_pagination_return_invalid_request
    """
    set_clock(CLOCK)

    validate_error(
        api_client.create_sku(
            create_sku_payload("SKU-A", sku_code="SKU-X", package_class="HUGE"), PLANNER
        ),
        "ERR_INVALID_REQUEST",
    )
    _skus, sku_meta = validate_paginated(api_client.list_skus(PLANNER))
    assert sku_meta["total_count"] == 0, (
        "a package_class outside SMALL/MEDIUM/LARGE writes no SKU row, "
        f"but the registry holds {sku_meta['total_count']}"
    )

    validate_error(
        api_client.create_order(
            create_order_payload(
                order_code="O-9101", customer_ref="C-111", service_level="TELEPORT"
            ),
            CARE,
        ),
        "ERR_INVALID_REQUEST",
    )
    _orders, order_meta = validate_paginated(api_client.list_orders(CARE))
    assert order_meta["total_count"] == 0, (
        "a service_level outside GROUND/EXPEDITED writes no order row, "
        f"but the registry holds {order_meta['total_count']}"
    )


def test_pagination_limit_outside_its_range_is_rejected_as_invalid_request():
    """PRD §2.3: "`limit` caps the number of rows returned; it defaults to 10, may not be lower than 1 and may not exceed 100."
    PRD §2.3: "A `limit` outside the range 1 to 100 inclusive, or a negative `offset`, is rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/unknown_enum_members_and_out_of_range_pagination_return_invalid_request
    """
    set_clock(CLOCK)

    validate_error(
        api_client.list_stores(PLANNER, params={"limit": 101}), "ERR_INVALID_REQUEST"
    )
    validate_error(
        api_client.list_stores(PLANNER, params={"limit": 0}), "ERR_INVALID_REQUEST"
    )


# ======================================================================
# Inventory rows: the promise-able quantity
# ======================================================================


def test_inventory_creation_derives_available_to_promise():
    """PRD §3.1: "Creation sets `reserved_units` to 0, leaves `last_adjustment_reason` null, and derives `available_to_promise_units` as the larger of 0 and the result of taking `on_hand_units`, subtracting `reserved_units`, then subtracting `safety_stock_units`."
    PRD §3.1: "Reserved units are never set by a client."
    PRD §2.5: "Most resources — nodes, SKUs, inventory rows, packaging rows, carrier pickups, customer orders, demand lines, routing runs, fulfillment assignments and performance windows — additionally carry `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation, and `version`, an integer that starts at 1 on creation and increments by exactly 1 on every mutation of that row."

    Design: Corner/entities/available_to_promise_is_computed_from_on_hand_minus_reserved_and_safety
    """
    set_clock(CLOCK)
    store = register_node("S1")
    sku = register_sku("SKU-A")

    row = validate_success(
        api_client.create_store_inventory(
            create_store_inventory_payload(
                store["id"], sku["id"], on_hand_units=12, safety_stock_units=2
            ),
            PLANNER,
        ),
        expected_status=201,
    )
    assert_store_inventory(row)

    assert row["on_hand_units"] == 12, "on_hand_units is stored as supplied"
    assert row["safety_stock_units"] == 2, "safety_stock_units is stored as supplied"
    assert row["reserved_units"] == 0, (
        f"creation sets reserved_units to 0, got {row['reserved_units']}"
    )
    assert row["available_to_promise_units"] == 10, (
        "available_to_promise_units is max(0, 12 - 0 - 2) = 10, got "
        f"{row['available_to_promise_units']}"
    )
    assert row["last_adjustment_reason"] is None, (
        "creation leaves last_adjustment_reason null"
    )
    assert row["version"] == 1, f"version starts at 1 on creation, got {row['version']}"


def test_inventory_adjustment_re_derives_available_to_promise():
    """PRD §3.1: "An adjustment carries `expected_inventory_version`, a `counted_on_hand_units` figure, a `reason` of `CYCLE_COUNT`, `SHRINK`, `RECEIPT` or `MARKDOWN_PULL`, and optionally a replacement `safety_stock_units`."
    PRD §3.1: "On success `on_hand_units` is overwritten with `counted_on_hand_units`, `last_adjustment_reason` records the supplied `reason`, `available_to_promise_units` is recomputed, the node's `eligibility_score` is recomputed, and the row's `version` increments."
    PRD §3.1: "Creation sets `reserved_units` to 0, leaves `last_adjustment_reason` null, and derives `available_to_promise_units` as the larger of 0 and the result of taking `on_hand_units`, subtracting `reserved_units`, then subtracting `safety_stock_units`."
    PRD §3.3: "A node with zero closed performance windows uses a flat performance ratio of 0.60 and records `eligibility_score_basis` as `COLD_START`."

    Design: Corner/entities/available_to_promise_is_computed_from_on_hand_minus_reserved_and_safety
    """
    set_clock(CLOCK)
    store = register_node("S1")
    sku = register_sku("SKU-A")
    row = stock_inventory(store["id"], sku["id"], 12, 2)

    adjusted = validate_success(
        api_client.adjust_store_inventory(
            row["id"],
            inventory_adjustment_payload(
                row["version"], 9, "CYCLE_COUNT", safety_stock_units=3
            ),
            PLANNER,
        )
    )
    assert_store_inventory(adjusted)

    assert adjusted["on_hand_units"] == 9, (
        f"on_hand_units is overwritten with the counted figure, got {adjusted['on_hand_units']}"
    )
    assert adjusted["safety_stock_units"] == 3, (
        f"the replacement safety_stock_units is stored, got {adjusted['safety_stock_units']}"
    )
    assert adjusted["reserved_units"] == 0, (
        "no assignment holds a reservation, so reserved_units stays 0"
    )
    assert adjusted["available_to_promise_units"] == 6, (
        "available_to_promise_units re-derives to max(0, 9 - 0 - 3) = 6, got "
        f"{adjusted['available_to_promise_units']}"
    )
    assert adjusted["last_adjustment_reason"] == "CYCLE_COUNT", (
        f"last_adjustment_reason records the supplied reason, got "
        f"{adjusted['last_adjustment_reason']!r}"
    )
    assert adjusted["version"] == 2, (
        f"the adjustment increments the row's version to 2, got {adjusted['version']}"
    )

    rescored = read_store(store["id"])
    assert rescored["eligibility_score"] == pytest.approx(72.00, abs=0.01), (
        "the adjustment re-scores the node, but stock is not an input to the "
        f"cold-start score, which stays 72.00, got {rescored['eligibility_score']}"
    )


def test_inventory_creation_with_unknown_sku_returns_sku_not_found():
    """PRD §2.4: "Foreign keys supplied in a request body resolve under the same codes: a `store_id` or `sku_id` on an inventory row, a `store_id` on a packaging row, a `sku_id` on a demand line, an `assignment_line_id` inside a pick payload, or a `carrier_pickup_id` on a ship request."
    PRD §2.4: "The per-identifier codes are `ERR_STORE_NOT_FOUND` for `store_id`, `ERR_SKU_NOT_FOUND` for `sku_id`, `ERR_INVENTORY_NOT_FOUND` for `inventory_id`, `ERR_PACKAGING_NOT_FOUND` for `supply_id`, `ERR_PICKUP_NOT_FOUND` for `pickup_id` (and for a `carrier_pickup_id` supplied in a body), `ERR_ORDER_NOT_FOUND` for `order_id`, `ERR_ORDER_LINE_NOT_FOUND` for `order_line_id`, `ERR_ROUTING_RUN_NOT_FOUND` for `routing_run_id`, `ERR_CANDIDATE_NOT_FOUND` for `candidate_id`, `ERR_ASSIGNMENT_NOT_FOUND` for `assignment_id`, `ERR_ASSIGNMENT_LINE_NOT_FOUND` for `assignment_line_id`, `ERR_WINDOW_NOT_FOUND` for `window_id` and `ERR_NOTIFICATION_NOT_FOUND` for `notification_id`."

    Design: Corner/entities/store_inventory_creation_with_an_unknown_sku_returns_sku_not_found
    """
    set_clock(CLOCK)
    store = register_node("S1")
    sku = register_sku("SKU-A")
    assert sku["id"] != UNKNOWN_SKU_ID, "the fabricated sku_id must not be the real one"

    validate_error(
        api_client.create_store_inventory(
            create_store_inventory_payload(store["id"], UNKNOWN_SKU_ID, 10, 2), PLANNER
        ),
        "ERR_SKU_NOT_FOUND",
    )

    _rows, meta = validate_paginated(api_client.list_store_inventories(PLANNER))
    assert meta["total_count"] == 0, (
        "an unresolved sku_id writes no inventory row, "
        f"but the collection holds {meta['total_count']}"
    )


def test_inventory_creation_with_unknown_store_returns_store_not_found():
    """PRD §2.4: "Foreign keys supplied in a request body resolve under the same codes: a `store_id` or `sku_id` on an inventory row, a `store_id` on a packaging row, a `sku_id` on a demand line, an `assignment_line_id` inside a pick payload, or a `carrier_pickup_id` on a ship request."
    PRD §2.4: "The per-identifier codes are `ERR_STORE_NOT_FOUND` for `store_id`, `ERR_SKU_NOT_FOUND` for `sku_id`, `ERR_INVENTORY_NOT_FOUND` for `inventory_id`, `ERR_PACKAGING_NOT_FOUND` for `supply_id`, `ERR_PICKUP_NOT_FOUND` for `pickup_id` (and for a `carrier_pickup_id` supplied in a body), `ERR_ORDER_NOT_FOUND` for `order_id`, `ERR_ORDER_LINE_NOT_FOUND` for `order_line_id`, `ERR_ROUTING_RUN_NOT_FOUND` for `routing_run_id`, `ERR_CANDIDATE_NOT_FOUND` for `candidate_id`, `ERR_ASSIGNMENT_NOT_FOUND` for `assignment_id`, `ERR_ASSIGNMENT_LINE_NOT_FOUND` for `assignment_line_id`, `ERR_WINDOW_NOT_FOUND` for `window_id` and `ERR_NOTIFICATION_NOT_FOUND` for `notification_id`."

    Design: Corner/entities/store_inventory_creation_with_an_unknown_sku_returns_sku_not_found
    """
    set_clock(CLOCK)
    store = register_node("S1")
    sku = register_sku("SKU-A")
    unknown_store_id = "00000000-0000-4000-8000-000000000004"
    assert store["id"] != unknown_store_id, (
        "the fabricated store_id must not be the real node's id"
    )

    validate_error(
        api_client.create_store_inventory(
            create_store_inventory_payload(unknown_store_id, sku["id"], 10, 2), PLANNER
        ),
        "ERR_STORE_NOT_FOUND",
    )

    _rows, meta = validate_paginated(api_client.list_store_inventories(PLANNER))
    assert meta["total_count"] == 0, (
        "an unresolved store_id writes no inventory row, "
        f"but the collection holds {meta['total_count']}"
    )


# ======================================================================
# Orders and demand lines
# ======================================================================


def test_order_detail_read_returns_stored_inputs_and_derived_totals():
    """PRD §3.2: "Intake sets `routing_status` to `UNROUTED`, `fulfillment_status` to `PENDING`, and every unit counter — `total_units`, `shipped_units`, `unassigned_units`, `dc_fallback_units`, `split_count`, `reroute_attempt_count` — to 0, with `provisional_cost_cents` 0, `final_cost_cents` null, `cost_variance_cents` null and `cost_index_bps` 0."
    PRD §3.2: "Adding a line recomputes the order's `total_units`, `unassigned_units` and `dc_baseline_cost_cents`, and increments the order's `version`."
    PRD §2.9: "At the order level, `total_units` equals the sum of every demand line's `quantity`, and `unassigned_units` equals the sum of every demand line's `open_units`."
    PRD §2.5: "Most resources — nodes, SKUs, inventory rows, packaging rows, carrier pickups, customer orders, demand lines, routing runs, fulfillment assignments and performance windows — additionally carry `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation, and `version`, an integer that starts at 1 on creation and increments by exactly 1 on every mutation of that row."

    Design: Corner/entities/order_detail_read_returns_stored_inputs_and_derived_totals
    """
    ctx = _two_line_order()
    order_id = ctx["order"]["id"]

    response = api_client.get_order(order_id, CARE)
    order = validate_success(response)
    assert_customer_order(order)
    assert response.json()["response_type"] == "object", (
        "a single order detail read is an object envelope"
    )

    assert order["order_code"] == "O-9001", "order_code echoes the intake input"
    assert order["customer_ref"] == "C-101", "customer_ref echoes the intake input"
    assert order["destination_zone"] == 4, "destination_zone echoes the intake input"
    assert order["service_level"] == "GROUND", "service_level echoes the intake input"
    assert _at_second(order["promised_ship_by_utc"]) == "2026-08-03T15:00:00", (
        f"promised_ship_by_utc echoes the intake input, got {order['promised_ship_by_utc']}"
    )

    assert order["total_units"] == 4, (
        f"total_units is 3 + 1 across the two demand lines, got {order['total_units']}"
    )
    assert order["unassigned_units"] == 4, (
        "unassigned_units is the sum of the lines' open_units, got "
        f"{order['unassigned_units']}"
    )
    assert order["routing_status"] == "UNROUTED", (
        f"an order that has never been routed stays UNROUTED, got {order['routing_status']}"
    )
    assert order["fulfillment_status"] == "PENDING", (
        f"intake sets fulfillment_status PENDING, got {order['fulfillment_status']}"
    )
    assert order["shipped_units"] == 0, "no unit has shipped"
    assert order["dc_fallback_units"] == 0, "no unit went to the distribution centre"
    assert order["split_count"] == 0, "no assignment exists yet"
    assert order["reroute_attempt_count"] == 0, "no system reroute run exists yet"
    assert order["provisional_cost_cents"] == 0, (
        f"intake sets provisional_cost_cents to 0, got {order['provisional_cost_cents']}"
    )
    assert order["cost_index_bps"] == 0, (
        f"intake sets cost_index_bps to 0, got {order['cost_index_bps']}"
    )
    assert order["final_cost_cents"] is None, "final_cost_cents is null until ship"
    assert order["cost_variance_cents"] is None, "cost_variance_cents is null until ship"

    assert order["version"] == 3, (
        "creation minted version 1 and each of the two line creations bumped it by "
        f"exactly 1, got {order['version']}"
    )


def test_order_lines_read_back_their_opening_counters():
    """PRD §3.2: "A new line starts with `assigned_units`, `shipped_units`, `cancelled_units` and `dc_fallback_units` all 0, `open_units` equal to `quantity`, and `line_status` `OPEN`."
    PRD §2.4: "Demand lines may be filtered by `order_id`, `sku_id` and `line_status`."
    PRD §2.3: "Every list response repeats `limit` and `offset` in the envelope's `meta` object alongside `total_count` (the number of rows matching the filters before pagination) and `has_more` (true when rows remain beyond the current page)."

    Design: Corner/entities/order_detail_read_returns_stored_inputs_and_derived_totals
    """
    ctx = _two_line_order()
    order_id = ctx["order"]["id"]

    rows, meta = validate_paginated(
        api_client.list_order_lines(CARE, params={"order_id": order_id})
    )
    assert meta["total_count"] == 2, (
        f"the order carries exactly two demand lines, got {meta['total_count']}"
    )
    assert meta["has_more"] is False, "two rows fit inside the default page"
    assert len(rows) == 2, f"expected two demand line rows, got {len(rows)}"

    by_id = {row["id"]: row for row in rows}
    first = by_id[ctx["lines"][0]["id"]]
    second = by_id[ctx["lines"][1]["id"]]
    assert_order_line(first)
    assert_order_line(second)

    assert first["quantity"] == 3, "the SKU-A line was taken for 3 units"
    assert first["open_units"] == 3, (
        f"a new line's open_units equals its quantity, got {first['open_units']}"
    )
    assert first["assigned_units"] == 0, "a new line has no assigned units"
    assert first["shipped_units"] == 0, "a new line has no shipped units"
    assert first["cancelled_units"] == 0, "a new line has no cancelled units"
    assert first["dc_fallback_units"] == 0, "a new line has no fallback units"
    assert first["line_status"] == "OPEN", (
        f"a new line's line_status is OPEN, got {first['line_status']}"
    )

    assert second["quantity"] == 1, "the SKU-B line was taken for 1 unit"
    assert second["open_units"] == 1, (
        f"a new line's open_units equals its quantity, got {second['open_units']}"
    )
    assert second["line_status"] == "OPEN", (
        f"a new line's line_status is OPEN, got {second['line_status']}"
    )


def test_order_line_creation_under_an_unknown_order_returns_order_not_found():
    """PRD §2.4: "Where a path does carry more than one identifier — a pickup being scheduled at a node, or a demand line being added to an order — the identifiers are resolved strictly left to right, and the first one that does not resolve determines the 404 that comes back."
    PRD §2.4: "The per-identifier codes are `ERR_STORE_NOT_FOUND` for `store_id`, `ERR_SKU_NOT_FOUND` for `sku_id`, `ERR_INVENTORY_NOT_FOUND` for `inventory_id`, `ERR_PACKAGING_NOT_FOUND` for `supply_id`, `ERR_PICKUP_NOT_FOUND` for `pickup_id` (and for a `carrier_pickup_id` supplied in a body), `ERR_ORDER_NOT_FOUND` for `order_id`, `ERR_ORDER_LINE_NOT_FOUND` for `order_line_id`, `ERR_ROUTING_RUN_NOT_FOUND` for `routing_run_id`, `ERR_CANDIDATE_NOT_FOUND` for `candidate_id`, `ERR_ASSIGNMENT_NOT_FOUND` for `assignment_id`, `ERR_ASSIGNMENT_LINE_NOT_FOUND` for `assignment_line_id`, `ERR_WINDOW_NOT_FOUND` for `window_id` and `ERR_NOTIFICATION_NOT_FOUND` for `notification_id`."

    Design: Corner/entities/order_line_creation_under_an_unknown_order_returns_order_not_found
    """
    set_clock(CLOCK)
    sku = register_sku("SKU-A")

    validate_error(
        api_client.create_order_line(
            UNKNOWN_ORDER_ID, create_order_line_payload(sku["id"], 2, 4500), CARE
        ),
        "ERR_ORDER_NOT_FOUND",
    )

    _rows, meta = validate_paginated(api_client.list_order_lines(CARE))
    assert meta["total_count"] == 0, (
        "an unresolved order_id writes no demand line, "
        f"but the collection holds {meta['total_count']}"
    )


# ======================================================================
# Append-only child rows
# ======================================================================


class TestImmutableChildRows:
    """The three append-only records the PRD declares carry no version."""

    def test_assignment_line_read_carries_no_version(self):
        """PRD §2.5: "Three resources are append-only records rather than mutable state and therefore carry only `id` and `created_at` — both `updated_at` and `version` are absent from `RoutingCandidate`, from `AssignmentLine` and from `CustomerNotification`."
        PRD §3.5: "Alongside the assignment, one assignment line is created per demand line served, each carrying `assignment_id`, `order_line_id` and `units_assigned` — immutable after creation — with `units_picked` and `units_cancelled` both starting at 0."
        PRD §3.7: "All four permitted source states carry the same cascade: `status` becomes `CANCELLED` and the `cancel_reason_code` is stored; each assignment line's `units_cancelled` becomes its `units_assigned` minus its `units_picked`, releasing that much of the served demand line's `assigned_units`; the node's inventory `reserved_units`, `units_committed_epoch` and `reserved_labor_minutes` all decrease and its `eligibility_score` is recomputed — including, for a `PICKED` or `SHORT_PICKED` source, the units already physically picked, which are returned to the node's reservations and then released; when `reroute` is true a system reroute run excluding this node is created, at `initiated_by` `SYSTEM_REROUTE` or, for a deactivation cascade, `SYSTEM_DEACTIVATION`, while when `reroute` is false the released units become the demand lines' `cancelled_units`; a customer notification is emitted; the order's `routing_status` and `fulfillment_status` are re-derived; and the assignment's `version` increments."

        Design: Corner/entities/immutable_child_rows_expose_no_version_and_no_write_route
        """
        ctx = _cancelled_committed_order()
        assignment = ctx["assignment"]

        rows = find_assignment_lines(assignment["id"])
        assert len(rows) == 1, (
            f"one demand line was served, so one assignment line exists, got {len(rows)}"
        )
        line = read_assignment_line(rows[0]["id"])
        assert_assignment_line(line)

        assert line["assignment_id"] == assignment["id"], (
            "the row names its owning assignment"
        )
        assert line["order_line_id"] == ctx["line"]["id"], (
            "the row names the demand line it serves"
        )
        assert line["units_assigned"] == 2, (
            f"units_assigned is immutable after creation, got {line['units_assigned']}"
        )
        assert line["units_picked"] == 0, (
            f"nothing was picked before the cancel, got {line['units_picked']}"
        )
        assert line["units_cancelled"] == 2, (
            "the cancel sets units_cancelled to units_assigned minus units_picked = 2, "
            f"got {line['units_cancelled']}"
        )
        assert "version" not in line, (
            "an AssignmentLine is append-only and carries no version field"
        )
        assert "updated_at" not in line, (
            "an AssignmentLine is append-only and carries no updated_at field"
        )

    def test_routing_candidate_read_carries_no_version(self):
        """PRD §2.5: "Three resources are append-only records rather than mutable state and therefore carry only `id` and `created_at` — both `updated_at` and `version` are absent from `RoutingCandidate`, from `AssignmentLine` and from `CustomerNotification`."
        PRD §3.4: "Within each iteration every node in the network is evaluated in ascending node `created_at` order, and every evaluation is persisted as a candidate row carrying `routing_run_id`, `store_id` and the 1-based `iteration` in which it happened."
        PRD §3.4: "Its `coverage_units` is the smallest of four numbers: its promise-able units, its capacity units left, its labour units left, and the total remaining demand."
        PRD §3.4: "`coverage_ratio` is `coverage_units` divided by the total remaining demand, rounded half-up to four decimal places."
        PRD §3.4: "The winner's `selected` flag is set to true and its `assigned_units` is set equal to its `coverage_units`."

        Design: Corner/entities/immutable_child_rows_expose_no_version_and_no_write_route
        """
        ctx = _cancelled_committed_order()
        run_id = ctx["run"]["id"]

        rows = find_routing_candidates(routing_run_id=run_id)
        assert len(rows) == 1, (
            "one node evaluated in one iteration persists one candidate row, got "
            f"{len(rows)}"
        )
        candidate = validate_success(
            api_client.get_routing_candidate(rows[0]["id"], PLANNER)
        )
        assert_routing_candidate(candidate)

        assert candidate["routing_run_id"] == run_id, "the row names its routing run"
        assert candidate["store_id"] == ctx["store"]["id"], (
            "the row names the node it evaluated"
        )
        assert candidate["iteration"] == 1, (
            f"the only evaluation happened in iteration 1, got {candidate['iteration']}"
        )
        assert candidate["eligible"] is True, (
            "the sole node passes all eight eligibility clauses"
        )
        assert candidate["coverage_units"] == 2, (
            "coverage_units is the smallest of promise-able 18, capacity 120, labour "
            f"156 and remaining demand 2, got {candidate['coverage_units']}"
        )
        assert candidate["coverage_ratio"] == pytest.approx(1.0000, abs=0.01), (
            "coverage_ratio is 2 / 2, got " f"{candidate['coverage_ratio']}"
        )
        assert candidate["selected"] is True, (
            "the only eligible candidate covers the whole demand and wins"
        )
        assert candidate["assigned_units"] == 2, (
            f"the winner's assigned_units equals its coverage_units, got "
            f"{candidate['assigned_units']}"
        )
        assert "version" not in candidate, (
            "a RoutingCandidate is append-only and carries no version field"
        )
        assert "updated_at" not in candidate, (
            "a RoutingCandidate is append-only and carries no updated_at field"
        )

    def test_customer_notification_read_carries_no_version(self):
        """PRD §2.5: "Three resources are append-only records rather than mutable state and therefore carry only `id` and `created_at` — both `updated_at` and `version` are absent from `RoutingCandidate`, from `AssignmentLine` and from `CustomerNotification`."
        PRD §3.2: "A full cancel moves `fulfillment_status` from `PENDING` to `CANCELLED`, cancels every non-terminal assignment of the order with cancellation reason `CUSTOMER_REQUEST` and no reroute, turns all released units into each line's `cancelled_units` so that every line ends with `open_units` 0 and `line_status` `CANCELLED`, releases each affected node's inventory reservations along with its `units_committed_epoch` and `reserved_labor_minutes`, recomputes each affected node's `eligibility_score`, emits exactly one customer notification of type `CANCELLATION_FULL`, leaves `final_cost_cents` null, recomputes `provisional_cost_cents` and `cost_index_bps`, and increments the order's `version`."
        PRD §3.7: "It carries a `channel` of `EMAIL` or `SMS`, defaulting to `EMAIL`, a `units_affected` count of the units the event moved or removed, a `sent_at_utc` clock instant, and a `body_summary` — a templated one-line summary containing the order's `order_code`, the `notification_type` and the `units_affected` count."
        PRD §3.7: "A notification records the `order_id` it concerns and, for assignment-level events, the `assignment_id` that triggered it; for order-level events `assignment_id` is null."

        Design: Corner/entities/immutable_child_rows_expose_no_version_and_no_write_route
        """
        ctx = _cancelled_committed_order()
        order_id = ctx["order"]["id"]

        rows = find_notifications(order_id=order_id)
        assert len(rows) == 1, (
            f"a full cancel emits exactly one notification, got {len(rows)}"
        )
        notification = validate_success(api_client.get_notification(rows[0]["id"], CARE))
        assert_customer_notification(notification)

        assert notification["order_id"] == order_id, "the row names the order it concerns"
        assert notification["notification_type"] == "CANCELLATION_FULL", (
            "a customer order cancel whose cancelled units equal total_units notifies "
            f"CANCELLATION_FULL, got {notification['notification_type']}"
        )
        assert notification["units_affected"] == 2, (
            f"the cancel removed the order's 2 units, got {notification['units_affected']}"
        )
        assert notification["channel"] == "EMAIL", (
            f"channel defaults to EMAIL, got {notification['channel']}"
        )
        assert "version" not in notification, (
            "a CustomerNotification is append-only and carries no version field"
        )
        assert "updated_at" not in notification, (
            "a CustomerNotification is append-only and carries no updated_at field"
        )
