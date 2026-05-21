"""Tests for §3.6 (dispatch & assignments), §3.7 (delivery & fiscal reconciliation)."""
from __future__ import annotations

from .harness import test


def _setup_ready_order(ctx, *, restaurant=None, customer=None, price=500, qty=1):
    """Common scenario: order placed, restaurant accepts, start-preparing dispatched."""
    if restaurant is None:
        restaurant = ctx.make_active_restaurant(lat=40.0, lng=-74.0)
    if customer is None:
        customer = ctx.register_customer(lat=40.01, lng=-74.01)
    mi = ctx.add_menu_item(restaurant["id"], price_cents=price)
    s, b = ctx.place_order(customer=customer, restaurant=restaurant,
                            items=[{"menu_item_id": mi["id"], "quantity": qty}])
    order = b["data"]
    ctx.post(f"/api/orders/{order['id']}/accept", role="Restaurant", user_id=restaurant["id"])
    return restaurant, customer, mi, order


@test("dispatch: start-preparing creates Assignment in OFFERED")
def t1(ctx):
    rest, cust, _, order = _setup_ready_order(ctx)
    rider = ctx.register_rider()
    ctx.go_online(rider)
    ctx.post(f"/api/orders/{order['id']}/start-preparing", role="Restaurant", user_id=rest["id"])
    # Find assignment via internal store
    store = ctx.app.config["STORE"]
    with store.lock:
        assignments = [a for a in store.assignments.values() if a["order_id"] == order["id"]]
    assert len(assignments) == 1
    assert assignments[0]["status"] == "OFFERED"
    assert assignments[0]["rider_id"] == rider["id"]


@test("dispatch: no eligible rider → /dispatch returns ERR_INVALID_STATE")
def t2(ctx):
    rest, cust, _, order = _setup_ready_order(ctx)
    # No riders online
    s, b = ctx.post(f"/api/orders/{order['id']}/dispatch", role="PlatformAdmin", user_id="a")
    assert s == 409 and b["data"]["error_id"] == "ERR_INVALID_STATE"


@test("dispatch: tie-break created_at desc")
def t3(ctx):
    rest, cust, _, order = _setup_ready_order(ctx)
    r1 = ctx.register_rider(name="r1", phone="p1"); ctx.go_online(r1)
    r2 = ctx.register_rider(name="r2", phone="p2"); ctx.go_online(r2)
    ctx.post(f"/api/orders/{order['id']}/start-preparing", role="Restaurant", user_id=rest["id"])
    store = ctx.app.config["STORE"]
    with store.lock:
        assignments = [a for a in store.assignments.values() if a["order_id"] == order["id"]]
    # Newest (r2) should win
    assert assignments[0]["rider_id"] == r2["id"]


@test("accept: rider OFFERED → ACCEPTED, rider → ON_DELIVERY")
def t4(ctx):
    rest, cust, _, order = _setup_ready_order(ctx)
    rider = ctx.register_rider()
    ctx.go_online(rider)
    ctx.post(f"/api/orders/{order['id']}/start-preparing", role="Restaurant", user_id=rest["id"])
    store = ctx.app.config["STORE"]
    with store.lock:
        a = [x for x in store.assignments.values() if x["order_id"] == order["id"]][0]
    s, b = ctx.post(f"/api/assignments/{a['id']}/accept", role="Rider", user_id=rider["id"])
    assert s == 200 and b["data"]["status"] == "ACCEPTED"
    s, b = ctx.get(f"/api/riders/{rider['id']}", role="PlatformAdmin", user_id="a")
    assert b["data"]["status"] == "ON_DELIVERY"


