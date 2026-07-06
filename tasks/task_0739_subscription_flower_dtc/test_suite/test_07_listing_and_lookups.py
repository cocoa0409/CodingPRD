"""Listing endpoints, pagination, reverse-reachability, and not-found errors on GETs.

Covers corner endpoints and errors instances.
"""
from test_helpers import (
    api_client,
    NON_EXISTENT_UUID,
    TEST_USERS,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
    ApiErrorId,
    setup_plan_customer_subscription,
    get_subscription_shipments,
    create_carrier_route,
    set_clock,
    source_shipment,
    confirm_sourced,
    ship,
    create_customer,
)
from test_helpers.factories import (
    ship_shipment_payload,
    simulate_payment_payload,
    redeem_offer_payload,
)


# =====================================================================
# Corner: shipments_pagination
# =====================================================================


def test_list_subscription_shipments_paginated_returns_meta():
    """PRD §2.3: "The `limit` parameter caps how many items are returned; it defaults to 10, must be at least 1, and may be at most 100. The `offset` parameter counts how many leading items to skip; it defaults to 0 and must be zero or greater."
    PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object, where `total_count` reflects the full number of matching items before pagination and `has_more` indicates whether items remain beyond the returned page."

    WEEKLY subscription has 4 cycle-1 shipments; with limit=2 -> 2 items, total_count=4, has_more=true.

    Design: Corner/endpoints/corner_shipments_pagination
    """
    _plan, _customer, subscription = setup_plan_customer_subscription()
    res = api_client.list_subscription_shipments(
        subscription["id"],
        TEST_USERS["platform_admin_headers"],
        params={"limit": 2, "offset": 0},
    )
    data, meta = validate_paginated(res)
    assert len(data) == 2
    assert meta["total_count"] == 4
    assert meta["has_more"] is True


# =====================================================================
# Corner: invalid_pagination_limit
# =====================================================================


