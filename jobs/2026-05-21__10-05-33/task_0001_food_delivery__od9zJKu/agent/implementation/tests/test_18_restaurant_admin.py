"""Restaurant admin lifecycle: approve, suspend (with cancel cascade), reinstate, settle (§3.1, §3.8)."""
from __future__ import annotations

from ._factories import make_customer, make_menu_item, make_restaurant, make_rider, place_order
from ._harness import Client, expect_err, expect_ok, test


@test("register restaurant starts in PENDING_APPROVAL")
def t():
    c = Client()
    s, b = c.post("/api/restaurants", role="PlatformAdmin",
                  body={"name": "X", "address": "1 St", "lat": 0, "lng": 0})
    assert s == 201
    assert b["data"]["status"] == "PENDING_APPROVAL"
    assert b["data"]["pending_settlement_cents"] == 0
    assert b["data"]["commission_rate_override"] is None


@test("duplicate restaurant name (non-CLOSED) -> ERR_VALIDATION")
def t():
    c = Client()
    s, b = c.post("/api/restaurants", role="PlatformAdmin",
                  body={"name": "Dupe", "address": "1 St", "lat": 0, "lng": 0})
    assert s == 201
    expect_err(c.post("/api/restaurants", role="PlatformAdmin",
                      body={"name": "Dupe", "address": "2 Av", "lat": 0, "lng": 0}),
               "ERR_VALIDATION", http=422)


@test("approve PENDING -> ACTIVE")
def t():
    c = Client()
    s, b = c.post("/api/restaurants", role="PlatformAdmin",
                  body={"name": "Y", "address": "1 St", "lat": 0, "lng": 0})
    rid = b["data"]["id"]
    s, b = c.post(f"/api/restaurants/{rid}/approve", role="PlatformAdmin")
    assert s == 200 and b["data"]["status"] == "ACTIVE"


@test("approve non-PENDING -> ERR_INVALID_STATE")
def t():
    c = Client()
    rest = make_restaurant(c, name="Z")
    expect_err(c.post(f"/api/restaurants/{rest['id']}/approve", role="PlatformAdmin"),
               "ERR_INVALID_STATE", http=409)


@test("suspend ACTIVE cancels all PLACED orders for it")
def t():
    c = Client()
    rest = make_restaurant(c, name="S1")
    mi = make_menu_item(c, rest["id"], price_cents=1000)
    cust1 = make_customer(c, phone="P1")
    cust2 = make_customer(c, phone="P2")
    cust3 = make_customer(c, phone="P3")
    # Three orders: 2 PLACED, 1 advanced beyond PLACED
    s, b = place_order(c, customer=cust1, restaurant=rest,
                       items=[{"menu_item_id": mi["id"], "quantity": 1}])
    o1 = b["data"]
    s, b = place_order(c, customer=cust2, restaurant=rest,
                       items=[{"menu_item_id": mi["id"], "quantity": 1}])
    o2 = b["data"]
    s, b = place_order(c, customer=cust3, restaurant=rest,
                       items=[{"menu_item_id": mi["id"], "quantity": 1}])
    o3 = b["data"]
    c.post(f"/api/orders/{o3['id']}/accept", role="Restaurant", user_id=rest["id"])
    c.post(f"/api/restaurants/{rest['id']}/suspend", role="PlatformAdmin")
    from app.store import store
    assert store.restaurants[rest["id"]]["status"] == "SUSPENDED"
    assert store.orders[o1["id"]]["status"] == "CANCELLED"
    assert store.orders[o2["id"]]["status"] == "CANCELLED"
    assert store.orders[o1["id"]]["payment_status"] == "VOIDED"
    # The RESTAURANT_ACCEPTED one is not in PLACED, so it's NOT cancelled by suspend
    assert store.orders[o3["id"]]["status"] == "RESTAURANT_ACCEPTED"


