"""Validation pipeline priority ordering (§2.6, §2.7)."""
from __future__ import annotations

from ._factories import make_customer, make_menu_item, make_restaurant, make_rider, place_order
from ._harness import Client, expect_err, expect_ok, test


@test("step 1: missing X-User-ID -> ERR_AUTH_REQUIRED")
def t():
    c = Client()
    resp = c.c.open("/api/restaurants", method="POST",
                    headers={"X-User-Role": "PlatformAdmin", "Content-Type": "application/json"},
                    json={"name": "X", "address": "1", "lat": 0, "lng": 0})
    assert resp.status_code == 401
    assert resp.get_json()["data"]["error_id"] == "ERR_AUTH_REQUIRED"


@test("step 1: missing X-User-Role -> ERR_AUTH_REQUIRED")
def t():
    c = Client()
    resp = c.c.open("/api/restaurants", method="POST",
                    headers={"X-User-ID": "u1", "Content-Type": "application/json"},
                    json={"name": "X", "address": "1", "lat": 0, "lng": 0})
    assert resp.status_code == 401
    assert resp.get_json()["data"]["error_id"] == "ERR_AUTH_REQUIRED"


@test("step 1: unrecognized role -> ERR_AUTH_REQUIRED")
def t():
    c = Client()
    expect_err(c.post("/api/restaurants", role="NotARole",
                      body={"name": "X", "address": "1", "lat": 0, "lng": 0}),
               "ERR_AUTH_REQUIRED", http=401)


@test("step 2: wrong role -> ERR_FORBIDDEN before any other check")
def t():
    c = Client()
    expect_err(c.post("/api/restaurants", role="Customer", user_id="anyone",
                      body={"name": "X", "address": "1", "lat": 0, "lng": 0}),
               "ERR_FORBIDDEN", http=403)


@test("step 3: unknown path id -> ERR_NOT_FOUND")
def t():
    c = Client()
    expect_err(c.get("/api/restaurants/nonexistent", role="PlatformAdmin"),
               "ERR_NOT_FOUND", http=404)


@test("step 3+4: nested path id checks left-to-right (restaurant first, then menu item)")
def t():
    c = Client()
    # Listing menu items under a non-existent restaurant
    expect_err(c.get("/api/restaurants/nope/menu-items", role="PlatformAdmin"),
               "ERR_NOT_FOUND", http=404)


@test("step 4: unknown customer_id in body -> ERR_NOT_FOUND")
def t():
    c = Client()
    rest = make_restaurant(c)
    mi = make_menu_item(c, rest["id"])
    expect_err(c.post("/api/orders", role="Customer", user_id="ghost",
                      body={"customer_id": "ghost", "restaurant_id": rest["id"],
                            "items": [{"menu_item_id": mi["id"], "quantity": 1}]}),
               "ERR_NOT_FOUND", http=404)


@test("step 4: unknown restaurant_id in body -> ERR_NOT_FOUND")
def t():
    c = Client()
    cust = make_customer(c)
    expect_err(c.post("/api/orders", role="Customer", user_id=cust["id"],
                      body={"customer_id": cust["id"], "restaurant_id": "nope",
                            "items": [{"menu_item_id": "x", "quantity": 1}]}),
               "ERR_NOT_FOUND", http=404)


@test("step 5: identity mismatch -> ERR_FORBIDDEN after FK existence")
def t():
    c = Client()
    cust1 = make_customer(c, phone="P1")
    cust2 = make_customer(c, phone="P2")
    rest = make_restaurant(c)
    mi = make_menu_item(c, rest["id"])
    # Caller is cust1 but body says cust2
    expect_err(c.post("/api/orders", role="Customer", user_id=cust1["id"],
                      body={"customer_id": cust2["id"], "restaurant_id": rest["id"],
                            "items": [{"menu_item_id": mi["id"], "quantity": 1}]}),
               "ERR_FORBIDDEN", http=403)


@test("step 7: ERR_RESTAURANT_UNAVAILABLE (domain) fires after FK+identity passes")
def t():
    c = Client()
    rest = make_restaurant(c)
    mi = make_menu_item(c, rest["id"])
    cust = make_customer(c)
    # Suspend restaurant -> placement should fail at the domain check
    c.post(f"/api/restaurants/{rest['id']}/suspend", role="PlatformAdmin")
    expect_err(place_order(c, customer=cust, restaurant=rest,
                           items=[{"menu_item_id": mi["id"], "quantity": 1}]),
               "ERR_RESTAURANT_UNAVAILABLE", http=422)


@test("step 11: missing required field -> ERR_VALIDATION")
def t():
    c = Client()
    expect_err(c.post("/api/restaurants", role="PlatformAdmin",
                      body={"address": "X", "lat": 0, "lng": 0}),
               "ERR_VALIDATION", http=422)


@test("step 11: wrong type for required field -> ERR_VALIDATION")
def t():
    c = Client()
    expect_err(c.post("/api/restaurants", role="PlatformAdmin",
                      body={"name": "X", "address": "X", "lat": "notanumber", "lng": 0}),
               "ERR_VALIDATION", http=422)


@test("ERR_NOT_FOUND comes before ERR_FORBIDDEN when path id missing")
def t():
    c = Client()
    # Customer role looking up a non-existent restaurant
    expect_err(c.get("/api/restaurants/nope", role="Customer", user_id="anyone"),
               "ERR_NOT_FOUND", http=404)


@test("place order: ERR_ORDER_INVALID (shape) when items empty even if restaurant inactive")
def t():
    c = Client()
    rest = make_restaurant(c)
    cust = make_customer(c)
    c.post(f"/api/restaurants/{rest['id']}/suspend", role="PlatformAdmin")
    # Both restaurant-unavailable AND items-empty apply; restaurant check (#7) fires before #11
    # Per PRD #7 > #11
    expect_err(place_order(c, customer=cust, restaurant=rest, items=[]),
               "ERR_RESTAURANT_UNAVAILABLE", http=422)


@test("PATCH version conflict only after field validation passes")
def t():
    c = Client()
    rest = make_restaurant(c, name="A1")
    # Send bad rate AND wrong version. Field validation (#11) > OCC (#12).
    expect_err(c.patch(f"/api/restaurants/{rest['id']}", role="PlatformAdmin",
                       body={"commission_rate_override": 99.0, "version": 999}),
               "ERR_VALIDATION", http=422)
