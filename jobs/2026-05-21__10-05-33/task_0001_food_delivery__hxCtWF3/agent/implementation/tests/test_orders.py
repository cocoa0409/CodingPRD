"""Order placement and restaurant-side flow."""
from .client import Client
from .fixtures import setup_basics, place_order


def run(suite):
    def place_minimum_subtotal():
        c, ids = setup_basics()
        # Update price to 50 cents -> two items still = 100 (minimum). Single item = 50, fails.
        # Easier: register a sub-100 price item separately.
        _, mi = c.post(f"/api/restaurants/{ids['rid']}/menu-items",
                       {"name": "cheap", "price_cents": 50},
                       role="PlatformAdmin", user_id="op")
        mid_cheap = mi["data"]["id"]
        s, body = c.post("/api/orders", {
            "customer_id": ids["cid"], "restaurant_id": ids["rid"],
            "items": [{"menu_item_id": mid_cheap, "quantity": 1}],
        }, role="Customer", user_id=ids["cid"])
        assert s == 422
        assert body["data"]["error_id"] == "ERR_ORDER_INVALID"

    def items_must_not_be_empty():
        c, ids = setup_basics()
        s, body = c.post("/api/orders", {
            "customer_id": ids["cid"], "restaurant_id": ids["rid"], "items": [],
        }, role="Customer", user_id=ids["cid"])
        assert s == 422 and body["data"]["error_id"] == "ERR_ORDER_INVALID"

    def quantity_must_be_positive_int():
        c, ids = setup_basics()
        s, body = c.post("/api/orders", {
            "customer_id": ids["cid"], "restaurant_id": ids["rid"],
            "items": [{"menu_item_id": ids["mid"], "quantity": 0}],
        }, role="Customer", user_id=ids["cid"])
        assert s == 422 and body["data"]["error_id"] == "ERR_ORDER_INVALID"

    def restaurant_not_active():
        c, ids = setup_basics()
        # Suspend it
        c.post(f"/api/restaurants/{ids['rid']}/suspend", role="PlatformAdmin", user_id="op")
        s, body = place_order(c, ids)
        assert s == 422
        assert body["data"]["error_id"] == "ERR_RESTAURANT_UNAVAILABLE"

    def unlisted_item():
        c, ids = setup_basics()
        # Unlist the menu item
        c.patch(f"/api/menu-items/{ids['mid']}", {"is_listed": False},
                role="PlatformAdmin", user_id="op")
        s, body = place_order(c, ids)
        assert s == 422 and body["data"]["error_id"] == "ERR_RESTAURANT_UNAVAILABLE"

    def menu_item_belongs_to_other_restaurant():
        c, ids = setup_basics()
        # Build a 2nd restaurant + item
        _, r2 = c.post("/api/restaurants", {"name": "R2", "address": "a", "lat": 0, "lng": 0},
                       role="PlatformAdmin", user_id="op")
        rid2 = r2["data"]["id"]
        c.post(f"/api/restaurants/{rid2}/approve", role="PlatformAdmin", user_id="op")
        _, mi2 = c.post(f"/api/restaurants/{rid2}/menu-items",
                        {"name": "x", "price_cents": 500},
                        role="PlatformAdmin", user_id="op")
        mid2 = mi2["data"]["id"]
        s, body = c.post("/api/orders", {
            "customer_id": ids["cid"], "restaurant_id": ids["rid"],
            "items": [{"menu_item_id": mid2, "quantity": 1}],
        }, role="Customer", user_id=ids["cid"])
        assert s == 422 and body["data"]["error_id"] == "ERR_RESTAURANT_UNAVAILABLE"

    def placement_authorizes_payment():
        c, ids = setup_basics()
        s, body = place_order(c, ids, qty=2)
        assert s == 201
        o = body["data"]
        assert o["status"] == "PLACED"
        assert o["payment_status"] == "AUTHORIZED"
        assert o["subtotal_cents"] == 500 * 2
        assert o["provisional_commission_cents"] == 150  # 1000 * 0.15
        assert o["final_delivery_fee_cents"] is None
        assert o["final_commission_cents"] is None
        assert o["actual_delivery_time"] is None
        assert o["minutes_late"] is None
        assert o["version"] == 1

    def placement_uses_credit_first():
        c, ids = setup_basics()
        # Manually credit the customer via approving + rejecting? Instead seed it through a refund flow.
        # Shortcut: rely on a future test of refunds to verify drawdown end-to-end. Here just verify
        # that credit_used_cents and card_authorized_cents are set on the order.
        s, body = place_order(c, ids, qty=2)
        o = body["data"]
        assert o["credit_used_cents"] == 0
        assert o["card_authorized_cents"] >= o["subtotal_cents"]

    def restaurant_accept_flow():
        c, ids = setup_basics()
        # Register a rider, ensure dispatch can find a candidate
        from .fixtures import register_rider
        register_rider(c)
        _, body = place_order(c, ids, qty=2)
        oid = body["data"]["id"]
        # accept
        s, body = c.post(f"/api/orders/{oid}/accept", role="Restaurant", user_id=ids["rid"])
        assert s == 200 and body["data"]["status"] == "RESTAURANT_ACCEPTED"
        # ready before start-preparing -> ERR_INVALID_STATE
        s, e = c.post(f"/api/orders/{oid}/ready", role="Restaurant", user_id=ids["rid"])
        assert s == 409
        s, _ = c.post(f"/api/orders/{oid}/start-preparing", role="Restaurant", user_id=ids["rid"])
        assert s == 200
        # ready before rider accepts -> ERR_INVALID_STATE
        s, e = c.post(f"/api/orders/{oid}/ready", role="Restaurant", user_id=ids["rid"])
        assert s == 409, (s, e)

    def cancel_by_customer():
        c, ids = setup_basics()
        _, body = place_order(c, ids)
        oid = body["data"]["id"]
        s, body = c.post(f"/api/orders/{oid}/cancel", role="Customer", user_id=ids["cid"])
        assert s == 200
        assert body["data"]["status"] == "CANCELLED"
        assert body["data"]["payment_status"] == "VOIDED"

    def cancel_other_customer_forbidden():
        c, ids = setup_basics()
        _, body = place_order(c, ids)
        oid = body["data"]["id"]
        s, _ = c.post(f"/api/orders/{oid}/cancel", role="Customer", user_id="bad")
        assert s == 403

    def cancel_after_prepare_forbidden():
        c, ids = setup_basics()
        from .fixtures import register_rider
        register_rider(c)
        _, body = place_order(c, ids)
        oid = body["data"]["id"]
        c.post(f"/api/orders/{oid}/accept", role="Restaurant", user_id=ids["rid"])
        s, _ = c.post(f"/api/orders/{oid}/cancel", role="Customer", user_id=ids["cid"])
        assert s == 409

    def order_invalid_menu_item():
        c, ids = setup_basics()
        s, e = c.post("/api/orders", {
            "customer_id": ids["cid"], "restaurant_id": ids["rid"],
            "items": [{"menu_item_id": "bogus", "quantity": 1}],
        }, role="Customer", user_id=ids["cid"])
        assert s == 404

    def customer_identity_match():
        c, ids = setup_basics()
        s, e = c.post("/api/orders", {
            "customer_id": ids["cid"], "restaurant_id": ids["rid"],
            "items": [{"menu_item_id": ids["mid"], "quantity": 1}],
        }, role="Customer", user_id="not-this-customer")
        assert s == 403

    suite.case("min subtotal 100c -> ERR_ORDER_INVALID", place_minimum_subtotal)
    suite.case("empty items -> ERR_ORDER_INVALID", items_must_not_be_empty)
    suite.case("qty < 1 -> ERR_ORDER_INVALID", quantity_must_be_positive_int)
    suite.case("non-ACTIVE restaurant -> ERR_RESTAURANT_UNAVAILABLE", restaurant_not_active)
    suite.case("unlisted menu item -> ERR_RESTAURANT_UNAVAILABLE", unlisted_item)
    suite.case("foreign menu item -> ERR_RESTAURANT_UNAVAILABLE", menu_item_belongs_to_other_restaurant)
    suite.case("placement authorizes payment + computes derived fields", placement_authorizes_payment)
    suite.case("placement records credit_used_cents=0 by default", placement_uses_credit_first)
    suite.case("restaurant accept -> start-preparing flow", restaurant_accept_flow)
    suite.case("customer cancels placed -> VOIDED", cancel_by_customer)
    suite.case("other customer cancel -> ERR_FORBIDDEN", cancel_other_customer_forbidden)
    suite.case("cancel beyond PLACED -> ERR_INVALID_STATE", cancel_after_prepare_forbidden)
    suite.case("unknown menu_item_id -> ERR_NOT_FOUND", order_invalid_menu_item)
    suite.case("customer_id must match X-User-ID -> ERR_FORBIDDEN", customer_identity_match)
