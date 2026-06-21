"""Entity creation, defaults, body validation, listing/pagination, RBAC, not-found.

Citations trace to PRD §2.1, §2.3, §2.6, §3.1, §3.3, §3.9.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID,
    create_zone, create_rider, create_driver, create_quest, request_trip,
    TEST_USERS, make_rider_headers, anonymous_headers,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]


def test_create_zone_returns_201_with_defaults(api):
    """PRD §3.1: "On creation, a zone's `open_demand_count` and `available_supply_count`
    both start at 0, its `current_multiplier` starts at 1.00, and its `heat_level`
    starts at `COOL`."
    PRD §2.4: "`version` — an integer that starts at its initial value and increments by
    one on each modification."

    Design: Corner/entities/create_zone_returns_201_with_defaults
    """
    z = validate_success(api.create_zone(
        {"name": "Z1", "grid_code": "A1", "base_fare_cents": 1000}, DISPATCHER), 201)
    assert z["open_demand_count"] == 0
    assert z["available_supply_count"] == 0
    assert z["current_multiplier"] == 1.00
    assert z["heat_level"] == "COOL"
    assert z["version"] == 1


def test_create_zone_is_airport_default_false(api):
    """PRD §3.1: "The `is_airport` flag defaults to false; airport zones use FIFO queue
    dispatch instead of nearest-driver matching."

    Design: Corner/entities/create_zone_is_airport_default_false
    """
    z = validate_success(api.create_zone(
        {"name": "Z2", "grid_code": "A2", "base_fare_cents": 1000}, DISPATCHER), 201)
    assert z["is_airport"] is False


def test_get_zone_not_found_returns_404(api):
    """PRD §2.6: "The first identifier that does not resolve to an existing resource
    causes the request to be rejected with `ERR_NOT_FOUND`, before any deeper validation
    runs."

    Design: Corner/entities/get_zone_not_found_returns_404
    """
    resp = api.get_zone(NON_EXISTENT_UUID, DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_create_zone_missing_base_fare_returns_invalid_request(api):
    """PRD §2.10: "a request whose body is missing a required field, carries an
    out-of-range enum, or violates a declared numeric constraint (such as a base fare
    below the minimum, a quest target below one, or a negative observed count) is
    rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_zone_missing_base_fare_returns_invalid_request
    """
    resp = api.create_zone({"name": "Z3", "grid_code": "A3"}, DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_zone_base_fare_below_min_returns_invalid_request(api):
    """PRD §3.1: "The `base_fare_cents` is the fare charged before any surge multiplier
    and must be at least 100 cents."
    PRD §2.10: "violates a declared numeric constraint (such as a base fare below the
    minimum ...) is rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_zone_base_fare_below_min_returns_invalid_request
    """
    resp = api.create_zone({"name": "Z4", "grid_code": "A4", "base_fare_cents": 50}, DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_duplicate_grid_code_returns_conflict(api):
    """PRD §3.1: "it must be unique across all zones; an attempt to create a zone whose
    `grid_code` duplicates an existing one is rejected with `ERR_DUPLICATE_GRID_CODE`."

    Design: Corner/entities/duplicate_grid_code_returns_conflict
    """
    create_zone(grid_code="A1", base_fare_cents=1000)
    resp = api.create_zone({"name": "dup", "grid_code": "A1", "base_fare_cents": 2000}, DISPATCHER)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_GRID_CODE.value)


def test_rider_wallet_default_zero(api):
    """PRD §3.1: "The wallet balance is a prepaid balance in cents that defaults to 0 and
    may never be negative."

    Design: Corner/entities/rider_wallet_default_zero
    """
    z = create_zone(grid_code="C1", base_fare_cents=1000)
    rider = validate_success(api.create_rider(
        {"name": "R1", "home_zone_id": z["id"]}, DISPATCHER), 201)
    assert rider["wallet_balance_cents"] == 0


def test_driver_current_zone_initialized_to_home(api):
    """PRD §3.1: "The driver's `current_zone_id` — the cell the driver currently occupies
    — is initialized to the `home_zone_id` at onboarding. A driver also carries a
    `status` that starts at `OFFLINE`"

    Design: Corner/entities/driver_current_zone_initialized_to_home
    """
    z = create_zone(grid_code="D1", base_fare_cents=1000)
    driver = validate_success(api.create_driver(
        {"name": "D1", "home_zone_id": z["id"]}, DISPATCHER), 201)
    assert driver["current_zone_id"] == z["id"]
    assert driver["status"] == "OFFLINE"


def test_list_zones_pagination_envelope(api):
    """PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope."

    Two zones with limit=1 -> total_count 2 and has_more true.

    Design: Corner/endpoints/list_zones_pagination_envelope
    """
    create_zone(grid_code="S1", base_fare_cents=1000)
    create_zone(grid_code="S2", base_fare_cents=1000)
    data, meta = validate_paginated(api.list_zones(DISPATCHER, params={"limit": 1, "offset": 0}))
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


def test_list_trips_filter_by_rider(api):
    """PRD §3.3: "Trips may be listed and filtered by `rider_id`, `driver_id`,
    `pickup_zone_id`, `dropoff_zone_id`, and `status`."

    Design: Corner/endpoints/list_trips_filter_by_rider
    """
    z = create_zone(grid_code="T1", base_fare_cents=1000)
    rider = create_rider(z["id"], wallet_balance_cents=0)
    trip = request_trip(rider["id"], z["id"], z["id"])
    data, _meta = validate_paginated(
        api.list_trips(make_rider_headers(rider["id"]), params={"rider_id": rider["id"]}))
    ids = [t["id"] for t in data]
    assert trip["id"] in ids
    assert all(t["rider_id"] == rider["id"] for t in data)


def test_list_quests_filter_by_driver(api):
    """PRD §3.9: "Quests may be listed and filtered by `driver_id` and `status`."

    Design: Corner/endpoints/list_quests_filter_by_driver
    """
    z = create_zone(grid_code="U1", base_fare_cents=1000)
    driver = create_driver(z["id"])
    quest = create_quest(driver["id"], target_trips=3, bonus_cents=5000,
                         window_start="2026-06-01T00:00:00Z", window_end="2026-06-01T05:00:00Z")
    data, _meta = validate_paginated(api.list_quests(DISPATCHER, params={"driver_id": driver["id"]}))
    ids = [q["id"] for q in data]
    assert quest["id"] in ids
    assert all(q["driver_id"] == driver["id"] for q in data)


def test_rider_cannot_publish_surge_snapshot(api):
    """PRD §2.1: "When the header is present and valid but the role is not permitted to
    perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`."

    A Rider calling the Dispatcher-only surge-snapshot publish is rejected.

    Design: Corner/rbac/rider_cannot_publish_surge_snapshot
    """
    z = create_zone(grid_code="V1", base_fare_cents=1000)
    rider = create_rider(z["id"], wallet_balance_cents=0)
    resp = api.create_surge_snapshot(
        z["id"],
        {"observed_demand": 4, "observed_supply": 2, "is_rush_hour": False,
         "effective_from": "2026-06-01T00:00:00Z", "effective_to": "2026-06-01T01:00:00Z",
         "expected_zone_version": z["version"]},
        make_rider_headers(rider["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value)


def test_missing_role_header_returns_unauthenticated(api):
    """PRD §2.1: "If `X-User-Role` is missing or is not one of these three known roles,
    the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/rbac/missing_role_header_returns_unauthenticated
    """
    resp = api.list_trips(anonymous_headers())
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