@test("suspend non-ACTIVE -> ERR_INVALID_STATE")
def t():
    c = Client()
    s, b = c.post("/api/restaurants", role="PlatformAdmin",
                  body={"name": "Q", "address": "1", "lat": 0, "lng": 0})
    rid = b["data"]["id"]
    expect_err(c.post(f"/api/restaurants/{rid}/suspend", role="PlatformAdmin"),
               "ERR_INVALID_STATE", http=409)


@test("reinstate SUSPENDED -> ACTIVE")
def t():
    c = Client()
    rest = make_restaurant(c, name="W")
    c.post(f"/api/restaurants/{rest['id']}/suspend", role="PlatformAdmin")
    s, b = c.post(f"/api/restaurants/{rest['id']}/reinstate", role="PlatformAdmin")
    assert s == 200 and b["data"]["status"] == "ACTIVE"


@test("settle zeros pending_settlement_cents")
def t():
    c = Client()
    rest = make_restaurant(c, name="T")
    from app.store import store
    store.restaurants[rest["id"]]["pending_settlement_cents"] = 9999
    s, b = c.post(f"/api/restaurants/{rest['id']}/settle", role="PlatformAdmin")
    assert s == 200 and b["data"]["pending_settlement_cents"] == 0


@test("PATCH lat/lng/address/commission_rate_override updates fields")
def t():
    c = Client()
    rest = make_restaurant(c, name="U", lat=0, lng=0)
    s, b = c.patch(f"/api/restaurants/{rest['id']}", role="PlatformAdmin",
                   body={"address": "New Addr", "lat": 1.0, "lng": 2.0,
                         "commission_rate_override": 0.15})
    assert s == 200
    assert b["data"]["address"] == "New Addr"
    assert b["data"]["lat"] == 1.0
    assert b["data"]["commission_rate_override"] == 0.15


@test("PATCH with stale version -> ERR_VERSION_CONFLICT")
def t():
    c = Client()
    rest = make_restaurant(c, name="V")
    # First PATCH succeeds (no version), bumping version to 3 (registered=1, approved=2)
    s, b = c.patch(f"/api/restaurants/{rest['id']}", role="PlatformAdmin",
                   body={"address": "A"})
    assert s == 200
    cur = b["data"]["version"]
    expect_err(c.patch(f"/api/restaurants/{rest['id']}", role="PlatformAdmin",
                       body={"address": "B", "version": cur - 1}),
               "ERR_VERSION_CONFLICT", http=409)


@test("PATCH with matching version -> OK, version bumps")
def t():
    c = Client()
    rest = make_restaurant(c, name="W2")
    s, b = c.patch(f"/api/restaurants/{rest['id']}", role="PlatformAdmin",
                   body={"address": "X"})
    cur = b["data"]["version"]
    s, b = c.patch(f"/api/restaurants/{rest['id']}", role="PlatformAdmin",
                   body={"address": "Y", "version": cur})
    assert s == 200 and b["data"]["version"] == cur + 1


@test("Restaurant role cannot PATCH another restaurant -> ERR_FORBIDDEN")
def t():
    c = Client()
    r1 = make_restaurant(c, name="A1")
    r2 = make_restaurant(c, name="A2")
    expect_err(c.patch(f"/api/restaurants/{r1['id']}", role="Restaurant", user_id=r2["id"],
                       body={"address": "Hax"}),
               "ERR_FORBIDDEN", http=403)


@test("placement against non-ACTIVE restaurant (SUSPENDED) -> ERR_RESTAURANT_UNAVAILABLE")
def t():
    c = Client()
    rest = make_restaurant(c, name="S2", lat=0, lng=0)
    mi = make_menu_item(c, rest["id"])
    cust = make_customer(c)
    c.post(f"/api/restaurants/{rest['id']}/suspend", role="PlatformAdmin")
    expect_err(place_order(c, customer=cust, restaurant=rest,
                           items=[{"menu_item_id": mi["id"], "quantity": 1}]),
               "ERR_RESTAURANT_UNAVAILABLE", http=422)
