"""Delivery and fiscal reconciliation (§3.7)."""
from __future__ import annotations

from ._factories import make_customer, make_menu_item, make_restaurant, make_rider, place_order
from ._harness import Client, expect_err, expect_ok, test


def _deliver_solo_order(c, *, rider_rate=None, item_price=1000, subtotal_mult=1,
                       distance_far=False, peak=False):
    if distance_far:
        rest = make_restaurant(c, lat=0.0, lng=0.0, rate=rider_rate)
        cust = make_customer(c, lat=0.0, lng=0.05)  # ~5.5 km
    else:
        rest = make_restaurant(c, lat=0.0, lng=0.0, rate=rider_rate)
        cust = make_customer(c, lat=0.0, lng=0.0)  # 0 km
    mi = make_menu_item(c, rest["id"], price_cents=item_price)
    rider = make_rider(c, online=True)
    s, b = place_order(c, customer=cust, restaurant=rest,
                       items=[{"menu_item_id": mi["id"], "quantity": subtotal_mult}])
    o = b["data"]
    # Force peak for this order if requested by direct injection (avoid clock dependence)
    from app.store import store
    if peak:
        store.orders[o["id"]]["is_peak"] = True
    c.post(f"/api/orders/{o['id']}/accept", role="Restaurant", user_id=rest["id"])
    c.post(f"/api/orders/{o['id']}/start-preparing", role="Restaurant", user_id=rest["id"])
    a = [x for x in store.assignments.values() if x["order_id"] == o["id"]][0]
    c.post(f"/api/assignments/{a['id']}/accept", role="Rider", user_id=rider["id"])
    c.post(f"/api/orders/{o['id']}/ready", role="Restaurant", user_id=rest["id"])
    c.post(f"/api/assignments/{a['id']}/pickup", role="Rider", user_id=rider["id"])
    s, b = c.post(f"/api/assignments/{a['id']}/deliver", role="Rider", user_id=rider["id"])
    assert s == 200, b
    return rest, cust, rider, o, a, b["data"]


@test("on-time delivery: final fee == solo fee, no late fine, no minutes_late")
def t():
    c = Client()
    rest, cust, rider, o, a, ad = _deliver_solo_order(c)
    s, b = c.get(f"/api/orders/{o['id']}", role="PlatformAdmin")
    assert b["data"]["status"] == "DELIVERED"
    assert b["data"]["minutes_late"] == 0
    assert b["data"]["final_delivery_fee_cents"] == 300
    assert b["data"]["payment_status"] == "CAPTURED"
    # No late fine
    from app.store import store
    late_fines = [f for f in store.fines.values() if f["reason"] == "LATE_DELIVERY"]
    assert len(late_fines) == 0


@test("delivery credits rider's wallet by final fee")
def t():
    c = Client()
    rest, cust, rider, o, a, ad = _deliver_solo_order(c)
    s, b = c.get(f"/api/riders/{rider['id']}", role="Rider", user_id=rider["id"])
    assert b["data"]["wallet_balance_cents"] == 300


@test("delivery increments restaurant pending_settlement by (subtotal - final_commission)")
def t():
    c = Client()
    rest, cust, rider, o, a, ad = _deliver_solo_order(c, item_price=2000)
    s, b = c.get(f"/api/restaurants/{rest['id']}", role="PlatformAdmin")
    # subtotal 2000, commission 300 -> pending = 1700
    assert b["data"]["pending_settlement_cents"] == 1700


@test("late delivery creates LATE_DELIVERY fine and debits wallet; on_time_rate updates")
def t():
    c = Client()
    rest = make_restaurant(c, lat=0, lng=0)
    mi = make_menu_item(c, rest["id"], price_cents=1000)
    cust = make_customer(c, lat=0, lng=0)
    rider = make_rider(c)
    s, b = place_order(c, customer=cust, restaurant=rest,
                       items=[{"menu_item_id": mi["id"], "quantity": 1}])
    o = b["data"]
    c.post(f"/api/orders/{o['id']}/accept", role="Restaurant", user_id=rest["id"])
    c.post(f"/api/orders/{o['id']}/start-preparing", role="Restaurant", user_id=rest["id"])
    from app.store import store
    a = [x for x in store.assignments.values() if x["order_id"] == o["id"]][0]
    c.post(f"/api/assignments/{a['id']}/accept", role="Rider", user_id=rider["id"])
    c.post(f"/api/orders/{o['id']}/ready", role="Restaurant", user_id=rest["id"])
    c.post(f"/api/assignments/{a['id']}/pickup", role="Rider", user_id=rider["id"])
    # Advance clock past promised time. Promised is +45min, so push +50 min
    c.post("/api/_clock/advance", role="PlatformAdmin", body={"seconds": 50 * 60})
    s, b = c.post(f"/api/assignments/{a['id']}/deliver", role="Rider", user_id=rider["id"])
    assert s == 200
    s, ob = c.get(f"/api/orders/{o['id']}", role="PlatformAdmin")
    assert ob["data"]["minutes_late"] == 5
    # Tier 1 fine = 200
    fines = [f for f in store.fines.values() if f["reason"] == "LATE_DELIVERY"]
    assert len(fines) == 1 and fines[0]["amount_cents"] == 200
    # Wallet = +300 (fee) - 200 (fine) = 100
    s, rb = c.get(f"/api/riders/{rider['id']}", role="Rider", user_id=rider["id"])
    assert rb["data"]["wallet_balance_cents"] == 100


@test("delivery uses commission_rate_override if set at delivery time (post-placement change)")
def t():
    c = Client()
    rest = make_restaurant(c, lat=0, lng=0)  # No override at registration
    mi = make_menu_item(c, rest["id"], price_cents=10000)
    cust = make_customer(c, lat=0, lng=0)
    rider = make_rider(c)
    s, b = place_order(c, customer=cust, restaurant=rest,
                       items=[{"menu_item_id": mi["id"], "quantity": 1}])
    o = b["data"]
    # provisional_commission = tiered(10000) = 1500
    assert o["provisional_commission_cents"] == 1500
    # Admin sets override mid-flight
    c.patch(f"/api/restaurants/{rest['id']}", role="PlatformAdmin",
            body={"commission_rate_override": 0.10})
    c.post(f"/api/orders/{o['id']}/accept", role="Restaurant", user_id=rest["id"])
    c.post(f"/api/orders/{o['id']}/start-preparing", role="Restaurant", user_id=rest["id"])
    from app.store import store
    a = [x for x in store.assignments.values() if x["order_id"] == o["id"]][0]
    c.post(f"/api/assignments/{a['id']}/accept", role="Rider", user_id=rider["id"])
    c.post(f"/api/orders/{o['id']}/ready", role="Restaurant", user_id=rest["id"])
    c.post(f"/api/assignments/{a['id']}/pickup", role="Rider", user_id=rider["id"])
    s, b = c.post(f"/api/assignments/{a['id']}/deliver", role="Rider", user_id=rider["id"])
    assert s == 200
    s, ob = c.get(f"/api/orders/{o['id']}", role="PlatformAdmin")
    # final = 10000 * 0.10 = 1000
    assert ob["data"]["final_commission_cents"] == 1000
