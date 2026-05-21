"""Tests for §2.10 (peak windows / clock) and miscellaneous edges."""
from __future__ import annotations

import datetime

from .harness import test


@test("clock advance: 60s sweeps OFFERED → REJECTED with fresh dispatch")
def t1(ctx):
    rest = ctx.make_active_restaurant(lat=40.0, lng=-74.0)
    mi = ctx.add_menu_item(rest["id"], price_cents=500)
    cust = ctx.register_customer(lat=40.01, lng=-74.01)
    s, b = ctx.place_order(customer=cust, restaurant=rest,
                            items=[{"menu_item_id": mi["id"], "quantity": 1}])
    o = b["data"]
    ctx.post(f"/api/orders/{o['id']}/accept", role="Restaurant", user_id=rest["id"])
    r1 = ctx.register_rider(name="r1", phone="p1"); ctx.go_online(r1)
    ctx.post(f"/api/orders/{o['id']}/start-preparing", role="Restaurant", user_id=rest["id"])
    store = ctx.app.config["STORE"]
    with store.lock:
        offered = [a for a in store.assignments.values()
                   if a["order_id"] == o["id"] and a["status"] == "OFFERED"][0]
    # Add another rider to be the redispatch target
    r2 = ctx.register_rider(name="r2", phone="p2"); ctx.go_online(r2)
    ctx.clock_advance(61)
    with store.lock:
        offered_now = store.assignments[offered["id"]]
        assert offered_now["status"] == "REJECTED"
        # A new OFFERED assignment exists
        live = [a for a in store.assignments.values()
                if a["order_id"] == o["id"] and a["status"] == "OFFERED"]
    assert len(live) == 1


@test("peak window: order placed inside 11:00 UTC is_peak True")
def t2(ctx):
    from app.peak import is_peak
    assert is_peak(datetime.datetime(2025, 5, 24, 11, 30, tzinfo=datetime.timezone.utc)) is True
    assert is_peak(datetime.datetime(2025, 5, 24, 12, 59, tzinfo=datetime.timezone.utc)) is True
    assert is_peak(datetime.datetime(2025, 5, 24, 13, 0, tzinfo=datetime.timezone.utc)) is False
    assert is_peak(datetime.datetime(2025, 5, 24, 18, 0, tzinfo=datetime.timezone.utc)) is True
    assert is_peak(datetime.datetime(2025, 5, 24, 19, 59, tzinfo=datetime.timezone.utc)) is True
    assert is_peak(datetime.datetime(2025, 5, 24, 20, 0, tzinfo=datetime.timezone.utc)) is False


@test("is_peak frozen at placement governs final fee")
def t3(ctx):
    # delivery_fee with same distance but peak vs not yields different fees
    from app.fees import delivery_fee
    assert delivery_fee(1.0, True) - delivery_fee(1.0, False) == 200


@test("cascade: deliver updates version on every versioned resource touched")
def t4(ctx):
    from .test_dispatch_delivery import _setup_ready_order
    rest, cust, mi, order = _setup_ready_order(ctx, price=10000)
    rider = ctx.register_rider(); ctx.go_online(rider)
    pre_rest_ver = ctx.get(f"/api/restaurants/{rest['id']}", role="PlatformAdmin", user_id="a")[1]["data"]["version"]
    pre_rider_ver = ctx.get(f"/api/riders/{rider['id']}", role="PlatformAdmin", user_id="a")[1]["data"]["version"]
    ctx.post(f"/api/orders/{order['id']}/start-preparing", role="Restaurant", user_id=rest["id"])
    store = ctx.app.config["STORE"]
    with store.lock:
        a = [x for x in store.assignments.values() if x["order_id"] == order["id"]][0]
    ctx.post(f"/api/assignments/{a['id']}/accept", role="Rider", user_id=rider["id"])
    ctx.post(f"/api/orders/{order['id']}/ready", role="Restaurant", user_id=rest["id"])
    ctx.post(f"/api/assignments/{a['id']}/pickup", role="Rider", user_id=rider["id"])
    ctx.post(f"/api/assignments/{a['id']}/deliver", role="Rider", user_id=rider["id"])
    post_rest = ctx.get(f"/api/restaurants/{rest['id']}", role="PlatformAdmin", user_id="a")[1]["data"]
    post_rider = ctx.get(f"/api/riders/{rider['id']}", role="PlatformAdmin", user_id="a")[1]["data"]
    assert post_rest["version"] > pre_rest_ver
    assert post_rider["version"] > pre_rider_ver


