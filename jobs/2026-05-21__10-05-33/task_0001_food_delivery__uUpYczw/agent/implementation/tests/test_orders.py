"""Tests for §3.4 (order placement) and §3.5 (restaurant flow)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .harness import test


def _setup(ctx, *, restaurant_lat=40.0, restaurant_lng=-74.0,
           customer_lat=40.05, customer_lng=-74.05, price=500,
           commission_override=None):
    rest = ctx.make_active_restaurant(lat=restaurant_lat, lng=restaurant_lng,
                                       commission_rate_override=commission_override)
    mi = ctx.add_menu_item(rest["id"], price_cents=price)
    cust = ctx.register_customer(lat=customer_lat, lng=customer_lng)
    return rest, mi, cust


@test("place: subtotal sums unit_price * quantity")
def t1(ctx):
    rest, mi, cust = _setup(ctx, price=750)
    s, b = ctx.place_order(customer=cust, restaurant=rest,
                            items=[{"menu_item_id": mi["id"], "quantity": 3}])
    assert s == 201
    assert b["data"]["subtotal_cents"] == 2250


@test("place: empty items → ERR_ORDER_INVALID")
def t2(ctx):
    rest, _, cust = _setup(ctx)
    s, b = ctx.place_order(customer=cust, restaurant=rest, items=[])
    assert s == 422 and b["data"]["error_id"] == "ERR_ORDER_INVALID"


@test("place: quantity < 1 → ERR_ORDER_INVALID")
def t3(ctx):
    rest, mi, cust = _setup(ctx)
    s, b = ctx.place_order(customer=cust, restaurant=rest,
                            items=[{"menu_item_id": mi["id"], "quantity": 0}])
    assert s == 422 and b["data"]["error_id"] == "ERR_ORDER_INVALID"


@test("place: subtotal below 100 → ERR_ORDER_INVALID")
def t4(ctx):
    rest, mi, cust = _setup(ctx, price=50)
    s, b = ctx.place_order(customer=cust, restaurant=rest,
                            items=[{"menu_item_id": mi["id"], "quantity": 1}])
    assert s == 422 and b["data"]["error_id"] == "ERR_ORDER_INVALID"


@test("place: restaurant not ACTIVE → ERR_RESTAURANT_UNAVAILABLE")
def t5(ctx):
    rest = ctx.register_restaurant()  # PENDING_APPROVAL
    mi = ctx.add_menu_item(rest["id"], price_cents=500)
    # Approve to add menu items? We added directly. Now suspend.
    ctx.approve_restaurant(rest["id"])
    ctx.post(f"/api/restaurants/{rest['id']}/suspend", role="PlatformAdmin", user_id="a")
    cust = ctx.register_customer()
    s, b = ctx.place_order(customer=cust, restaurant=rest,
                            items=[{"menu_item_id": mi["id"], "quantity": 1}])
    assert s == 422 and b["data"]["error_id"] == "ERR_RESTAURANT_UNAVAILABLE"


@test("place: unlisted menu item → ERR_RESTAURANT_UNAVAILABLE")
def t6(ctx):
    rest, mi, cust = _setup(ctx)
    ctx.patch(f"/api/menu-items/{mi['id']}", role="Restaurant", user_id=rest["id"],
               json_body={"is_listed": False})
    s, b = ctx.place_order(customer=cust, restaurant=rest,
                            items=[{"menu_item_id": mi["id"], "quantity": 1}])
    assert s == 422 and b["data"]["error_id"] == "ERR_RESTAURANT_UNAVAILABLE"


@test("place: menu item from different restaurant → ERR_RESTAURANT_UNAVAILABLE")
def t7(ctx):
    rest1, mi1, cust = _setup(ctx)
    rest2 = ctx.make_active_restaurant(name="Other", lat=41.0, lng=-75.0)
    s, b = ctx.place_order(customer=cust, restaurant=rest2,
                            items=[{"menu_item_id": mi1["id"], "quantity": 1}])
    assert s == 422 and b["data"]["error_id"] == "ERR_RESTAURANT_UNAVAILABLE"


@test("place: identity mismatch on customer_id → ERR_FORBIDDEN")
def t8(ctx):
    rest, mi, cust = _setup(ctx)
    other = ctx.register_customer(phone="other")
    s, b = ctx.post("/api/orders", role="Customer", user_id=other["id"],
                    json_body={"customer_id": cust["id"], "restaurant_id": rest["id"],
                                "items": [{"menu_item_id": mi["id"], "quantity": 1}]})
    assert s == 403 and b["data"]["error_id"] == "ERR_FORBIDDEN"


@test("place: unknown menu_item_id → ERR_NOT_FOUND")
def t9(ctx):
    rest, _, cust = _setup(ctx)
    s, b = ctx.post("/api/orders", role="Customer", user_id=cust["id"],
                    json_body={"customer_id": cust["id"], "restaurant_id": rest["id"],
                                "items": [{"menu_item_id": "nope", "quantity": 1}]})
    assert s == 404 and b["data"]["error_id"] == "ERR_NOT_FOUND"


@test("place: provisional_delivery_fee uses base + bands + peak (when peak)")
def t10(ctx):
    # Force peak by advancing clock if needed — use module function directly.
    from app.fees import delivery_fee
    # distance 2.0km → ceil=2 → 2 bands; peak=True → 200 surcharge
    # 300 + 2*120 + 200 = 740
    assert delivery_fee(2.0, True) == 740
    # distance 2.01 → ceil=3 → 3 bands; peak=False
    # 300 + 3*120 + 0 = 660
    assert delivery_fee(2.01, False) == 660


@test("place: provisional commission uses tiered formula")
def t11(ctx):
    from app.fees import tiered_commission
    # 20000 * 0.15 = 3000
    assert tiered_commission(20000) == 3000
    # 50000 -> 20000*0.15 + 30000*0.18 = 3000 + 5400 = 8400
    assert tiered_commission(50000) == 8400
    # 100000 -> 3000 + 5400 + 50000*0.22 = 3000 + 5400 + 11000 = 19400
    assert tiered_commission(100000) == 19400


@test("place: distance_km rounded to 1 decimal place")
def t12(ctx):
    rest, mi, cust = _setup(ctx, restaurant_lat=40.0, restaurant_lng=-74.0,
                              customer_lat=40.05, customer_lng=-74.05)
    s, b = ctx.place_order(customer=cust, restaurant=rest,
                            items=[{"menu_item_id": mi["id"], "quantity": 1}])
    assert s == 201
    d = b["data"]["distance_km"]
    assert isinstance(d, float)
    # Should be one decimal of precision
    assert round(d, 1) == d


@test("place: payment_status starts AUTHORIZED with credit drawdown")
def t13(ctx):
    rest, mi, cust = _setup(ctx, price=500)
    # Give customer credit
    with ctx.app.config["STORE"].lock:
        ctx.app.config["STORE"].customers[cust["id"]]["credit_balance_cents"] = 200
    s, b = ctx.place_order(customer=cust, restaurant=rest,
                            items=[{"menu_item_id": mi["id"], "quantity": 1}])
    assert b["data"]["payment_status"] == "AUTHORIZED"
    assert b["data"]["credit_applied_cents"] == 200
    # Customer credit drawn down
    s, b = ctx.get(f"/api/customers/{cust['id']}", role="PlatformAdmin", user_id="a")
    assert b["data"]["credit_balance_cents"] == 0


@test("place: promised_delivery_time = now + 45m")
def t14(ctx):
    rest, mi, cust = _setup(ctx, price=500)
    s, b = ctx.place_order(customer=cust, restaurant=rest,
                            items=[{"menu_item_id": mi["id"], "quantity": 1}])
    from app.clock import parse_iso
    placed = parse_iso(b["data"]["created_at"])
    promised = parse_iso(b["data"]["promised_delivery_time"])
    assert (promised - placed) == timedelta(minutes=45)


@test("accept: PLACED → RESTAURANT_ACCEPTED")
def t15(ctx):
    rest, mi, cust = _setup(ctx)
    s, b = ctx.place_order(customer=cust, restaurant=rest,
                            items=[{"menu_item_id": mi["id"], "quantity": 1}])
    oid = b["data"]["id"]
    s, b = ctx.post(f"/api/orders/{oid}/accept", role="Restaurant", user_id=rest["id"])
    assert s == 200 and b["data"]["status"] == "RESTAURANT_ACCEPTED"


@test("accept: non-PLACED → ERR_INVALID_STATE")
def t16(ctx):
    rest, mi, cust = _setup(ctx)
    s, b = ctx.place_order(customer=cust, restaurant=rest,
                            items=[{"menu_item_id": mi["id"], "quantity": 1}])
    oid = b["data"]["id"]
    ctx.post(f"/api/orders/{oid}/accept", role="Restaurant", user_id=rest["id"])
    s, b = ctx.post(f"/api/orders/{oid}/accept", role="Restaurant", user_id=rest["id"])
    assert s == 409 and b["data"]["error_id"] == "ERR_INVALID_STATE"


@test("cancel: PLACED by customer → CANCELLED + VOIDED")
def t17(ctx):
    rest, mi, cust = _setup(ctx)
    s, b = ctx.place_order(customer=cust, restaurant=rest,
                            items=[{"menu_item_id": mi["id"], "quantity": 1}])
    oid = b["data"]["id"]
    s, b = ctx.post(f"/api/orders/{oid}/cancel", role="Customer", user_id=cust["id"])
    assert s == 200
    assert b["data"]["status"] == "CANCELLED"
    assert b["data"]["payment_status"] == "VOIDED"


@test("cancel: non-PLACED → ERR_INVALID_STATE")
def t18(ctx):
    rest, mi, cust = _setup(ctx)
    s, b = ctx.place_order(customer=cust, restaurant=rest,
                            items=[{"menu_item_id": mi["id"], "quantity": 1}])
    oid = b["data"]["id"]
    ctx.post(f"/api/orders/{oid}/accept", role="Restaurant", user_id=rest["id"])
    s, b = ctx.post(f"/api/orders/{oid}/cancel", role="Customer", user_id=cust["id"])
    assert s == 409 and b["data"]["error_id"] == "ERR_INVALID_STATE"


@test("ready: requires rider acceptance → ERR_INVALID_STATE otherwise")
def t19(ctx):
    rest, mi, cust = _setup(ctx)
    s, b = ctx.place_order(customer=cust, restaurant=rest,
                            items=[{"menu_item_id": mi["id"], "quantity": 1}])
    oid = b["data"]["id"]
    ctx.post(f"/api/orders/{oid}/accept", role="Restaurant", user_id=rest["id"])
    ctx.post(f"/api/orders/{oid}/start-preparing", role="Restaurant", user_id=rest["id"])
    s, b = ctx.post(f"/api/orders/{oid}/ready", role="Restaurant", user_id=rest["id"])
    assert s == 409 and b["data"]["error_id"] == "ERR_INVALID_STATE"


@test("list orders: filter by customer/restaurant/status")
def t20(ctx):
    rest, mi, cust = _setup(ctx)
    ctx.place_order(customer=cust, restaurant=rest,
                     items=[{"menu_item_id": mi["id"], "quantity": 1}])
    s, b = ctx.get("/api/orders", role="PlatformAdmin", user_id="a",
                    query={"customer_id": cust["id"], "status": "PLACED"})
    assert s == 200 and b["meta"]["total_count"] == 1
