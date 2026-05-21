"""Dispatch + Assignment lifecycle (§3.6)."""
from __future__ import annotations

from ._factories import make_customer, make_menu_item, make_restaurant, make_rider, place_order
from ._harness import Client, expect_err, expect_ok, test


def _flow_until_preparing(c, with_riders=1):
    rest = make_restaurant(c, lat=37.0, lng=-122.0)
    mi = make_menu_item(c, rest["id"], price_cents=1000)
    cust = make_customer(c, lat=37.0, lng=-122.0)
    riders = [make_rider(c, phone=f"R{i}", online=True) for i in range(with_riders)]
    s, b = place_order(c, customer=cust, restaurant=rest,
                       items=[{"menu_item_id": mi["id"], "quantity": 1}])
    o = b["data"]
    c.post(f"/api/orders/{o['id']}/accept", role="Restaurant", user_id=rest["id"])
    c.post(f"/api/orders/{o['id']}/start-preparing", role="Restaurant", user_id=rest["id"])
    return rest, mi, cust, riders, o


@test("start-preparing opens an OFFERED Assignment")
def t():
    c = Client()
    rest, mi, cust, riders, o = _flow_until_preparing(c)
    from app.store import store
    matches = [a for a in store.assignments.values() if a["order_id"] == o["id"]]
    assert len(matches) == 1
    assert matches[0]["status"] == "OFFERED"
    assert matches[0]["rider_id"] == riders[0]["id"]


@test("dispatch without available riders -> ERR_INVALID_STATE")
def t():
    c = Client()
    rest = make_restaurant(c, lat=37.0, lng=-122.0)
    mi = make_menu_item(c, rest["id"], price_cents=1000)
    cust = make_customer(c, lat=37.0, lng=-122.0)
    s, b = place_order(c, customer=cust, restaurant=rest,
                       items=[{"menu_item_id": mi["id"], "quantity": 1}])
    o = b["data"]
    c.post(f"/api/orders/{o['id']}/accept", role="Restaurant", user_id=rest["id"])
    # Explicit dispatch with no riders -> ERR_INVALID_STATE
    s, b = c.post(f"/api/orders/{o['id']}/dispatch", role="PlatformAdmin")
    assert s == 409 and b["data"]["error_id"] == "ERR_INVALID_STATE"


@test("rider accept moves Assignment OFFERED -> ACCEPTED, rider AVAILABLE -> ON_DELIVERY")
def t():
    c = Client()
    rest, mi, cust, riders, o = _flow_until_preparing(c)
    from app.store import store
    a = [x for x in store.assignments.values() if x["order_id"] == o["id"]][0]
    s, b = c.post(f"/api/assignments/{a['id']}/accept", role="Rider", user_id=riders[0]["id"])
    assert s == 200 and b["data"]["status"] == "ACCEPTED"
    s, br = c.get(f"/api/riders/{riders[0]['id']}", role="Rider", user_id=riders[0]["id"])
    assert br["data"]["status"] == "ON_DELIVERY"


@test("second rider racing to accept -> ERR_ORDER_ALREADY_ASSIGNED")
def t():
    c = Client()
    rest, mi, cust, riders, o = _flow_until_preparing(c, with_riders=2)
    from app.store import store
    a1 = [x for x in store.assignments.values() if x["order_id"] == o["id"]][0]
    first_rider_id = a1["rider_id"]
    other_rider_id = [r["id"] for r in riders if r["id"] != first_rider_id][0]
    # Inject a second OFFERED assignment for the OTHER rider for the same order
    from app.entities import init_unversioned
    a2 = init_unversioned("Assignment")
    a2.update({
        "order_id": o["id"], "rider_id": other_rider_id, "status": "OFFERED",
        "offered_at": "2020-01-01T00:00:00.000Z", "accepted_at": None, "picked_up_at": None,
        "delivered_at": None, "route_group_id": None, "final_delivery_fee_cents": None,
    })
    store.assignments[a2["id"]] = a2
    # First rider accepts
    s, _ = c.post(f"/api/assignments/{a1['id']}/accept", role="Rider", user_id=first_rider_id)
    assert s == 200
    # Second rider tries to accept
    s, b = c.post(f"/api/assignments/{a2['id']}/accept", role="Rider", user_id=other_rider_id)
    assert s == 409 and b["data"]["error_id"] == "ERR_ORDER_ALREADY_ASSIGNED"


@test("rider reject -> REJECTED + redispatch to next rider")
def t():
    c = Client()
    rest, mi, cust, riders, o = _flow_until_preparing(c, with_riders=2)
    from app.store import store
    a = [x for x in store.assignments.values() if x["order_id"] == o["id"]][0]
    target = a["rider_id"]
    other_id = riders[1]["id"] if target == riders[0]["id"] else riders[0]["id"]
    s, b = c.post(f"/api/assignments/{a['id']}/reject", role="Rider", user_id=target)
    assert s == 200 and b["data"]["status"] == "REJECTED"
    # A new OFFERED assignment now exists for the other rider
    new_offers = [x for x in store.assignments.values()
                  if x["order_id"] == o["id"] and x["status"] == "OFFERED"]
    assert len(new_offers) == 1
    assert new_offers[0]["rider_id"] == other_id


@test("rider pickup ACCEPTED+READY_FOR_PICKUP -> PICKED_UP")
def t():
    c = Client()
    rest, mi, cust, riders, o = _flow_until_preparing(c)
    from app.store import store
    a = [x for x in store.assignments.values() if x["order_id"] == o["id"]][0]
    c.post(f"/api/assignments/{a['id']}/accept", role="Rider", user_id=riders[0]["id"])
    c.post(f"/api/orders/{o['id']}/ready", role="Restaurant", user_id=rest["id"])
    s, b = c.post(f"/api/assignments/{a['id']}/pickup", role="Rider", user_id=riders[0]["id"])
    assert s == 200 and b["data"]["status"] == "PICKED_UP"
    # Order cascaded to PICKED_UP
    s, b = c.get(f"/api/orders/{o['id']}", role="PlatformAdmin")
    assert b["data"]["status"] == "PICKED_UP"


@test("rider cancel ACCEPTED -> CANCELLED + RIDER_NO_SHOW fine + wallet -500")
def t():
    c = Client()
    rest, mi, cust, riders, o = _flow_until_preparing(c)
    from app.store import store
    a = [x for x in store.assignments.values() if x["order_id"] == o["id"]][0]
    c.post(f"/api/assignments/{a['id']}/accept", role="Rider", user_id=riders[0]["id"])
    s, b = c.post(f"/api/assignments/{a['id']}/cancel", role="Rider", user_id=riders[0]["id"])
    assert s == 200 and b["data"]["status"] == "CANCELLED"
    # Fine exists with amount 500
    fines = [f for f in store.fines.values()
             if f["subject_type"] == "RIDER" and f["subject_id"] == riders[0]["id"]
             and f["reason"] == "RIDER_NO_SHOW"]
    assert len(fines) == 1 and fines[0]["amount_cents"] == 500
    s, br = c.get(f"/api/riders/{riders[0]['id']}", role="Rider", user_id=riders[0]["id"])
    assert br["data"]["wallet_balance_cents"] == -500


@test("go-offline forbidden while OFFERED/ACCEPTED/PICKED_UP assignment exists")
def t():
    c = Client()
    rest, mi, cust, riders, o = _flow_until_preparing(c)
    s, b = c.post(f"/api/riders/{riders[0]['id']}/go-offline",
                  role="Rider", user_id=riders[0]["id"])
    # Rider is AVAILABLE but has OFFERED assignment
    assert s == 409
