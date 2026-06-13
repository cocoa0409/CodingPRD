"""Access control and validation precedence:
- role denial, ownership denial, missing user context
- priority-pair conflicts (auth-vs-state, owner-vs-delivery-state)
- business validations (restaurant closed, item unavailable, tip rules,
  deactivation with active orders).
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    api_client, ApiErrorId,
    build_user_headers,
    make_admin_headers, make_customer_headers, make_dasher_headers,
    make_restaurant_headers,
    create_zone_payload,
    create_zone, create_restaurant, create_menu_item, create_customer, create_dasher,
    place_simple_order, dispatch, setup_market, setup_order_picked_up,
    setup_order_delivered,
)

ADMIN = make_admin_headers()


# ===========================================================================
# Corner: rbac
# ===========================================================================
def test_dasher_cannot_place_order_role_denied(api):
    """PRD §2.1: "When an authenticated user attempts an operation their role is not permitted to perform, the request is rejected with `ERR_UNAUTHORIZED_ROLE`."
    Placing an order is Customer-only (PRD §4 endpoint table: POST /orders →
    Customer).

    Design: Corner/rbac/dasher_cannot_place_order_role_denied
    """
    zone = create_zone()
    restaurant = create_restaurant(zone["id"])
    item = create_menu_item(restaurant["id"])
    dasher = create_dasher(zone["id"])
    customer = create_customer()
    resp = api_client.create_order(
        {"customer_id": customer["id"], "restaurant_id": restaurant["id"],
         "line_items": [{"menu_item_id": item["id"], "quantity": 1}]},
        make_dasher_headers(dasher["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE.value)


def test_customer_cannot_cancel_other_customers_order(api):
    """PRD §2.1: "When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of the acting customer. Ownership checks compare an order's `customer_id` against `X-User-ID`."
    and "an entity-backed user that tries to act on a resource it does not own is rejected with `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/rbac/customer_cannot_cancel_other_customers_order
    """
    zone = create_zone()
    restaurant = create_restaurant(zone["id"])
    item = create_menu_item(restaurant["id"])
    cust1 = create_customer(name="Cara")
    cust2 = create_customer(name="Cyrus")
    order = place_simple_order(cust1["id"], restaurant["id"], item["id"])
    resp = api_client.cancel_order(order["id"], make_customer_headers(cust2["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


def test_missing_user_context_header_rejected(api):
    """PRD §2.1: "If either header is missing or carries an invalid value, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

    Design: Corner/rbac/missing_user_context_header_rejected
    """
    bad_headers = {"X-User-ID": "someone", "X-User-Role": "Anonymous",
                   "Content-Type": "application/json"}
    resp = api_client.create_zone(create_zone_payload(name="X"), bad_headers)
    validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)


# ===========================================================================
# priority_pair_validation_conflict — auth-role (p2) vs state (p5)
# ===========================================================================
class TestRoleVsStateConflict:
    def test_wrong_role_dispatch_returns_role_error_not_state(self, api):
        """PRD §2.7: "(2) the acting role must be permitted for the operation, else `ERR_UNAUTHORIZED_ROLE`"
        PRD §2.7: "(5) the target order must be in the correct `fulfillment_status` or `billing_status` for the operation"

        A Customer (wrong role for dispatch) targeting a DELIVERED (wrong state)
        order fails the role check first -> 403 ERR_UNAUTHORIZED_ROLE.

        Design: Difficulty/priority_pair_validation_conflict/role_vs_state_conflict_on_dispatch_rejected
        """
        ctx = setup_order_delivered()
        order = ctx["order"]
        customer = ctx["customer"]
        resp = api_client.dispatch_order(
            order["id"], {"expected_order_version": order["version"]},
            make_customer_headers(customer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE.value, expected_status=403)

    def test_role_check_precedes_state_check_priority_order(self, api):
        """PRD §2.7: "they are evaluated in a fixed priority so that the returned
        error is deterministic."

        Re-asserts the 403 role error (not the 409 state error) is returned when
        both a wrong role and a wrong order state apply.

        Design: Difficulty/priority_pair_validation_conflict/role_vs_state_conflict_on_dispatch_rejected
        """
        ctx = setup_order_delivered()
        order = ctx["order"]
        customer = ctx["customer"]
        resp = api_client.dispatch_order(
            order["id"], {"expected_order_version": order["version"]},
            make_customer_headers(customer["id"]),
        )
        assert resp.status_code == 403, \
            f"role error must take priority (403), got {resp.status_code}"
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE.value)


# ===========================================================================
# priority_pair_validation_conflict — owner (p4) vs delivery-state (p6)
# ===========================================================================
class TestOwnerVsDeliveryStateConflict:
    def _setup_en_route_with_intruder(self):
        """Order taken to PICKED_UP (Delivery EN_ROUTE) by dasher A; a second
        OFFLINE dasher B exists as a non-owner intruder."""
        zone, restaurant, item, dasher_a, customer = setup_market(
            dasher_overrides={"name": "DanA", "max_batch_size": 1})
        dasher_b = create_dasher(zone["id"], name="DanB", max_batch_size=5,
                                 availability="OFFLINE")
        order = place_simple_order(customer["id"], restaurant["id"], item["id"], tip_cents=0)
        delivery = dispatch(order["id"], restaurant["id"], order["version"])
        dha = make_dasher_headers(dasher_a["id"])
        validate_success(api_client.accept_delivery(delivery["id"], dha))
        validate_success(api_client.pickup_delivery(delivery["id"], dha))
        return delivery["id"], dasher_b["id"]

    def test_non_owner_accept_returns_owner_error_not_state(self, api):
        """PRD §2.7: "(4) an entity-backed caller must own the resource it is mutating, else `ERR_NOT_RESOURCE_OWNER`"
        PRD §2.7: "(6) any target delivery, order issue, or earnings record must be in the correct state"

        A non-owner dasher accepting an EN_ROUTE delivery fails the ownership
        check first -> 403 ERR_NOT_RESOURCE_OWNER (not the 409 state error).

        Design: Difficulty/priority_pair_validation_conflict/owner_vs_delivery_state_conflict_on_accept_rejected
        """
        delivery_id, intruder_id = self._setup_en_route_with_intruder()
        resp = api_client.accept_delivery(delivery_id, make_dasher_headers(intruder_id))
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, expected_status=403)

    def test_owner_check_precedes_delivery_state_check(self, api):
        """PRD §2.7: "(4) an entity-backed caller must own the resource it is mutating, else `ERR_NOT_RESOURCE_OWNER`"
        PRD §2.7: "(6) any target delivery, order issue, or earnings record must be in the correct state"

        Re-asserts the 403 ownership error wins over the 409 delivery-state error.

        Design: Difficulty/priority_pair_validation_conflict/owner_vs_delivery_state_conflict_on_accept_rejected
        """
        delivery_id, intruder_id = self._setup_en_route_with_intruder()
        resp = api_client.accept_delivery(delivery_id, make_dasher_headers(intruder_id))
        assert resp.status_code == 403
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


# ===========================================================================
# Corner: validations
# ===========================================================================
def test_place_order_restaurant_closed_rejected(api):
    """PRD §3.4: "At placement the restaurant must be open and every ordered menu item must be available, `LISTED`, and actually belong to the named restaurant; any violation is rejected with `ERR_ITEM_UNAVAILABLE`."

    Design: Corner/validations/place_order_restaurant_closed_rejected
    """
    zone = create_zone()
    restaurant = create_restaurant(zone["id"], is_open=False)
    item = create_menu_item(restaurant["id"])
    customer = create_customer()
    resp = api_client.create_order(
        {"customer_id": customer["id"], "restaurant_id": restaurant["id"],
         "line_items": [{"menu_item_id": item["id"], "quantity": 1}]},
        make_customer_headers(customer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ITEM_UNAVAILABLE.value)


def test_place_order_unavailable_item_rejected(api):
    """PRD §3.4: "At placement the restaurant must be open and every ordered menu item must be available, `LISTED`, and actually belong to the named restaurant; any violation is rejected with `ERR_ITEM_UNAVAILABLE`."

    Design: Corner/validations/place_order_unavailable_item_rejected
    """
    zone = create_zone()
    restaurant = create_restaurant(zone["id"], is_open=True)
    item = create_menu_item(restaurant["id"], name="SoldOut", available=False)
    customer = create_customer()
    resp = api_client.create_order(
        {"customer_id": customer["id"], "restaurant_id": restaurant["id"],
         "line_items": [{"menu_item_id": item["id"], "quantity": 1}]},
        make_customer_headers(customer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ITEM_UNAVAILABLE.value)


def test_tip_adjustment_below_zero_rejected(api):
    """PRD §3.10: "The delta is added to the order's `tip_cents` and may be negative to reduce a tip, but the result may never fall below zero; an adjustment that would drive `tip_cents` below 0 is rejected with `ERR_TIP_NEGATIVE`."

    Tip 100, delta -200 -> would be -100 -> rejected; tip stays 100.

    Design: Corner/validations/tip_adjustment_below_zero_rejected
    """
    zone = create_zone()
    restaurant = create_restaurant(zone["id"])
    item = create_menu_item(restaurant["id"])
    customer = create_customer()
    order = place_simple_order(customer["id"], restaurant["id"], item["id"], tip_cents=100)
    ch = make_customer_headers(customer["id"])
    resp = api_client.adjust_tip(order["id"], {"delta_cents": -200}, ch)
    validate_error(resp, ApiErrorId.ERR_TIP_NEGATIVE.value)
    after = validate_success(api_client.get_order(order["id"], ch))
    assert after["tip_cents"] == 100, "rejected adjustment must leave tip unchanged at 100"


def test_tip_adjustment_after_settlement_window_closed(api):
    """PRD §3.10: "Adjustments are accepted only while the order's `billing_status` is still `UNSETTLED ... an attempt after the billing window has closed is rejected with `ERR_TIP_WINDOW_CLOSED`."

    A DELIVERED order has billing_status SETTLED -> tip adjustment rejected.

    Design: Corner/validations/tip_adjustment_after_settlement_window_closed
    """
    ctx = setup_order_delivered(order_overrides={"tip_cents": 100})
    order = ctx["order"]
    customer = ctx["customer"]
    resp = api_client.adjust_tip(order["id"], {"delta_cents": 50},
                                 make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_TIP_WINDOW_CLOSED.value)


def test_deactivate_restaurant_with_active_order_rejected(api):
    """PRD §3.2: "Deactivating a restaurant ... is permitted only when ... no order for that restaurant is currently in `fulfillment_status` `PLACED`, `ROUTED`, or `PICKED_UP` (otherwise `ERR_RESTAURANT_HAS_ACTIVE_ORDERS`)."

    Design: Corner/validations/deactivate_restaurant_with_active_order_rejected
    """
    zone = create_zone()
    restaurant = create_restaurant(zone["id"])
    item = create_menu_item(restaurant["id"])
    customer = create_customer()
    place_simple_order(customer["id"], restaurant["id"], item["id"])  # PLACED
    resp = api_client.deactivate_restaurant(restaurant["id"],
                                            make_restaurant_headers(restaurant["id"]))
    validate_error(resp, ApiErrorId.ERR_RESTAURANT_HAS_ACTIVE_ORDERS.value)
    after = validate_success(api_client.get_restaurant(restaurant["id"], ADMIN))
    assert after["status"] == "ACTIVE", "restaurant must stay ACTIVE after rejected deactivation"