@test("race: two accepts on same order — second → ERR_ORDER_ALREADY_ASSIGNED")
def t5(ctx):
    rest, cust, _, order = _setup_ready_order(ctx)
    r1 = ctx.register_rider(name="r1", phone="p1"); ctx.go_online(r1)
    r2 = ctx.register_rider(name="r2", phone="p2"); ctx.go_online(r2)
    ctx.post(f"/api/orders/{order['id']}/start-preparing", role="Restaurant", user_id=rest["id"])
    store = ctx.app.config["STORE"]
    with store.lock:
        a1 = [x for x in store.assignments.values() if x["order_id"] == order["id"]][0]
    # Force-dispatch a second assignment to r1 (manually craft scenario)
    s, b = ctx.post(f"/api/orders/{order['id']}/dispatch", role="PlatformAdmin", user_id="a")
    assert s == 201
    with store.lock:
        a2 = b["data"]
    # The original assignment goes to newest rider (r2). Second dispatch goes to r1.
    # Accept the first one
    s, b = ctx.post(f"/api/assignments/{a1['id']}/accept", role="Rider", user_id=a1["rider_id"])
    assert s == 200
    # Now accept the second should fail
    s, b = ctx.post(f"/api/assignments/{a2['id']}/accept", role="Rider", user_id=a2["rider_id"])
    assert s == 409, b
    assert b["data"]["error_id"] == "ERR_ORDER_ALREADY_ASSIGNED"


@test("reject: rejection issues fresh dispatch")
def t6(ctx):
    rest, cust, _, order = _setup_ready_order(ctx)
    r1 = ctx.register_rider(name="r1", phone="p1"); ctx.go_online(r1)
    ctx.post(f"/api/orders/{order['id']}/start-preparing", role="Restaurant", user_id=rest["id"])
    store = ctx.app.config["STORE"]
    with store.lock:
        a1 = [x for x in store.assignments.values() if x["order_id"] == order["id"]][0]
    # Reject → second assignment is created (but no more riders to dispatch, so none created)
    s, b = ctx.post(f"/api/assignments/{a1['id']}/reject", role="Rider", user_id=r1["id"])
    assert s == 200 and b["data"]["status"] == "REJECTED"
    # Add another rider and re-dispatch
    r2 = ctx.register_rider(name="r2", phone="p2"); ctx.go_online(r2)
    s, b = ctx.post(f"/api/orders/{order['id']}/dispatch", role="PlatformAdmin", user_id="a")
    assert s == 201
    assert b["data"]["rider_id"] == r2["id"]


@test("pickup: ACCEPTED+READY → PICKED_UP cascades order")
def t7(ctx):
    rest, cust, _, order = _setup_ready_order(ctx)
    rider = ctx.register_rider(); ctx.go_online(rider)
    ctx.post(f"/api/orders/{order['id']}/start-preparing", role="Restaurant", user_id=rest["id"])
    store = ctx.app.config["STORE"]
    with store.lock:
        a = [x for x in store.assignments.values() if x["order_id"] == order["id"]][0]
    ctx.post(f"/api/assignments/{a['id']}/accept", role="Rider", user_id=rider["id"])
    ctx.post(f"/api/orders/{order['id']}/ready", role="Restaurant", user_id=rest["id"])
    s, b = ctx.post(f"/api/assignments/{a['id']}/pickup", role="Rider", user_id=rider["id"])
    assert s == 200 and b["data"]["status"] == "PICKED_UP"
    s, b = ctx.get(f"/api/orders/{order['id']}", role="PlatformAdmin", user_id="a")
    assert b["data"]["status"] == "PICKED_UP"


@test("deliver: cascade — order DELIVERED, payment CAPTURED, wallet credited, restaurant settlement +")
def t8(ctx):
    rest, cust, _, order = _setup_ready_order(ctx, price=10000)
    rider = ctx.register_rider(); ctx.go_online(rider)
    ctx.post(f"/api/orders/{order['id']}/start-preparing", role="Restaurant", user_id=rest["id"])
    store = ctx.app.config["STORE"]
    with store.lock:
        a = [x for x in store.assignments.values() if x["order_id"] == order["id"]][0]
    ctx.post(f"/api/assignments/{a['id']}/accept", role="Rider", user_id=rider["id"])
    ctx.post(f"/api/orders/{order['id']}/ready", role="Restaurant", user_id=rest["id"])
    ctx.post(f"/api/assignments/{a['id']}/pickup", role="Rider", user_id=rider["id"])
    s, b = ctx.post(f"/api/assignments/{a['id']}/deliver", role="Rider", user_id=rider["id"])
    assert s == 200
    # Order state
    s, ob = ctx.get(f"/api/orders/{order['id']}", role="PlatformAdmin", user_id="a")
    assert ob["data"]["status"] == "DELIVERED"
    assert ob["data"]["payment_status"] == "CAPTURED"
    assert ob["data"]["final_delivery_fee_cents"] is not None
    assert ob["data"]["final_commission_cents"] == 1500  # 10000 * 0.15
    # Restaurant settlement
    s, rb = ctx.get(f"/api/restaurants/{rest['id']}", role="PlatformAdmin", user_id="a")
    expected = 10000 - 1500
    assert rb["data"]["pending_settlement_cents"] == expected
    # Wallet credit
    s, rib = ctx.get(f"/api/riders/{rider['id']}", role="PlatformAdmin", user_id="a")
    assert rib["data"]["wallet_balance_cents"] == ob["data"]["final_delivery_fee_cents"]


