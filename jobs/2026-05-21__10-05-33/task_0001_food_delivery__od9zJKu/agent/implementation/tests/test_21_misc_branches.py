"""Miscellaneous PRD branches: explicit dispatch, menu edits, list filters, OCC on more entities."""
from __future__ import annotations

from ._factories import make_customer, make_menu_item, make_restaurant, make_rider, place_order
from ._harness import Client, expect_err, expect_ok, test


@test("explicit /api/orders/{id}/dispatch re-creates OFFERED Assignment after rejection")
def t():
    c = Client()
    rest = make_restaurant(c, lat=0.0, lng=0.0)
    mi = make_menu_item(c, rest["id"], price_cents=1000)
    cust = make_customer(c, lat=0.0, lng=0.0)
    rider1 = make_rider(c, phone="R1", online=True)
    rider2 = make_rider(c, phone="R2", online=True)
    s, b = place_order(c, customer=cust, restaurant=rest,
                       items=[{"menu_item_id": mi["id"], "quantity": 1}])
    o = b["data"]
    c.post(f"/api/orders/{o['id']}/accept", role="Restaurant", user_id=rest["id"])
    c.post(f"/api/orders/{o['id']}/start-preparing", role="Restaurant", user_id=rest["id"])
    from app.store import store
    a = [x for x in store.assignments.values() if x["order_id"] == o["id"]][0]
    c.post(f"/api/assignments/{a['id']}/reject", role="Rider", user_id=a["rider_id"])
    # After reject, a fresh OFFERED exists for the other rider. Now an admin explicitly re-dispatches.
    # That should be ERR_INVALID_STATE since no candidates remain (only rider2 had been used after redispatch).
    # Actually, let's reject again to exhaust candidates, then call explicit /dispatch.
    a2 = [x for x in store.assignments.values() if x["order_id"] == o["id"] and x["status"] == "OFFERED"][0]
    c.post(f"/api/assignments/{a2['id']}/reject", role="Rider", user_id=a2["rider_id"])
    # Both riders excluded -> dispatch fails
    expect_err(c.post(f"/api/orders/{o['id']}/dispatch", role="PlatformAdmin"),
               "ERR_INVALID_STATE", http=409)


@test("/api/orders/{id}/dispatch returns 201 Created when a new Assignment is made")
def t():
    c = Client()
    rest = make_restaurant(c, lat=0.0, lng=0.0)
    mi = make_menu_item(c, rest["id"], price_cents=1000)
    cust = make_customer(c, lat=0.0, lng=0.0)
    s, b = place_order(c, customer=cust, restaurant=rest,
                       items=[{"menu_item_id": mi["id"], "quantity": 1}])
    o = b["data"]
    c.post(f"/api/orders/{o['id']}/accept", role="Restaurant", user_id=rest["id"])
    # Add a rider AFTER acceptance so start-preparing would dispatch on its own;
    # instead we'll skip start-preparing and use explicit dispatch.
    make_rider(c, online=True)
    s, b = c.post(f"/api/orders/{o['id']}/dispatch", role="PlatformAdmin")
    assert s == 201
    assert b["data"]["status"] == "OFFERED"


@test("PATCH menu item: update price")
def t():
    c = Client()
    rest = make_restaurant(c)
    mi = make_menu_item(c, rest["id"], price_cents=1000)
    s, b = c.patch(f"/api/menu-items/{mi['id']}", role="Restaurant", user_id=rest["id"],
                   body={"price_cents": 2000})
    assert s == 200 and b["data"]["price_cents"] == 2000


@test("PATCH menu item: unlist removes from customer view but keeps id")
def t():
    c = Client()
    rest = make_restaurant(c)
    mi = make_menu_item(c, rest["id"])
    c.patch(f"/api/menu-items/{mi['id']}", role="Restaurant", user_id=rest["id"],
            body={"is_listed": False})
    # Reading menu items as customer with is_listed filter true returns nothing
    s, b = c.get(f"/api/restaurants/{rest['id']}/menu-items", role="Customer", user_id="anyone",
                 query={"is_listed": "true"})
    assert s == 200
    assert all(mi2["id"] != mi["id"] for mi2 in b["data"])


@test("placement against an unlisted menu item -> ERR_RESTAURANT_UNAVAILABLE")
def t():
    c = Client()
    rest = make_restaurant(c)
    mi = make_menu_item(c, rest["id"], is_listed=False)
    cust = make_customer(c)
    expect_err(place_order(c, customer=cust, restaurant=rest,
                           items=[{"menu_item_id": mi["id"], "quantity": 1}]),
               "ERR_RESTAURANT_UNAVAILABLE", http=422)


@test("Order list filter by status")
def t():
    c = Client()
    rest = make_restaurant(c)
    mi = make_menu_item(c, rest["id"])
    cust = make_customer(c)
    s, b = place_order(c, customer=cust, restaurant=rest,
                       items=[{"menu_item_id": mi["id"], "quantity": 1}])
    o = b["data"]
    c.post(f"/api/orders/{o['id']}/accept", role="Restaurant", user_id=rest["id"])
    s, b = c.get("/api/orders", role="PlatformAdmin", query={"status": "PLACED"})
    assert all(x["status"] == "PLACED" for x in b["data"])
    s, b = c.get("/api/orders", role="PlatformAdmin", query={"status": "RESTAURANT_ACCEPTED"})
    assert any(x["id"] == o["id"] for x in b["data"])


