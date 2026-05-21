"""Order placement (§3.4)."""
from __future__ import annotations

from ._factories import make_customer, make_menu_item, make_restaurant, place_order
from ._harness import Client, expect_err, expect_ok, test


def _basic_world(c, rate=None):
    rest = make_restaurant(c, lat=37.0, lng=-122.0, rate=rate)
    mi = make_menu_item(c, rest["id"], price_cents=1000)
    cust = make_customer(c, lat=37.0, lng=-122.0)  # 0 km distance
    return rest, mi, cust


@test("place order returns 201 with derived fields")
def t():
    c = Client()
    rest, mi, cust = _basic_world(c)
    s, b = place_order(c, customer=cust, restaurant=rest,
                       items=[{"menu_item_id": mi["id"], "quantity": 2}])
    assert s == 201
    o = b["data"]
    assert o["status"] == "PLACED"
    assert o["payment_status"] == "AUTHORIZED"
    assert o["subtotal_cents"] == 2000
    assert o["distance_km"] == 0.0
    assert o["provisional_delivery_fee_cents"] == 300  # no peak, 0 km
    # commission tiered: 2000 * 0.15 = 300
    assert o["provisional_commission_cents"] == 300
    assert o["final_delivery_fee_cents"] is None
    assert o["final_commission_cents"] is None
    assert o["actual_delivery_time"] is None
    assert o["minutes_late"] is None
    assert o["version"] == 1
    # promised time is set
    assert o["promised_delivery_time"] is not None


@test("items must be non-empty -> ERR_ORDER_INVALID")
def t():
    c = Client()
    rest, mi, cust = _basic_world(c)
    s, b = place_order(c, customer=cust, restaurant=rest, items=[])
    assert s == 422 and b["data"]["error_id"] == "ERR_ORDER_INVALID"


@test("quantity < 1 -> ERR_ORDER_INVALID")
def t():
    c = Client()
    rest, mi, cust = _basic_world(c)
    s, b = place_order(c, customer=cust, restaurant=rest,
                       items=[{"menu_item_id": mi["id"], "quantity": 0}])
    assert s == 422 and b["data"]["error_id"] == "ERR_ORDER_INVALID"


@test("subtotal < 100 cents -> ERR_ORDER_INVALID")
def t():
    c = Client()
    rest = make_restaurant(c)
    mi = make_menu_item(c, rest["id"], price_cents=50)
    cust = make_customer(c)
    s, b = place_order(c, customer=cust, restaurant=rest,
                       items=[{"menu_item_id": mi["id"], "quantity": 1}])
    assert s == 422 and b["data"]["error_id"] == "ERR_ORDER_INVALID"


@test("restaurant must be ACTIVE -> ERR_RESTAURANT_UNAVAILABLE")
def t():
    c = Client()
    rest = make_restaurant(c, approve=False)
    mi = make_menu_item(c, rest["id"], price_cents=500)
    cust = make_customer(c)
    s, b = place_order(c, customer=cust, restaurant=rest,
                       items=[{"menu_item_id": mi["id"], "quantity": 1}])
    assert s == 422 and b["data"]["error_id"] == "ERR_RESTAURANT_UNAVAILABLE"


@test("unlisted menu item -> ERR_RESTAURANT_UNAVAILABLE")
def t():
    c = Client()
    rest, mi, cust = _basic_world(c)
    c.patch(f"/api/menu-items/{mi['id']}", role="Restaurant", user_id=rest["id"],
            body={"is_listed": False})
    s, b = place_order(c, customer=cust, restaurant=rest,
                       items=[{"menu_item_id": mi["id"], "quantity": 1}])
    assert s == 422 and b["data"]["error_id"] == "ERR_RESTAURANT_UNAVAILABLE"