def test_list_with_limit_below_min_returns_invalid_request():
    """PRD §2.3: "A `limit` outside the range of 1 through 100, or a negative `offset`, is a malformed request and is rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/endpoints/corner_invalid_pagination_limit
    """
    _plan, _customer, subscription = setup_plan_customer_subscription()
    res = api_client.list_subscription_shipments(
        subscription["id"], TEST_USERS["platform_admin_headers"], params={"limit": 0}
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


# =====================================================================
# Corner: route_shipments_reverse_reachability
# =====================================================================


def test_route_shipments_list_contains_shipped_shipment():
    """PRD §3.6: "The request names the `route_id` and the `delivery_window_start` and `delivery_window_end` of the booked window; those three values are recorded on the shipment."

    Once a shipment is SHIPPED onto a route, the route's shipments list includes it.

    Design: Corner/endpoints/corner_route_shipments_reverse_reachability
    """
    _plan, _customer, subscription = setup_plan_customer_subscription()
    shipments = get_subscription_shipments(subscription["id"])
    route = create_carrier_route(zone="Z1", service_date="2026-03-10T00:00:00Z")
    set_clock("2026-03-04T12:00:00Z")
    source_shipment(shipments[0]["id"])
    confirm_sourced(shipments[0]["id"], substitution_applied=False)
    ship(shipments[0]["id"], route["id"], "2026-03-10T09:00:00Z", "2026-03-10T10:00:00Z")
    res = api_client.list_carrier_route_shipments(
        route["id"], TEST_USERS["fulfillment_ops_headers"]
    )
    data = validate_success(res)
    ids = [s["id"] for s in data]
    assert shipments[0]["id"] in ids, (
        f"Route's shipment list must include the shipped shipment; got {ids}"
    )


# =====================================================================
# Corner: route_not_found_on_ship
# =====================================================================


def test_ship_with_unknown_route_returns_route_not_found_or_invalid():
    """PRD §2.10: "The first identifier in the path that does not resolve to an existing resource determines the not-found error returned, before any deeper identifier or any body rule is considered. Each entity has its own not-found error: `ERR_CUSTOMER_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_SUBSCRIPTION_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_STEM_LOT_NOT_FOUND`, `ERR_ROUTE_NOT_FOUND`, `ERR_CHARGE_NOT_FOUND`, and `ERR_OFFER_NOT_FOUND`."

    route_id here is in the body, not the path — §2.10 covers only path IDs. A faithful
    reader could raise ERR_ROUTE_NOT_FOUND or reject it as ERR_INVALID_REQUEST; accept either.

    Design: Corner/endpoints/corner_route_not_found_on_ship
    """
    _plan, _customer, subscription = setup_plan_customer_subscription()
    shipments = get_subscription_shipments(subscription["id"])
    set_clock("2026-03-04T12:00:00Z")
    source_shipment(shipments[0]["id"])
    confirm_sourced(shipments[0]["id"], substitution_applied=False)
    res = api_client.ship_shipment(
        shipments[0]["id"],
        ship_shipment_payload(
            route_id=NON_EXISTENT_UUID,
            delivery_window_start="2026-03-10T09:00:00Z",
            delivery_window_end="2026-03-10T10:00:00Z",
        ),
        TEST_USERS["fulfillment_ops_headers"],
    )
    validate_error_is_one_of(
        res,
        [
            ApiErrorId.ERR_ROUTE_NOT_FOUND.value,
            ApiErrorId.ERR_INVALID_REQUEST.value,
        ],
    )


# =====================================================================
# Corner: not-found path IDs (path existence check)
# =====================================================================


def test_source_unknown_shipment_returns_shipment_not_found():
    """PRD §2.10: "The first identifier in the path that does not resolve to an existing resource determines the not-found error returned, before any deeper identifier or any body rule is considered. Each entity has its own not-found error: `ERR_CUSTOMER_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_SUBSCRIPTION_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_STEM_LOT_NOT_FOUND`, `ERR_ROUTE_NOT_FOUND`, `ERR_CHARGE_NOT_FOUND`, and `ERR_OFFER_NOT_FOUND`."

    Design: Corner/errors/corner_shipment_not_found
    """
    res = api_client.source_shipment(
        NON_EXISTENT_UUID, {}, TEST_USERS["fulfillment_ops_headers"]
    )
    validate_error(res, ApiErrorId.ERR_SHIPMENT_NOT_FOUND.value)


def test_simulate_payment_unknown_charge_returns_charge_not_found():
    """PRD §2.10: "Each entity has its own not-found error: `ERR_CUSTOMER_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_SUBSCRIPTION_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_STEM_LOT_NOT_FOUND`, `ERR_ROUTE_NOT_FOUND`, `ERR_CHARGE_NOT_FOUND`, and `ERR_OFFER_NOT_FOUND`."

    Design: Corner/errors/corner_charge_not_found
    """
    res = api_client.simulate_payment(
        NON_EXISTENT_UUID,
        simulate_payment_payload("SUCCEEDED"),
        TEST_USERS["billing_admin_headers"],
    )
    validate_error(res, ApiErrorId.ERR_CHARGE_NOT_FOUND.value)


def test_get_unknown_stem_lot_returns_stem_lot_not_found():
    """PRD §2.10: "Each entity has its own not-found error: `ERR_CUSTOMER_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_SUBSCRIPTION_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_STEM_LOT_NOT_FOUND`, `ERR_ROUTE_NOT_FOUND`, `ERR_CHARGE_NOT_FOUND`, and `ERR_OFFER_NOT_FOUND`."

    Design: Corner/errors/corner_stem_lot_not_found
    """
    res = api_client.get_stem_lot(
        NON_EXISTENT_UUID, TEST_USERS["fulfillment_ops_headers"]
    )
    validate_error(res, ApiErrorId.ERR_STEM_LOT_NOT_FOUND.value)


def test_redeem_unknown_offer_returns_offer_not_found():
    """PRD §2.10: "The first identifier in the path that does not resolve to an existing resource determines the not-found error returned, before any deeper identifier or any body rule is considered. Each entity has its own not-found error: `ERR_CUSTOMER_NOT_FOUND`, `ERR_PLAN_NOT_FOUND`, `ERR_SUBSCRIPTION_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_STEM_LOT_NOT_FOUND`, `ERR_ROUTE_NOT_FOUND`, `ERR_CHARGE_NOT_FOUND`, and `ERR_OFFER_NOT_FOUND`."

    Design: Corner/errors/corner_offer_not_found
    """
    from test_helpers.test_users import make_customer_headers

    customer = create_customer()
    res = api_client.redeem_win_back_offer(
        NON_EXISTENT_UUID,
        redeem_offer_payload(subscription_id=NON_EXISTENT_UUID),
        make_customer_headers(customer["id"]),
    )
    validate_error(res, ApiErrorId.ERR_OFFER_NOT_FOUND.value)
