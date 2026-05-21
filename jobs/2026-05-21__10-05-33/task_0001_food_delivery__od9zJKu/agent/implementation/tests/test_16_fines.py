"""Fines list/read/waive (§3.11)."""
from __future__ import annotations

from ._factories import make_customer, make_menu_item, make_restaurant, make_rider, place_order
from ._harness import Client, expect_err, expect_ok, test


def _produce_rider_fine(c, *, online=True):
    """Cause a RIDER_NO_SHOW fine by canceling after accept."""
    rest = make_restaurant(c, lat=0.0, lng=0.0)
    mi = make_menu_item(c, rest["id"], price_cents=1000)
    cust = make_customer(c, lat=0.0, lng=0.0)
    rider = make_rider(c, online=online)
    s, b = place_order(c, customer=cust, restaurant=rest,
                       items=[{"menu_item_id": mi["id"], "quantity": 1}])
    o = b["data"]
    c.post(f"/api/orders/{o['id']}/accept", role="Restaurant", user_id=rest["id"])
    c.post(f"/api/orders/{o['id']}/start-preparing", role="Restaurant", user_id=rest["id"])
    from app.store import store
    a = [x for x in store.assignments.values() if x["order_id"] == o["id"]][0]
    c.post(f"/api/assignments/{a['id']}/accept", role="Rider", user_id=rider["id"])
    c.post(f"/api/assignments/{a['id']}/cancel", role="Rider", user_id=rider["id"])
    return rest, cust, rider, o, [f for f in store.fines.values()
                                   if f["subject_id"] == rider["id"]][0]


@test("Rider can read their own fine")
def t():
    c = Client()
    rest, cust, rider, o, fine = _produce_rider_fine(c)
    s, b = c.get(f"/api/fines/{fine['id']}", role="Rider", user_id=rider["id"])
    assert s == 200 and b["data"]["id"] == fine["id"]


@test("Rider cannot read another rider's fine")
def t():
    c = Client()
    rest, cust, rider, o, fine = _produce_rider_fine(c)
    other = make_rider(c, phone="X1", online=False)
    expect_err(c.get(f"/api/fines/{fine['id']}", role="Rider", user_id=other["id"]),
               "ERR_FORBIDDEN", http=403)


@test("PlatformAdmin and CS can read any fine")
def t():
    c = Client()
    rest, cust, rider, o, fine = _produce_rider_fine(c)
    s, b = c.get(f"/api/fines/{fine['id']}", role="PlatformAdmin")
    assert s == 200
    s, b = c.get(f"/api/fines/{fine['id']}", role="CustomerService")
    assert s == 200


@test("Rider list fines is scoped to their own subject_id")
def t():
    c = Client()
    rest, cust, rider, o, fine = _produce_rider_fine(c)
    # Create another rider's fine
    other = make_rider(c, phone="X1", online=True)
    s, b = place_order(c, customer=make_customer(c, phone="P2"), restaurant=rest,
                       items=[{"menu_item_id": [m for m in __import__("app.store").store.store.menu_items.values()
                                                if m["restaurant_id"] == rest["id"]][0]["id"], "quantity": 1}])
    o2 = b["data"]
    c.post(f"/api/orders/{o2['id']}/accept", role="Restaurant", user_id=rest["id"])
    c.post(f"/api/orders/{o2['id']}/start-preparing", role="Restaurant", user_id=rest["id"])
    from app.store import store
    a = [x for x in store.assignments.values() if x["order_id"] == o2["id"] and x["status"] == "OFFERED"][0]
    c.post(f"/api/assignments/{a['id']}/accept", role="Rider", user_id=a["rider_id"])
    c.post(f"/api/assignments/{a['id']}/cancel", role="Rider", user_id=a["rider_id"])
    # Rider lists their own fines
    s, b = c.get("/api/fines", role="Rider", user_id=rider["id"])
    assert s == 200
    ids = [f["subject_id"] for f in b["data"]]
    assert all(sid == rider["id"] for sid in ids)


@test("waive PENDING fine moves to WAIVED and credits back rider's wallet")
def t():
    c = Client()
    rest, cust, rider, o, fine = _produce_rider_fine(c)
    # Before: wallet -500
    s, rb = c.get(f"/api/riders/{rider['id']}", role="Rider", user_id=rider["id"])
    assert rb["data"]["wallet_balance_cents"] == -500
    s, b = c.post(f"/api/fines/{fine['id']}/waive", role="CustomerService", user_id="cs1")
    assert s == 200 and b["data"]["settlement_status"] == "WAIVED"
    # After: wallet 0
    s, rb = c.get(f"/api/riders/{rider['id']}", role="Rider", user_id=rider["id"])
    assert rb["data"]["wallet_balance_cents"] == 0


@test("waive non-PENDING fine -> ERR_INVALID_STATE")
def t():
    c = Client()
    rest, cust, rider, o, fine = _produce_rider_fine(c)
    c.post(f"/api/fines/{fine['id']}/waive", role="CustomerService", user_id="cs1")
    expect_err(c.post(f"/api/fines/{fine['id']}/waive", role="CustomerService", user_id="cs1"),
               "ERR_INVALID_STATE", http=409)


@test("Customer cannot waive a fine -> ERR_FORBIDDEN")
def t():
    c = Client()
    rest, cust, rider, o, fine = _produce_rider_fine(c)
    expect_err(c.post(f"/api/fines/{fine['id']}/waive", role="Customer", user_id=cust["id"]),
               "ERR_FORBIDDEN", http=403)


@test("Customer fine: waive restores credit_balance")
def t():
    c = Client()
    # Deliver order, request return, customer trust_score < 0.5 -> ABUSIVE_RETURN fine
    rest = make_restaurant(c, lat=0.0, lng=0.0)
    mi = make_menu_item(c, rest["id"], price_cents=2000)
    cust = make_customer(c, lat=0.0, lng=0.0)
    rider = make_rider(c, online=True)
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
    c.post(f"/api/assignments/{a['id']}/deliver", role="Rider", user_id=rider["id"])
    store.customers[cust["id"]]["trust_score"] = 0.3
    s, b = c.post(f"/api/orders/{o['id']}/returns", role="Customer", user_id=cust["id"],
                  body={"reason": "QUALITY_ISSUE", "requested_refund_cents": 500})
    ret = b["data"]
    c.post(f"/api/returns/{ret['id']}/approve", role="CustomerService", user_id="cs1",
           body={"approved_refund_cents": 500})
    # credit_balance went +500 (refund) then -500 (abusive fine debit) = 0
    s, cb = c.get(f"/api/customers/{cust['id']}", role="Customer", user_id=cust["id"])
    assert cb["data"]["credit_balance_cents"] == 0
    fine = [f for f in store.fines.values() if f["reason"] == "ABUSIVE_RETURN"][0]
    s, b = c.post(f"/api/fines/{fine['id']}/waive", role="PlatformAdmin")
    assert s == 200
    s, cb = c.get(f"/api/customers/{cust['id']}", role="Customer", user_id=cust["id"])
    assert cb["data"]["credit_balance_cents"] == 500  # restored


@test("Fines list filter by settlement_status=WAIVED returns only waived")
def t():
    c = Client()
    rest, cust, rider, o, fine = _produce_rider_fine(c)
    c.post(f"/api/fines/{fine['id']}/waive", role="PlatformAdmin")
    s, b = c.get("/api/fines", role="PlatformAdmin", query={"settlement_status": "WAIVED"})
    assert all(f["settlement_status"] == "WAIVED" for f in b["data"])
    assert len(b["data"]) >= 1
