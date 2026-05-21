"""Menu items (§3.1 end)."""
from __future__ import annotations

from ._factories import make_menu_item, make_restaurant
from ._harness import Client, expect_err, expect_ok, test


@test("Restaurant can create menu item with default is_listed=true")
def t():
    c = Client()
    r = make_restaurant(c)
    m = make_menu_item(c, r["id"], name="Burger", price_cents=999)
    assert m["is_listed"] is True
    assert m["price_cents"] == 999


@test("price_cents range [1, 1_000_000]")
def t():
    c = Client()
    r = make_restaurant(c)
    s, b = c.post(f"/api/restaurants/{r['id']}/menu-items", role="Restaurant", user_id=r["id"],
                  body={"name": "x", "price_cents": 0})
    assert s == 422
    s, b = c.post(f"/api/restaurants/{r['id']}/menu-items", role="Restaurant", user_id=r["id"],
                  body={"name": "x", "price_cents": 1_000_001})
    assert s == 422


@test("foreign restaurant cannot create menu item on another's restaurant")
def t():
    c = Client()
    r1 = make_restaurant(c, name="R1")
    r2 = make_restaurant(c, name="R2")
    s, b = c.post(f"/api/restaurants/{r1['id']}/menu-items", role="Restaurant", user_id=r2["id"],
                  body={"name": "X", "price_cents": 100})
    assert s == 403


@test("PATCH menu-item updates price and listing")
def t():
    c = Client()
    r = make_restaurant(c)
    m = make_menu_item(c, r["id"], price_cents=500)
    s, b = c.patch(f"/api/menu-items/{m['id']}", role="Restaurant", user_id=r["id"],
                   body={"price_cents": 700, "is_listed": False})
    assert s == 200 and b["data"]["price_cents"] == 700 and b["data"]["is_listed"] is False


@test("list menu items filterable by is_listed")
def t():
    c = Client()
    r = make_restaurant(c)
    m1 = make_menu_item(c, r["id"], name="A", is_listed=True)
    m2 = make_menu_item(c, r["id"], name="B", is_listed=False)
    s, b = c.get(f"/api/restaurants/{r['id']}/menu-items", role="Customer",
                 query={"is_listed": "true"})
    assert s == 200 and len(b["data"]) == 1 and b["data"][0]["id"] == m1["id"]
