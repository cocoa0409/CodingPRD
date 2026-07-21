"""BOPIS order validation checks (store match, pickup window, station, slot
buffer, store hours) and role-based access control.
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_customer_headers,
    new_store,
    new_customer,
    new_sku,
    create_order,
    create_order_payload,
    create_sku_payload,
    order_line,
)

ADMIN = TEST_USERS["platform_admin_headers"]
STAFF = TEST_USERS["store_staff_headers"]


def test_order_line_sku_from_other_store_returns_mismatch(api):
    """PRD §3.4: "Every line's SKU must belong to the order's `store_id`; a
    cross-store line is rejected with `ERR_SKU_STORE_MISMATCH`."

    Design: Corner/validations/order_line_sku_from_other_store_returns_mismatch
    """
    s1 = new_store(api, name="S1")
    s2 = new_store(api, name="S2")
    customer = new_customer(api)
    cust = customer["id"]
    sku = new_sku(api, s2["id"], base_price_cents=4000, initial_on_hand_qty=10)
    resp = api.create_order(
        create_order_payload(cust, s1["id"], [order_line(sku["id"], 1)]),
        make_customer_headers(cust),
    )
    validate_error(resp, ApiErrorId.ERR_SKU_STORE_MISMATCH.value)


def test_order_pickup_end_not_after_start_returns_invalid_window(api):
    """PRD §3.4: "The pickup window must be well-formed — `pickup_end` strictly
    after `pickup_start` — or the request is rejected with
    `ERR_INVALID_PICKUP_WINDOW`."

    Design: Corner/validations/order_pickup_end_not_after_start_returns_invalid_window
    """
    store = new_store(api)
    customer = new_customer(api)
    cust = customer["id"]
    sku = new_sku(api, store["id"], base_price_cents=4000, initial_on_hand_qty=10)
    resp = api.create_order(
        create_order_payload(
            cust, store["id"], [order_line(sku["id"], 1)],
            pickup_start="2026-07-01T10:00:00Z", pickup_end="2026-07-01T10:00:00Z",
        ),
        make_customer_headers(cust),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_PICKUP_WINDOW.value)


def test_order_invalid_station_returns_invalid_station(api):
    """PRD §3.4: "The `station_no` must be between 1 and the store's
    `pickup_station_count`, or the request is rejected with
    `ERR_INVALID_STATION`."

    Design: Corner/validations/order_invalid_station_returns_invalid_station
    """
    store = new_store(api, pickup_station_count=2)
    customer = new_customer(api)
    cust = customer["id"]
    sku = new_sku(api, store["id"], base_price_cents=4000, initial_on_hand_qty=10)
    resp = api.create_order(
        create_order_payload(cust, store["id"], [order_line(sku["id"], 1)], station_no=5),
        make_customer_headers(cust),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATION.value)


def test_pickup_window_buffer_conflict_same_station(api):
    """PRD §3.4: "The requested window must not collide with another
    non-cancelled order at the same store and `station_no`: two windows conflict
    when, treated as half-open intervals and expanded by a 15-minute buffer on
    each side, they overlap; a collision is rejected with
    `ERR_PICKUP_SLOT_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/pickup_window_buffer_conflict_same_station
    """
    store = new_store(api, pickup_station_count=2)
    customer = new_customer(api)
    cust = customer["id"]
    sku = new_sku(api, store["id"], base_price_cents=5000, initial_on_hand_qty=100)
    create_order(api, cust, store["id"], [order_line(sku["id"], 1)],
                 pickup_start="2026-07-01T10:00:00Z", pickup_end="2026-07-01T10:30:00Z",
                 station_no=1)
    resp = api.create_order(
        create_order_payload(
            cust, store["id"], [order_line(sku["id"], 1)],
            pickup_start="2026-07-01T10:40:00Z", pickup_end="2026-07-01T11:00:00Z",
            station_no=1,
        ),
        make_customer_headers(cust),
    )
    validate_error(resp, ApiErrorId.ERR_PICKUP_SLOT_CONFLICT.value)


def test_pickup_window_conflict_isolated_per_station(api):
    """PRD §3.4: "The requested window must not collide with another
    non-cancelled order at the same store and `station_no`: two windows conflict
    when, treated as half-open intervals and expanded by a 15-minute buffer on
    each side, they overlap; a collision is rejected with
    `ERR_PICKUP_SLOT_CONFLICT`." — an identical window on a different station
    does not conflict.

    Design: Difficulty/resource_temporal_overlap/pickup_window_buffer_conflict_same_station
    """
    store = new_store(api, pickup_station_count=2)
    customer = new_customer(api)
    cust = customer["id"]
    sku = new_sku(api, store["id"], base_price_cents=5000, initial_on_hand_qty=100)
    create_order(api, cust, store["id"], [order_line(sku["id"], 1)],
                 pickup_start="2026-07-01T10:00:00Z", pickup_end="2026-07-01T10:30:00Z",
                 station_no=1)
    resp = api.create_order(
        create_order_payload(
            cust, store["id"], [order_line(sku["id"], 1)],
            pickup_start="2026-07-01T10:00:00Z", pickup_end="2026-07-01T10:30:00Z",
            station_no=2,
        ),
        make_customer_headers(cust),
    )
    data = validate_success(resp, 201)
    assert data["station_no"] == 2


def test_pickup_outside_hours_beats_invalid_station_after_close(api):
    """PRD §3.4: "The window's time-of-day must fall within the store's trading
    hours, that is between `open_minute` and `close_minute`; a window outside
    those hours is rejected with `ERR_PICKUP_OUTSIDE_HOURS`. The `station_no`
    must be between 1 and the store's `pickup_station_count`, or the request is
    rejected with `ERR_INVALID_STATION`." — hours are checked before the station.

    Design: Difficulty/priority_pair_validation_conflict/pickup_outside_hours_temporal_beats_invalid_station_constraint
    """
    store = new_store(api, pickup_station_count=2)
    customer = new_customer(api)
    cust = customer["id"]
    sku = new_sku(api, store["id"], base_price_cents=5000, initial_on_hand_qty=100)
    resp = api.create_order(
        create_order_payload(
            cust, store["id"], [order_line(sku["id"], 1)],
            pickup_start="2026-07-01T21:00:00Z", pickup_end="2026-07-01T21:30:00Z",
            station_no=5,
        ),
        make_customer_headers(cust),
    )
    validate_error(resp, ApiErrorId.ERR_PICKUP_OUTSIDE_HOURS.value)


def test_pickup_outside_hours_beats_invalid_station_before_open(api):
    """PRD §3.4: "The window's time-of-day must fall within the store's trading
    hours, that is between `open_minute` and `close_minute`; a window outside
    those hours is rejected with `ERR_PICKUP_OUTSIDE_HOURS`. The `station_no`
    must be between 1 and the store's `pickup_station_count`, or the request is
    rejected with `ERR_INVALID_STATION`." — a window before opening also fails
    on hours ahead of the station check.

    Design: Difficulty/priority_pair_validation_conflict/pickup_outside_hours_temporal_beats_invalid_station_constraint
    """
    store = new_store(api, pickup_station_count=2)
    customer = new_customer(api)
    cust = customer["id"]
    sku = new_sku(api, store["id"], base_price_cents=5000, initial_on_hand_qty=100)
    resp = api.create_order(
        create_order_payload(
            cust, store["id"], [order_line(sku["id"], 1)],
            pickup_start="2026-07-01T08:00:00Z", pickup_end="2026-07-01T08:30:00Z",
            station_no=5,
        ),
        make_customer_headers(cust),
    )
    validate_error(resp, ApiErrorId.ERR_PICKUP_OUTSIDE_HOURS.value)


def test_customer_cannot_create_sku_unauthorized(api):
    """PRD §2.1: "If the role is recognized but is not permitted to perform the
    requested operation per the authorization matrix in Section 4, the request
    is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4: `POST /skus` — authorized roles StoreStaff, PlatformAdmin (not Customer).

    Design: Corner/rbac/customer_cannot_create_sku_unauthorized
    """
    store = new_store(api)
    customer = new_customer(api)
    resp = api.create_sku(
        create_sku_payload(store["id"], base_price_cents=4000),
        make_customer_headers(customer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_customer_cannot_pay_another_customers_order(api):
    """PRD §2.1: "When a `Customer` attempts an owner-restricted action on a
    resource whose owner foreign key does not equal `X-User-ID`, the request is
    rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403); the owner-restricted
    actions are activating, archiving, and adding items to a registry, paying
    for or cancelling an order, and cancelling a special order."

    Design: Corner/rbac/customer_cannot_pay_another_customers_order
    """
    store = new_store(api)
    sku = new_sku(api, store["id"], base_price_cents=4000, initial_on_hand_qty=10)
    c1 = new_customer(api)
    c2 = new_customer(api)
    o1 = create_order(api, c1["id"], store["id"], [order_line(sku["id"], 1)])
    resp = api.pay_order(o1["id"], {"payment_method": "CARD"}, make_customer_headers(c2["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


def test_sku_create_missing_auth_role_returns_unauthenticated(api):
    """PRD §2.1: "If a protected endpoint is called without a recognized
    `X-User-Role`, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/rbac/sku_create_missing_auth_role_returns_unauthenticated
    """
    store = new_store(api)
    resp = api.create_sku(
        create_sku_payload(store["id"], base_price_cents=4000),
        TEST_USERS["unknown_role_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)
