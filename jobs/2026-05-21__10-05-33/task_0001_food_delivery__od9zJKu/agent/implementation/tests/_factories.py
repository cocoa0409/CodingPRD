"""Test factories: convenience builders for entities via the API."""
from __future__ import annotations

from ._harness import Client, expect_ok


def make_restaurant(c: Client, *, name="R1", lat=37.0, lng=-122.0, approve=True,
                    rate=None, address="1 Main", admin_uid="adminR"):
    body = {"name": name, "address": address, "lat": lat, "lng": lng}
    if rate is not None:
        body["commission_rate_override"] = rate
    r = expect_ok(c.post("/api/restaurants", role="PlatformAdmin", user_id=admin_uid, body=body), http=201)
    if approve:
        expect_ok(c.post(f"/api/restaurants/{r['id']}/approve", role="PlatformAdmin", user_id=admin_uid))
    return r


def make_menu_item(c: Client, restaurant_id: str, *, name="Item", price_cents=1000, is_listed=True):
    return expect_ok(
        c.post(
            f"/api/restaurants/{restaurant_id}/menu-items",
            role="Restaurant",
            user_id=restaurant_id,
            body={"name": name, "price_cents": price_cents, "is_listed": is_listed},
        ),
        http=201,
    )


def make_customer(c: Client, *, name="C", phone="555-100", lat=37.01, lng=-122.01,
                  address="2 Side St"):
    return expect_ok(
        c.post(
            "/api/customers",
            role="PlatformAdmin",
            user_id="adminC",
            body={"name": name, "phone": phone, "address": address, "lat": lat, "lng": lng},
        ),
        http=201,
    )


def make_rider(c: Client, *, name="Rider", phone="555-200", online=True):
    r = expect_ok(
        c.post(
            "/api/riders",
            role="PlatformAdmin",
            user_id="adminRD",
            body={"name": name, "phone": phone},
        ),
        http=201,
    )
    if online:
        expect_ok(c.post(f"/api/riders/{r['id']}/go-online", role="Rider", user_id=r["id"]))
    return r


def place_order(c: Client, *, customer, restaurant, items):
    body = {
        "customer_id": customer["id"],
        "restaurant_id": restaurant["id"],
        "items": items,
    }
    return c.post("/api/orders", role="Customer", user_id=customer["id"], body=body)


def make_simple_order(c: Client, *, customer, restaurant, menu_items_qty):
    items = [{"menu_item_id": mi["id"], "quantity": q} for mi, q in menu_items_qty]
    status, body = place_order(c, customer=customer, restaurant=restaurant, items=items)
    if status != 201:
        raise AssertionError(f"place_order failed: {status} {body}")
    return body["data"]
