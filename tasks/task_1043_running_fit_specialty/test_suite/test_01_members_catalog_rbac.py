"""Member registration, catalog creation, reverse-lookup reads, OCC, RBAC denials,
and not-found errors."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID,
    assert_member, assert_product,
    TEST_USERS, make_member_headers,
    fixtures as fx,
)
import test_helpers.factories as f

SM = TEST_USERS["store_manager_headers"]
ANON = TEST_USERS["anonymous_headers"]


def test_register_member_mints_defaults(api):
    """PRD §3.1: "A freshly registered member starts with `loyalty_points` of 0,
    a `loyalty_tier` of `BRONZE`, `wallet_credit_cents` of 0, and `version` 1."

    Design: Corner/entities/create_member_mints_system_fields_and_defaults
    """
    data = validate_success(api.create_member(f.create_member_payload(email="new@x.com", full_name="New M"), ANON), 201)
    assert_member(data)
    assert data["loyalty_points"] == 0
    assert data["loyalty_tier"] == "BRONZE"
    assert data["wallet_credit_cents"] == 0
    assert data["version"] == 1


def test_create_product_initializes_stock_reserved_zero(api):
    """PRD §3.9: "The system also tracks `stock_reserved`, the units held by
    placed-but-not-yet-fulfilled orders, which initializes to 0 at creation and is
    never negative"

    Design: Corner/entities/create_product_initializes_stock_reserved_zero
    """
    data = validate_success(
        api.create_product(f.create_product_payload(sku="P-1", category="GEAR", name="Cap", price_cents=2000, stock_on_hand=10), SM),
        201,
    )
    assert_product(data)
    assert data["stock_on_hand"] == 10
    assert data["stock_reserved"] == 0


def test_shoepair_copies_reminder_threshold(api):
    """PRD §3.8: "On creation the pair copies the product's `max_mileage_km` into
    its own `reminder_threshold_km`, starts with `total_mileage_km` of 0 and an
    empty `run_logs`, and opens in `ACTIVE` status."

    Design: Corner/entities/shoepair_copies_reminder_threshold_from_product
    """
    member = fx.new_member(api)
    product = fx.new_product(api, sku="SHOE-2", category="SHOE", name="Racer", price_cents=18000, stock_on_hand=5, max_mileage_km=800)
    data = validate_success(
        api.create_shoe_pair(f.create_shoe_pair_payload(member["id"], product["id"]), make_member_headers(member["id"])),
        201,
    )
    assert data["reminder_threshold_km"] == 800
    assert data["total_mileage_km"] == 0
    assert data["status"] == "ACTIVE"


def test_list_staff_for_store_returns_array(api):
    """PRD §3.9: "A store's staff roster can be read back by staff or managers."
    PRD §2.9: "Several collections expose reverse-lookup reads: a store's staff
    roster, a member's subscriptions, and filtered lists of appointments"

    Design: Corner/endpoints/list_staff_for_store_returns_array_envelope
    """
    store = fx.new_store(api)
    staff = fx.new_staff(api, store["id"], role_type="BOTH")
    data, meta = validate_paginated(api.list_store_staff(store["id"], SM))
    assert len(data) == 1
    assert data[0]["id"] == staff["id"]


def test_list_orders_by_member_paginated(api):
    """PRD §2.3: "Each list response reports `limit`, `offset`, `total_count` (the
    total number of matching records before pagination), and `has_more` (true when
    records remain beyond the current page) inside the `meta` object."
    PRD §2.9: "filtered lists of ... orders (by `member_id`)"

    Design: Corner/endpoints/list_orders_by_member_paginated
    """
    member = fx.new_member(api)
    fx.new_cart_order(api, member["id"])
    data, meta = validate_paginated(
        api.list_orders(make_member_headers(member["id"]), params={"member_id": member["id"]})
    )
    assert meta["total_count"] == 1
    assert meta["has_more"] is False


def test_subscription_create_stale_member_version_rejected(api):
    """PRD §2.7: "If `expected_member_version` does not equal the member's current
    `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412),
    preventing the client from superseding a subscription state it never observed."

    Design: Corner/cross_cutting_complexity_layers/subscription_create_stale_member_version_conflict
    """
    member = fx.new_member(api)
    stale_version = member["version"]
    hdr = make_member_headers(member["id"])
    # First create with the observed version succeeds and advances Member.version.
    fx.new_subscription(api, member["id"], stale_version, tier="CLUB_BASIC")
    # Second create off the now-stale version is a supersede race.
    resp = api.create_subscription(member["id"], f.create_subscription_payload(stale_version, tier="CLUB_PRO"), hdr)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)


def test_get_missing_member_returns_not_found(api):
    """PRD §2.9: "Path parameters are validated left-to-right: for a nested path,
    each id segment must resolve to an existing resource before the next is
    considered, and the first unresolved id determines the 404."

    Design: Corner/errors/get_missing_member_returns_not_found
    """
    resp = api.get_member(NON_EXISTENT_UUID, SM)
    validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_FOUND, 404)


def test_register_on_missing_event_returns_not_found(api):
    """PRD §2.8: "existence of every id referenced in the path and in foreign-key
    body fields is checked left-to-right, yielding the resource-specific not-found
    error (404) for the first unresolved id."

    Design: Corner/errors/register_on_missing_event_returns_not_found
    """
    member = fx.new_member(api)
    resp = api.create_registration(NON_EXISTENT_UUID, f.create_registration_payload(member["id"]), make_member_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_EVENT_NOT_FOUND, 404)


def test_member_cannot_create_product(api):
    """PRD §2.1: "When the headers are present and valid but the role is not
    permitted to perform the requested operation — or an owner-scoped role acts on
    a resource it does not own — the request is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)."

    Design: Corner/rbac/member_cannot_create_product
    """
    member = fx.new_member(api)
    resp = api.create_product(
        f.create_product_payload(sku="X-1", category="GEAR", name="X", price_cents=100, stock_on_hand=1),
        make_member_headers(member["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)


def test_member_cannot_fulfill_order(api):
    """PRD §2.1: "When the headers are present and valid but the role is not
    permitted to perform the requested operation — or an owner-scoped role acts on
    a resource it does not own — the request is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)."

    Design: Corner/rbac/member_cannot_fulfill_order_staff_only
    """
    member = fx.new_member(api)
    product = fx.new_product(api, sku="FF-1", category="GEAR", name="Y", price_cents=1000, stock_on_hand=5)
    order = fx.new_placed_order(api, member["id"], product["id"], qty=1)
    resp = api.fulfill_order(order["id"], make_member_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)