@test("menu item from a different restaurant -> ERR_RESTAURANT_UNAVAILABLE")
def t():
    c = Client()
    rest1 = make_restaurant(c, name="R1")
    rest2 = make_restaurant(c, name="R2")
    mi2 = make_menu_item(c, rest2["id"], price_cents=500)
    cust = make_customer(c)
    s, b = place_order(c, customer=cust, restaurant=rest1,
                       items=[{"menu_item_id": mi2["id"], "quantity": 1}])
    assert s == 422 and b["data"]["error_id"] == "ERR_RESTAURANT_UNAVAILABLE"


@test("Customer identity mismatch on placement -> ERR_FORBIDDEN")
def t():
    c = Client()
    rest, mi, cust = _basic_world(c)
    # Caller is a different existing customer
    c2 = make_customer(c, phone="999")
    body = {"customer_id": cust["id"], "restaurant_id": rest["id"],
            "items": [{"menu_item_id": mi["id"], "quantity": 1}]}
    s, b = c.post("/api/orders", role="Customer", user_id=c2["id"], body=body)
    assert s == 403


@test("non-existent customer -> ERR_NOT_FOUND")
def t():
    c = Client()
    rest, mi, _ = _basic_world(c)
    body = {"customer_id": "nope", "restaurant_id": rest["id"],
            "items": [{"menu_item_id": mi["id"], "quantity": 1}]}
    s, b = c.post("/api/orders", role="Customer", user_id="any", body=body)
    assert s == 404 and b["data"]["error_id"] == "ERR_NOT_FOUND"


@test("placement uses tiered commission by default")
def t():
    c = Client()
    rest = make_restaurant(c, lat=0, lng=0)
    mi = make_menu_item(c, rest["id"], price_cents=30000)
    cust = make_customer(c, lat=0, lng=0)
    s, b = place_order(c, customer=cust, restaurant=rest,
                       items=[{"menu_item_id": mi["id"], "quantity": 1}])
    assert s == 201
    # subtotal 30000: tier1 3000 + tier2 1800 = 4800
    assert b["data"]["provisional_commission_cents"] == 4800


@test("placement uses commission_rate_override when set")
def t():
    c = Client()
    rest = make_restaurant(c, lat=0, lng=0, rate=0.20)
    mi = make_menu_item(c, rest["id"], price_cents=10000)
    cust = make_customer(c, lat=0, lng=0)
    s, b = place_order(c, customer=cust, restaurant=rest,
                       items=[{"menu_item_id": mi["id"], "quantity": 1}])
    assert s == 201
    # 10000 * 0.20 = 2000
    assert b["data"]["provisional_commission_cents"] == 2000


@test("placement uses credit_balance toward AUTHORIZED amount")
def t():
    c = Client()
    rest, mi, cust = _basic_world(c)
    # Inject some credit
    from app.store import store
    store.customers[cust["id"]]["credit_balance_cents"] = 600
    s, b = place_order(c, customer=cust, restaurant=rest,
                       items=[{"menu_item_id": mi["id"], "quantity": 1}])
    assert s == 201
    # gross = 1000 (subtotal) + 300 (delivery) = 1300; credit drawn = min(600, 1300) = 600
    s, cb = c.get(f"/api/customers/{cust['id']}", role="Customer", user_id=cust["id"])
    assert cb["data"]["credit_balance_cents"] == 0


@test("cancellation refunds drawn credit")
def t():
    c = Client()
    rest, mi, cust = _basic_world(c)
    from app.store import store
    store.customers[cust["id"]]["credit_balance_cents"] = 500
    s, b = place_order(c, customer=cust, restaurant=rest,
                       items=[{"menu_item_id": mi["id"], "quantity": 1}])
    o = b["data"]
    # Customer cancels
    s, _ = c.post(f"/api/orders/{o['id']}/cancel", role="Customer", user_id=cust["id"])
    assert s == 200
    s, cb = c.get(f"/api/customers/{cust['id']}", role="Customer", user_id=cust["id"])
    assert cb["data"]["credit_balance_cents"] == 500
