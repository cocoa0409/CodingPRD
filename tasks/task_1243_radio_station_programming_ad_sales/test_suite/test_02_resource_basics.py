"""Resource basics: creation defaults, system-managed fields, not-found,
listing/pagination, initial states, and order fulfillment counters
(PRD §2.3, §2.5, §2.10, §3.1, §3.4, §4)."""
from test_helpers import (
    DATE_MON,
    MGR,
    NON_EXISTENT_UUID,
    REP,
    TD,
    ApiErrorId,
    assert_station,
    book_spot_ok,
    create_clearance,
    create_clearance_payload,
    create_log,
    create_log_payload,
    create_order,
    create_order_payload,
    create_remote_event_payload,
    create_station,
    create_station_payload,
    get_success_data,
    import_as_run_ok,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_headers,
    make_sales_rep_headers,
    setup_bookable_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_station_create_applies_defaults_and_system_fields(api):
    """PRD §3.1: "an optional `default_share_fallback` (used by ratings lookup
    when no published ratings book covers an air date; when omitted it defaults
    to 1.0)". PRD §2.5: "`id` is a server-minted UUID with no type prefix."

    Design: Corner/entities/station_create_applies_defaults_and_system_fields
    """
    resp = api.create_station({"call_sign": "KAAA", "market_name": "Metro"}, MGR)
    data = validate_success(resp, expected_status=201)
    assert data["default_share_fallback"] == 1.0, "omitted fallback defaults to 1.0"
    assert is_valid_uuid(data.get("id", "")), "id is server-minted"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at present"
    # version is system-managed (PRD §2.5); exact initial value is not pinned
    # by the PRD, so assert presence and integer type only.
    assert isinstance(data.get("version"), int)


def test_station_create_system_fields_input_ignored(api):
    """PRD §2.5: "`version` is a system-managed integer incremented on every
    mutation, used for optimistic concurrency control." A client-supplied
    version in the create payload is never honored.

    Design: Corner/entities/station_create_system_fields_input_ignored
    """
    resp = api.create_station(
        {"call_sign": "KAAA", "market_name": "Metro", "version": 99}, MGR
    )
    data = validate_success(resp, expected_status=201)
    assert data["version"] != 99, "client-supplied version must be ignored"
    assert_station(data)


def test_station_create_missing_required_returns_400(api):
    """PRD §3.1: "A `SalesManager` establishes a Station by supplying its
    `call_sign`, `market_name`, and an optional `default_share_fallback`" —
    `market_name` is required. PRD §2.8 places "request well-formedness
    (`ERR_BAD_REQUEST`)" first in validation order.

    Design: Corner/entities/station_create_missing_required_returns_400
    """
    resp = api.create_station({"call_sign": "KAAA"}, MGR)
    validate_error(resp, ApiErrorId.ERR_BAD_REQUEST)


def test_spot_get_not_found_returns_404(api):
    """PRD §2.10: "Path identifiers and body foreign-key references (for example
    `station_id`, `order_id`, `log_id`, `clearance_id`, `contract_id`,
    `category_id`, `event_id`, `trade_agreement_id`, `spot_id`) are validated
    for existence left-to-right; the first missing reference is rejected with
    `ERR_NOT_FOUND` before any further validation runs."

    Design: Corner/entities/spot_get_not_found_returns_404
    """
    resp = api.get_spot("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", TD)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_spots_list_filter_and_paginate(api):
    """PRD §2.3: "The `limit` parameter specifies the maximum number of items
    returned and defaults to 10, with a minimum of 1 and a maximum of 100. The
    `offset` parameter specifies how many items to skip and defaults to 0."
    and "Paginated list responses include `limit`, `offset`, `total_count`,
    and `has_more` inside the response's `meta` object."

    Design: Corner/entities/spots_list_filter_and_paginate
    """
    env = setup_bookable_scenario(units=3)
    order_id = env["order"]["id"]
    log_id = env["log"]["id"]
    book_spot_ok(order_id, log_id)
    book_spot_ok(order_id, log_id)
    book_spot_ok(order_id, log_id)

    page1, meta1 = validate_paginated(
        api.list_spots(TD, params={"order_id": order_id, "limit": 2, "offset": 0})
    )
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api.list_spots(TD, params={"order_id": order_id, "limit": 2, "offset": 2})
    )
    assert len(page2) == 1
    assert meta2["has_more"] is False

    ids1 = {s["id"] for s in page1}
    ids2 = {s["id"] for s in page2}
    assert ids1.isdisjoint(ids2), "pages must not repeat items"


def test_order_computed_units_reconciled_after_import(api):
    """PRD §3.4: "Two counters summarize fulfillment: `units_scheduled` counts
    the order's spots in `SCHEDULED` or `AIRED` (make-good successors
    excluded), and `units_aired` counts the spots in `AIRED`."

    Design: Corner/entities/order_computed_units_reconciled_after_import
    """
    env = setup_bookable_scenario(units=2)
    order_id = env["order"]["id"]
    log_id = env["log"]["id"]
    s1 = book_spot_ok(order_id, log_id)
    book_spot_ok(order_id, log_id)

    pre = get_success_data(api.get_order(order_id, TD))
    assert pre["units_scheduled"] == 2, "both SCHEDULED before import"

    import_as_run_ok(log_id, aired_spot_ids=[s1["id"]])

    post = get_success_data(api.get_order(order_id, TD))
    assert post["units_scheduled"] == 1, "MAKE_GOOD_PENDING spot excluded from scheduled count"
    assert post["units_aired"] == 1, "only the listed spot is AIRED"


def test_entity_initial_states_on_create(api):
    """PRD §4: "Create an advertising order (DRAFT)", "Create a daily log
    (DRAFT); unique per (station, log_date)", "Create a syndication clearance
    (PENDING)", "Create a remote broadcast sponsorship package (PLANNED)".

    Design: Corner/state_machines/entity_initial_states_on_create
    """
    station = create_station()
    order = create_order(station["id"], rep_user_id="rep-1")
    assert order["status"] == "DRAFT"

    log = create_log(station["id"], log_date=DATE_MON)
    assert log["posture"] == "DRAFT"

    clearance = create_clearance(station["id"])
    assert clearance["status"] == "PENDING"

    event = get_success_data(
        api.create_remote_event(
            create_remote_event_payload(station["id"]), make_sales_rep_headers("rep-1")
        )
    )
    assert event["status"] == "PLANNED"