@test("deliver: late delivery 1-10m → flat 200 cent fine")
def t9(ctx):
    rest, cust, _, order = _setup_ready_order(ctx, price=10000)
    rider = ctx.register_rider(); ctx.go_online(rider)
    ctx.post(f"/api/orders/{order['id']}/start-preparing", role="Restaurant", user_id=rest["id"])
    store = ctx.app.config["STORE"]
    with store.lock:
        a = [x for x in store.assignments.values() if x["order_id"] == order["id"]][0]
    ctx.post(f"/api/assignments/{a['id']}/accept", role="Rider", user_id=rider["id"])
    ctx.post(f"/api/orders/{order['id']}/ready", role="Restaurant", user_id=rest["id"])
    ctx.post(f"/api/assignments/{a['id']}/pickup", role="Rider", user_id=rider["id"])
    # Advance 50 minutes — 5m late
    ctx.clock_advance(50 * 60)
    s, b = ctx.post(f"/api/assignments/{a['id']}/deliver", role="Rider", user_id=rider["id"])
    assert s == 200
    s, ob = ctx.get(f"/api/orders/{order['id']}", role="PlatformAdmin", user_id="a")
    assert ob["data"]["minutes_late"] == 5
    # Late fine
    s, fb = ctx.get("/api/fines", role="PlatformAdmin", user_id="a")
    fines = [f for f in fb["data"] if f["reason"] == "LATE_DELIVERY"]
    assert len(fines) == 1 and fines[0]["amount_cents"] == 200


@test("deliver: late 11-30m → 500 + 50*(m-10)")
def t10(ctx):
    rest, cust, _, order = _setup_ready_order(ctx, price=10000)
    rider = ctx.register_rider(); ctx.go_online(rider)
    ctx.post(f"/api/orders/{order['id']}/start-preparing", role="Restaurant", user_id=rest["id"])
    store = ctx.app.config["STORE"]
    with store.lock:
        a = [x for x in store.assignments.values() if x["order_id"] == order["id"]][0]
    ctx.post(f"/api/assignments/{a['id']}/accept", role="Rider", user_id=rider["id"])
    ctx.post(f"/api/orders/{order['id']}/ready", role="Restaurant", user_id=rest["id"])
    ctx.post(f"/api/assignments/{a['id']}/pickup", role="Rider", user_id=rider["id"])
    # Advance 65 minutes → 20 late
    ctx.clock_advance(65 * 60)
    ctx.post(f"/api/assignments/{a['id']}/deliver", role="Rider", user_id=rider["id"])
    s, fb = ctx.get("/api/fines", role="PlatformAdmin", user_id="a")
    fines = [f for f in fb["data"] if f["reason"] == "LATE_DELIVERY"]
    expected = 500 + 50 * (20 - 10)
    assert fines[0]["amount_cents"] == expected


