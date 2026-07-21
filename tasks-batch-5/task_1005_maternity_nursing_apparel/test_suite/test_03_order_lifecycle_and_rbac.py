"""Order state machine gates and role-based access control."""
from test_helpers import (
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_shopper_headers,
    setup_buyable,
    place_order,
)

AGENT = TEST_USERS["fulfillment_agent_headers"]
GUEST = TEST_USERS["guest_headers"]


def test_fulfill_unpaid_order_rejected(api):
    """PRD §3.5: "It is permitted only when `payment_status` is `PAID` (a fulfill
    attempt on an order that is not paid is rejected with `ERR_ORDER_NOT_PAID`)."

    Design: Corner/state_machines/fulfill_unpaid_order_rejected
    """
    base = setup_buyable(api, buy_price_cents=5000, inventory_on_hand=5, category="NURSING")
    order = place_order(api, base["customer"]["id"], base["variant"]["id"], "BUY", quantity=1)
    resp = api.fulfill_order(order["id"], AGENT)
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_PAID.value)


def test_guest_cannot_create_product(api):
    """PRD §2.1: "When a recognized role attempts an operation it is not permitted
    to perform, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4: the `POST /products` row authorizes only `PlatformAdmin`.

    Design: Corner/rbac/guest_cannot_create_product
    """
    resp = api.create_product({"name": "Sneaky", "category": "MATERNITY",
                               "buy_price_cents": 5000}, GUEST)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_shopper_cannot_fulfill_order(api):
    """PRD §2.1: "When a recognized role attempts an operation it is not permitted
    to perform, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4: the `POST /orders/{id}/fulfill` row authorizes only `FulfillmentAgent`.

    Design: Corner/rbac/shopper_cannot_fulfill_order
    """
    base = setup_buyable(api, buy_price_cents=5000, inventory_on_hand=5, category="NURSING")
    order = place_order(api, base["customer"]["id"], base["variant"]["id"], "BUY", quantity=1)
    resp = api.fulfill_order(order["id"], make_shopper_headers(base["customer"]["id"]))
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_fulfillment_agent_cannot_place_order(api):
    """PRD §2.1: "When a recognized role attempts an operation it is not permitted
    to perform, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4: the `POST /orders` row authorizes only `Shopper`.

    Design: Corner/rbac/fulfillment_agent_cannot_place_order
    """
    base = setup_buyable(api, buy_price_cents=5000, inventory_on_hand=5, category="NURSING")
    resp = api.create_order(
        {"customer_id": base["customer"]["id"], "variant_id": base["variant"]["id"],
         "order_type": "BUY", "expected_variant_version": base["variant"]["version"],
         "quantity": 1},
        AGENT,
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)