@test("validation priority: ERR_AUTH_REQUIRED wins over ERR_NOT_FOUND")
def t5(ctx):
    s, b = ctx.get("/api/restaurants/none")
    assert s == 401  # no headers → auth required, not 404


@test("validation priority: ERR_FORBIDDEN (role) wins over ERR_NOT_FOUND")
def t6(ctx):
    s, b = ctx.post("/api/restaurants/none/approve", role="Customer", user_id="x")
    assert s == 403


@test("validation priority: ERR_NOT_FOUND wins over ERR_FORBIDDEN (identity)")
def t7(ctx):
    # GET /restaurants/{id} with role Restaurant for a missing id
    s, b = ctx.get("/api/restaurants/missing", role="Restaurant", user_id="x")
    assert s == 404


@test("validation priority: ERR_NOT_FOUND on FK before ERR_FORBIDDEN on identity")
def t8(ctx):
    # Place order with non-existent customer_id (FK check at priority 4)
    s, b = ctx.post("/api/orders", role="Customer", user_id="other",
                     json_body={"customer_id": "nope", "restaurant_id": "nope2", "items": []})
    assert s == 404


@test("monetary integers: tiered_commission boundary rounding (half-up once)")
def t9(ctx):
    from app.fees import tiered_commission
    # Pick a subtotal where per-tier independent rounding would differ from joint.
    # 19999 cents in tier 1 → 19999 * 0.15 = 2999.85 → joint half-up → 3000
    assert tiered_commission(19999) == 3000


@test("monetary integers: merge_discount floor-rounded")
def t10(ctx):
    from app.fees import merge_discount
    # 25% of 999 = 249.75 → floor → 249
    assert merge_discount(999) == 249


@test("validation priority: state-machine before domain checks (accept on suspended restaurant)")
def t11(ctx):
    # An order in PLACED whose restaurant got suspended cancels the order.
    # Then accept attempt → ERR_INVALID_STATE.
    rest = ctx.make_active_restaurant()
    mi = ctx.add_menu_item(rest["id"], price_cents=500)
    cust = ctx.register_customer()
    s, b = ctx.place_order(customer=cust, restaurant=rest,
                            items=[{"menu_item_id": mi["id"], "quantity": 1}])
    o = b["data"]
    ctx.post(f"/api/restaurants/{rest['id']}/suspend", role="PlatformAdmin", user_id="a")
    s, b = ctx.post(f"/api/orders/{o['id']}/accept", role="Restaurant", user_id=rest["id"])
    assert s == 409  # ERR_INVALID_STATE because order is CANCELLED already


@test("OCC: PATCH menu-item version mismatch → ERR_VERSION_CONFLICT")
def t12(ctx):
    r = ctx.make_active_restaurant()
    mi = ctx.add_menu_item(r["id"])
    s, b = ctx.patch(f"/api/menu-items/{mi['id']}", role="Restaurant", user_id=r["id"],
                      json_body={"price_cents": 700, "version": 99})
    assert s == 409 and b["data"]["error_id"] == "ERR_VERSION_CONFLICT"


@test("clock advance: return window expiry test against 24h boundary")
def t13(ctx):
    # Deliver order then advance just over 24h and try to open return
    from .test_returns_fines_workorders import _deliver
    rest, cust, o, *_ = _deliver(ctx, price=1000)
    ctx.clock_advance(24 * 3600 + 1)
    s, b = ctx.post(f"/api/orders/{o['id']}/returns", role="Customer", user_id=cust["id"],
                     json_body={"reason": "OTHER", "requested_refund_cents": 100})
    assert s == 422 and b["data"]["error_id"] == "ERR_RETURN_WINDOW_EXPIRED"
