"""Restaurant lifecycle (§3.1)."""
from __future__ import annotations

from ._factories import make_restaurant
from ._harness import Client, expect_err, expect_ok, test


@test("restaurant starts in PENDING_APPROVAL, pending_settlement=0, version=1")
def t():
    c = Client()
    r = make_restaurant(c, approve=False)
    assert r["status"] == "PENDING_APPROVAL"
    assert r["pending_settlement_cents"] == 0
    assert r["version"] == 1
    assert r["commission_rate_override"] is None


@test("PlatformAdmin can set commission_rate_override at registration")
def t():
    c = Client()
    r = make_restaurant(c, approve=False, rate=0.20)
    assert r["commission_rate_override"] == 0.20


@test("commission_rate_override out of [0.05, 0.35] rejected")
def t():
    c = Client()
    s, b = c.post("/api/restaurants", role="PlatformAdmin",
                  body={"name": "X", "address": "a", "lat": 0, "lng": 0,
                        "commission_rate_override": 0.04})
    assert s == 422


@test("name must be unique among active (non-CLOSED)")
def t():
    c = Client()
    make_restaurant(c, name="Dup", approve=False)
    s, b = c.post("/api/restaurants", role="PlatformAdmin",
                  body={"name": "Dup", "address": "a", "lat": 0, "lng": 0})
    assert s == 422


@test("approve PENDING_APPROVAL -> ACTIVE")
def t():
    c = Client()
    r = make_restaurant(c, approve=False)
    s, b = c.post(f"/api/restaurants/{r['id']}/approve", role="PlatformAdmin")
    assert s == 200
    assert b["data"]["status"] == "ACTIVE"
    assert b["data"]["version"] == 2


@test("approve non-PENDING -> ERR_INVALID_STATE")
def t():
    c = Client()
    r = make_restaurant(c, approve=True)
    s, b = c.post(f"/api/restaurants/{r['id']}/approve", role="PlatformAdmin")
    assert s == 409 and b["data"]["error_id"] == "ERR_INVALID_STATE"


@test("suspend ACTIVE cascades cancellation to PLACED orders")
def t():
    c = Client()
    from ._factories import make_customer, make_menu_item, place_order
    rest = make_restaurant(c)
    mi = make_menu_item(c, rest["id"], price_cents=500)
    cust = make_customer(c)
    s, b = place_order(c, customer=cust, restaurant=rest,
                       items=[{"menu_item_id": mi["id"], "quantity": 1}])
    assert s == 201
    order = b["data"]
    # Suspend the restaurant
    s, b = c.post(f"/api/restaurants/{rest['id']}/suspend", role="PlatformAdmin")
    assert s == 200 and b["data"]["status"] == "SUSPENDED"
    # The order should be CANCELLED with payment_status VOIDED
    s, b = c.get(f"/api/orders/{order['id']}", role="PlatformAdmin")
    assert s == 200
    assert b["data"]["status"] == "CANCELLED"
    assert b["data"]["payment_status"] == "VOIDED"


@test("reinstate SUSPENDED -> ACTIVE")
def t():
    c = Client()
    r = make_restaurant(c)
    c.post(f"/api/restaurants/{r['id']}/suspend", role="PlatformAdmin")
    s, b = c.post(f"/api/restaurants/{r['id']}/reinstate", role="PlatformAdmin")
    assert s == 200 and b["data"]["status"] == "ACTIVE"


@test("settle zeroes pending_settlement_cents")
def t():
    c = Client()
    r = make_restaurant(c)
    # Manually inject a pending_settlement via direct store access for this targeted test
    from app.store import store
    store.restaurants[r["id"]]["pending_settlement_cents"] = 12345
    s, b = c.post(f"/api/restaurants/{r['id']}/settle", role="PlatformAdmin")
    assert s == 200
    assert b["data"]["pending_settlement_cents"] == 0


@test("Restaurant role can PATCH own fields; another restaurant cannot")
def t():
    c = Client()
    r1 = make_restaurant(c, name="R1")
    r2 = make_restaurant(c, name="R2")
    s, b = c.patch(f"/api/restaurants/{r1['id']}", role="Restaurant", user_id=r1["id"],
                   body={"address": "NewAddr"})
    assert s == 200 and b["data"]["address"] == "NewAddr"
    # Other restaurant attempts patch
    s, b = c.patch(f"/api/restaurants/{r1['id']}", role="Restaurant", user_id=r2["id"],
                   body={"address": "Hack"})
    assert s == 403 and b["data"]["error_id"] == "ERR_FORBIDDEN"


@test("OCC: stale version on PATCH -> ERR_VERSION_CONFLICT")
def t():
    c = Client()
    r = make_restaurant(c)
    # current version after register + approve = 2
    s, b = c.patch(f"/api/restaurants/{r['id']}", role="PlatformAdmin",
                   body={"address": "x", "version": 99})
    assert s == 409 and b["data"]["error_id"] == "ERR_VERSION_CONFLICT"


@test("OCC: matching version succeeds and increments")
def t():
    c = Client()
    r = make_restaurant(c)
    # v=2 after approve
    s, b = c.patch(f"/api/restaurants/{r['id']}", role="PlatformAdmin",
                   body={"address": "x", "version": 2})
    assert s == 200
    assert b["data"]["version"] == 3