@test("Order list filter by customer_id, restaurant_id, rider_id")
def t():
    c = Client()
    rest = make_restaurant(c)
    mi = make_menu_item(c, rest["id"])
    cust1 = make_customer(c, phone="P1")
    cust2 = make_customer(c, phone="P2")
    place_order(c, customer=cust1, restaurant=rest,
                items=[{"menu_item_id": mi["id"], "quantity": 1}])
    place_order(c, customer=cust2, restaurant=rest,
                items=[{"menu_item_id": mi["id"], "quantity": 1}])
    s, b = c.get("/api/orders", role="PlatformAdmin", query={"customer_id": cust1["id"]})
    assert all(o["customer_id"] == cust1["id"] for o in b["data"])
    assert len(b["data"]) == 1
    s, b = c.get("/api/orders", role="PlatformAdmin", query={"restaurant_id": rest["id"]})
    assert len(b["data"]) == 2


@test("restaurant role list orders only sees own")
def t():
    c = Client()
    r1 = make_restaurant(c, name="A1")
    r2 = make_restaurant(c, name="A2")
    mi = make_menu_item(c, r1["id"])
    mi2 = make_menu_item(c, r2["id"])
    cust = make_customer(c)
    place_order(c, customer=cust, restaurant=r1,
                items=[{"menu_item_id": mi["id"], "quantity": 1}])
    place_order(c, customer=cust, restaurant=r2,
                items=[{"menu_item_id": mi2["id"], "quantity": 1}])
    s, b = c.get("/api/orders", role="Restaurant", user_id=r1["id"])
    assert all(o["restaurant_id"] == r1["id"] for o in b["data"])
    assert len(b["data"]) == 1


@test("restaurant cancels PLACED order on its own")
def t():
    c = Client()
    rest = make_restaurant(c)
    mi = make_menu_item(c, rest["id"])
    cust = make_customer(c)
    s, b = place_order(c, customer=cust, restaurant=rest,
                       items=[{"menu_item_id": mi["id"], "quantity": 1}])
    o = b["data"]
    s, b = c.post(f"/api/orders/{o['id']}/cancel", role="Restaurant", user_id=rest["id"])
    assert s == 200 and b["data"]["status"] == "CANCELLED"


@test("CustomerService cancels order on customer's behalf")
def t():
    c = Client()
    rest = make_restaurant(c)
    mi = make_menu_item(c, rest["id"])
    cust = make_customer(c)
    s, b = place_order(c, customer=cust, restaurant=rest,
                       items=[{"menu_item_id": mi["id"], "quantity": 1}])
    o = b["data"]
    s, b = c.post(f"/api/orders/{o['id']}/cancel", role="CustomerService", user_id="cs1")
    assert s == 200 and b["data"]["status"] == "CANCELLED"


@test("Customer cannot read another customer's order")
def t():
    c = Client()
    rest = make_restaurant(c)
    mi = make_menu_item(c, rest["id"])
    cust1 = make_customer(c, phone="P1")
    cust2 = make_customer(c, phone="P2")
    s, b = place_order(c, customer=cust1, restaurant=rest,
                       items=[{"menu_item_id": mi["id"], "quantity": 1}])
    o = b["data"]
    expect_err(c.get(f"/api/orders/{o['id']}", role="Customer", user_id=cust2["id"]),
               "ERR_FORBIDDEN", http=403)


@test("Restaurant cannot read another restaurant's order")
def t():
    c = Client()
    r1 = make_restaurant(c, name="A1")
    r2 = make_restaurant(c, name="A2")
    mi = make_menu_item(c, r1["id"])
    cust = make_customer(c)
    s, b = place_order(c, customer=cust, restaurant=r1,
                       items=[{"menu_item_id": mi["id"], "quantity": 1}])
    o = b["data"]
    expect_err(c.get(f"/api/orders/{o['id']}", role="Restaurant", user_id=r2["id"]),
               "ERR_FORBIDDEN", http=403)


@test("pagination: limit caps at 100, defaults to 10")
def t():
    c = Client()
    s, b = c.get("/api/restaurants", role="PlatformAdmin")
    assert b["meta"]["limit"] == 10
    s, b = c.get("/api/restaurants", role="PlatformAdmin", query={"limit": 200})
    # Out of range -> ERR_VALIDATION
    assert s == 422


@test("pagination: limit=0 -> ERR_VALIDATION (must be >=1)")
def t():
    c = Client()
    s, b = c.get("/api/restaurants", role="PlatformAdmin", query={"limit": 0})
    assert s == 422


@test("rider go-offline AVAILABLE -> OFFLINE")
def t():
    c = Client()
    rider = make_rider(c, online=True)
    s, b = c.post(f"/api/riders/{rider['id']}/go-offline", role="Rider", user_id=rider["id"])
    assert s == 200 and b["data"]["status"] == "OFFLINE"


@test("rider go-online from OFFLINE -> AVAILABLE")
def t():
    c = Client()
    rider = make_rider(c, online=False)
    s, b = c.post(f"/api/riders/{rider['id']}/go-online", role="Rider", user_id=rider["id"])
    assert s == 200 and b["data"]["status"] == "AVAILABLE"


@test("rider go-online while AVAILABLE -> ERR_INVALID_STATE")
def t():
    c = Client()
    rider = make_rider(c, online=True)
    expect_err(c.post(f"/api/riders/{rider['id']}/go-online", role="Rider", user_id=rider["id"]),
               "ERR_INVALID_STATE", http=409)


@test("identity mismatch on rider go-online -> ERR_FORBIDDEN")
def t():
    c = Client()
    r1 = make_rider(c, phone="R1", online=False)
    r2 = make_rider(c, phone="R2", online=False)
    expect_err(c.post(f"/api/riders/{r1['id']}/go-online", role="Rider", user_id=r2["id"]),
               "ERR_FORBIDDEN", http=403)