@test("deliver: late >30m → min(fee,1500) + 500")
def t11(ctx):
    rest, cust, _, order = _setup_ready_order(ctx, price=10000)
    rider = ctx.register_rider(); ctx.go_online(rider)
    ctx.post(f"/api/orders/{order['id']}/start-preparing", role="Restaurant", user_id=rest["id"])
    store = ctx.app.config["STORE"]
    with store.lock:
        a = [x for x in store.assignments.values() if x["order_id"] == order["id"]][0]
    ctx.post(f"/api/assignments/{a['id']}/accept", role="Rider", user_id=rider["id"])
    ctx.post(f"/api/orders/{order['id']}/ready", role="Restaurant", user_id=rest["id"])
    ctx.post(f"/api/assignments/{a['id']}/pickup", role="Rider", user_id=rider["id"])
    ctx.clock_advance(120 * 60)  # 75 late
    ctx.post(f"/api/assignments/{a['id']}/deliver", role="Rider", user_id=rider["id"])
    s, fb = ctx.get("/api/fines", role="PlatformAdmin", user_id="a")
    fines = [f for f in fb["data"] if f["reason"] == "LATE_DELIVERY"]
    s, ob = ctx.get(f"/api/orders/{order['id']}", role="PlatformAdmin", user_id="a")
    fee = ob["data"]["final_delivery_fee_cents"]
    expected = min(fee, 1500) + 500
    assert fines[0]["amount_cents"] == expected


@test("rider cancel after accept → RIDER_NO_SHOW fine, redispatch")
def t12(ctx):
    rest, cust, _, order = _setup_ready_order(ctx)
    r1 = ctx.register_rider(name="r1", phone="p1"); ctx.go_online(r1)
    r2 = ctx.register_rider(name="r2", phone="p2"); ctx.go_online(r2)
    ctx.post(f"/api/orders/{order['id']}/start-preparing", role="Restaurant", user_id=rest["id"])
    store = ctx.app.config["STORE"]
    with store.lock:
        a = [x for x in store.assignments.values() if x["order_id"] == order["id"]][0]
    accepting = a["rider_id"]
    ctx.post(f"/api/assignments/{a['id']}/accept", role="Rider", user_id=accepting)
    s, b = ctx.post(f"/api/assignments/{a['id']}/cancel", role="Rider", user_id=accepting)
    assert s == 200 and b["data"]["status"] == "CANCELLED"
    # Fine of 500 cents
    s, fb = ctx.get("/api/fines", role="PlatformAdmin", user_id="a")
    no_show = [f for f in fb["data"] if f["reason"] == "RIDER_NO_SHOW"]
    assert len(no_show) == 1 and no_show[0]["amount_cents"] == 500
    # Wallet debited
    s, rb = ctx.get(f"/api/riders/{accepting}", role="PlatformAdmin", user_id="a")
    assert rb["data"]["wallet_balance_cents"] == -500
    # New assignment exists for the order
    with store.lock:
        live = [x for x in store.assignments.values()
                if x["order_id"] == order["id"] and x["status"] == "OFFERED"]
    assert len(live) == 1


@test("commission override: flat rate replaces tiered at delivery")
def t13(ctx):
    rest = ctx.make_active_restaurant(lat=40.0, lng=-74.0, commission_rate_override=0.10)
    mi = ctx.add_menu_item(rest["id"], price_cents=10000)
    cust = ctx.register_customer(lat=40.01, lng=-74.01)
    s, b = ctx.place_order(customer=cust, restaurant=rest,
                            items=[{"menu_item_id": mi["id"], "quantity": 1}])
    oid = b["data"]["id"]
    ctx.post(f"/api/orders/{oid}/accept", role="Restaurant", user_id=rest["id"])
    rider = ctx.register_rider(); ctx.go_online(rider)
    ctx.post(f"/api/orders/{oid}/start-preparing", role="Restaurant", user_id=rest["id"])
    store = ctx.app.config["STORE"]
    with store.lock:
        a = [x for x in store.assignments.values() if x["order_id"] == oid][0]
    ctx.post(f"/api/assignments/{a['id']}/accept", role="Rider", user_id=rider["id"])
    ctx.post(f"/api/orders/{oid}/ready", role="Restaurant", user_id=rest["id"])
    ctx.post(f"/api/assignments/{a['id']}/pickup", role="Rider", user_id=rider["id"])
    ctx.post(f"/api/assignments/{a['id']}/deliver", role="Rider", user_id=rider["id"])
    s, ob = ctx.get(f"/api/orders/{oid}", role="PlatformAdmin", user_id="a")
    assert ob["data"]["final_commission_cents"] == 1000  # 10000 * 0.10


