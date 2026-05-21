"""Restaurant-side order flow (§3.5)."""
from __future__ import annotations

from ._factories import make_customer, make_menu_item, make_restaurant, make_rider, place_order
from ._harness import Client, expect_err, expect_ok, test


def _world(c):
    rest = make_restaurant(c, lat=37.0, lng=-122.0)
    mi = make_menu_item(c, rest["id"], price_cents=1000)
    cust = make_customer(c, lat=37.0, lng=-122.0)
    rider = make_rider(c, online=True)
    s, b = place_order(c, customer=cust, restaurant=rest,
                       items=[{"menu_item_id": mi["id"], "quantity": 1}])
    return rest, mi, cust, rider, b["data"]


@test("restaurant accept: PLACED -> RESTAURANT_ACCEPTED")
def t():
    c = Client()
    rest, mi, cust, rider, o = _world(c)
    s, b = c.post(f"/api/orders/{o['id']}/accept", role="Restaurant", user_id=rest["id"])
    assert s == 200
    assert b["data"]["status"] == "RESTAURANT_ACCEPTED"
    assert b["data"]["payment_status"] == "AUTHORIZED"  # unchanged


@test("accept by wrong restaurant -> ERR_FORBIDDEN")
def t():
    c = Client()
    rest, mi, cust, rider, o = _world(c)
    other = make_restaurant(c, name="Other")
    s, b = c.post(f"/api/orders/{o['id']}/accept", role="Restaurant", user_id=other["id"])
    assert s == 403


@test("accept twice -> ERR_INVALID_STATE")
def t():
    c = Client()
    rest, mi, cust, rider, o = _world(c)
    c.post(f"/api/orders/{o['id']}/accept", role="Restaurant", user_id=rest["id"])
    s, b = c.post(f"/api/orders/{o['id']}/accept", role="Restaurant", user_id=rest["id"])
    assert s == 409


@test("cancel PLACED moves to CANCELLED, VOIDED")
def t():
    c = Client()
    rest, mi, cust, rider, o = _world(c)
    s, b = c.post(f"/api/orders/{o['id']}/cancel", role="Customer", user_id=cust["id"])
    assert s == 200
    assert b["data"]["status"] == "CANCELLED"
    assert b["data"]["payment_status"] == "VOIDED"


@test("cancel non-PLACED -> ERR_INVALID_STATE")
def t():
    c = Client()
    rest, mi, cust, rider, o = _world(c)
    c.post(f"/api/orders/{o['id']}/accept", role="Restaurant", user_id=rest["id"])
    s, b = c.post(f"/api/orders/{o['id']}/cancel", role="Customer", user_id=cust["id"])
    assert s == 409


@test("start-preparing requires RESTAURANT_ACCEPTED state")
def t():
    c = Client()
    rest, mi, cust, rider, o = _world(c)
    s, b = c.post(f"/api/orders/{o['id']}/start-preparing", role="Restaurant", user_id=rest["id"])
    assert s == 409
    c.post(f"/api/orders/{o['id']}/accept", role="Restaurant", user_id=rest["id"])
    s, b = c.post(f"/api/orders/{o['id']}/start-preparing", role="Restaurant", user_id=rest["id"])
    assert s == 200 and b["data"]["status"] == "PREPARING"


@test("ready requires an assignment in ACCEPTED or PICKED_UP")
def t():
    c = Client()
    rest, mi, cust, rider, o = _world(c)
    c.post(f"/api/orders/{o['id']}/accept", role="Restaurant", user_id=rest["id"])
    c.post(f"/api/orders/{o['id']}/start-preparing", role="Restaurant", user_id=rest["id"])
    # No rider accepted yet -> ready should fail
    s, b = c.post(f"/api/orders/{o['id']}/ready", role="Restaurant", user_id=rest["id"])
    assert s == 409, b
    # Rider accepts
    from app.store import store
    a = [x for x in store.assignments.values() if x["order_id"] == o["id"]][0]
    s, _ = c.post(f"/api/assignments/{a['id']}/accept", role="Rider", user_id=rider["id"])
    assert s == 200
    s, b = c.post(f"/api/orders/{o['id']}/ready", role="Restaurant", user_id=rest["id"])
    assert s == 200 and b["data"]["status"] == "READY_FOR_PICKUP"