@test("merge: two ON_DELIVERY orders within 500m → discount 25% floor")
def t14(ctx):
    rest1 = ctx.make_active_restaurant(name="A", lat=40.0, lng=-74.0)
    rest2 = ctx.make_active_restaurant(name="B", lat=40.0002, lng=-74.0002)  # ~28m
    mi1 = ctx.add_menu_item(rest1["id"], price_cents=10000)
    mi2 = ctx.add_menu_item(rest2["id"], price_cents=10000)
    cust1 = ctx.register_customer(phone="c1", lat=40.01, lng=-74.01)
    cust2 = ctx.register_customer(phone="c2", lat=40.011, lng=-74.011)
    s, b = ctx.place_order(customer=cust1, restaurant=rest1,
                            items=[{"menu_item_id": mi1["id"], "quantity": 1}])
    o1 = b["data"]
    s, b = ctx.place_order(customer=cust2, restaurant=rest2,
                            items=[{"menu_item_id": mi2["id"], "quantity": 1}])
    o2 = b["data"]
    rider = ctx.register_rider(); ctx.go_online(rider)
    # Accept and start preparing both
    ctx.post(f"/api/orders/{o1['id']}/accept", role="Restaurant", user_id=rest1["id"])
    ctx.post(f"/api/orders/{o1['id']}/start-preparing", role="Restaurant", user_id=rest1["id"])
    store = ctx.app.config["STORE"]
    with store.lock:
        a1 = [x for x in store.assignments.values() if x["order_id"] == o1["id"]][0]
    ctx.post(f"/api/assignments/{a1['id']}/accept", role="Rider", user_id=rider["id"])
    # Now rider is ON_DELIVERY; accept second
    ctx.post(f"/api/orders/{o2['id']}/accept", role="Restaurant", user_id=rest2["id"])
    ctx.post(f"/api/orders/{o2['id']}/start-preparing", role="Restaurant", user_id=rest2["id"])
    with store.lock:
        a2 = [x for x in store.assignments.values()
              if x["order_id"] == o2["id"] and x["status"] == "OFFERED"][0]
    ctx.post(f"/api/assignments/{a2['id']}/accept", role="Rider", user_id=rider["id"])
    # Both should now share a RouteGroup
    with store.lock:
        a1 = store.assignments[a1["id"]]
        a2 = store.assignments[a2["id"]]
    assert a1["route_group_id"] is not None
    assert a1["route_group_id"] == a2["route_group_id"]
    # Mark ready and deliver both — observe 25% discount
    ctx.post(f"/api/orders/{o1['id']}/ready", role="Restaurant", user_id=rest1["id"])
    ctx.post(f"/api/orders/{o2['id']}/ready", role="Restaurant", user_id=rest2["id"])
    ctx.post(f"/api/assignments/{a1['id']}/pickup", role="Rider", user_id=rider["id"])
    ctx.post(f"/api/assignments/{a2['id']}/pickup", role="Rider", user_id=rider["id"])
    ctx.post(f"/api/assignments/{a1['id']}/deliver", role="Rider", user_id=rider["id"])
    ctx.post(f"/api/assignments/{a2['id']}/deliver", role="Rider", user_id=rider["id"])
    s, ob1 = ctx.get(f"/api/orders/{o1['id']}", role="PlatformAdmin", user_id="a")
    from app.fees import delivery_fee, merge_discount
    solo = delivery_fee(ob1["data"]["distance_km"], ob1["data"]["is_peak"])
    expected = solo - merge_discount(solo)
    assert ob1["data"]["final_delivery_fee_cents"] == expected


@test("dispatch: rider already linked to live assignment excluded from re-offer")
def t15(ctx):
    rest, cust, _, order = _setup_ready_order(ctx)
    rider = ctx.register_rider(); ctx.go_online(rider)
    ctx.post(f"/api/orders/{order['id']}/start-preparing", role="Restaurant", user_id=rest["id"])
    # Force another dispatch — only rider in pool, but excluded → ERR_INVALID_STATE
    s, b = ctx.post(f"/api/orders/{order['id']}/dispatch", role="PlatformAdmin", user_id="a")
    assert s == 409 and b["data"]["error_id"] == "ERR_INVALID_STATE"
