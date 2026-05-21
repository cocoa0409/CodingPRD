"""Tests for §3.1 — Restaurant and Menu Lifecycle."""
from __future__ import annotations

from .harness import test


@test("restaurant: register starts in PENDING_APPROVAL with version=1")
def t1(ctx):
    r = ctx.register_restaurant(name="R-PA")
    assert r["status"] == "PENDING_APPROVAL"
    assert r["version"] == 1
    assert r["pending_settlement_cents"] == 0
    assert r["commission_rate_override"] is None


@test("restaurant: name uniqueness across active restaurants")
def t2(ctx):
    ctx.register_restaurant(name="Same")
    s, b = ctx.post("/api/restaurants", role="PlatformAdmin", user_id="a",
                    json_body={"name": "Same", "address": "y", "lat": 1, "lng": 2})
    assert s == 422 and b["data"]["error_id"] == "ERR_VALIDATION"


@test("restaurant: commission_rate_override out of range rejected")
def t3(ctx):
    s, b = ctx.post("/api/restaurants", role="PlatformAdmin", user_id="a",
                    json_body={"name": "X", "address": "y", "lat": 1, "lng": 2,
                               "commission_rate_override": 0.04})
    assert s == 422 and b["data"]["error_id"] == "ERR_VALIDATION"
    s, b = ctx.post("/api/restaurants", role="PlatformAdmin", user_id="a",
                    json_body={"name": "X", "address": "y", "lat": 1, "lng": 2,
                               "commission_rate_override": 0.36})
    assert s == 422 and b["data"]["error_id"] == "ERR_VALIDATION"


@test("restaurant: approve PENDING_APPROVAL → ACTIVE")
def t4(ctx):
    r = ctx.register_restaurant()
    a = ctx.approve_restaurant(r["id"])
    assert a["status"] == "ACTIVE"
    assert a["version"] == 2


@test("restaurant: approve when not pending → ERR_INVALID_STATE")
def t5(ctx):
    r = ctx.register_restaurant()
    ctx.approve_restaurant(r["id"])
    s, b = ctx.post(f"/api/restaurants/{r['id']}/approve", role="PlatformAdmin", user_id="a")
    assert s == 409 and b["data"]["error_id"] == "ERR_INVALID_STATE"


@test("restaurant: suspend cancels PLACED orders for the restaurant")
def t6(ctx):
    rest = ctx.make_active_restaurant()
    mi = ctx.add_menu_item(rest["id"], price_cents=500)
    cust = ctx.register_customer()
    s, b = ctx.place_order(customer=cust, restaurant=rest,
                            items=[{"menu_item_id": mi["id"], "quantity": 1}])
    assert s == 201, b
    order = b["data"]
    assert order["status"] == "PLACED"
    s, b = ctx.post(f"/api/restaurants/{rest['id']}/suspend", role="PlatformAdmin", user_id="a")
    assert s == 200
    assert b["data"]["status"] == "SUSPENDED"
    # Order cancelled and payment voided
    s, b = ctx.get(f"/api/orders/{order['id']}", role="PlatformAdmin", user_id="a")
    assert b["data"]["status"] == "CANCELLED"
    assert b["data"]["payment_status"] == "VOIDED"


@test("restaurant: reinstate SUSPENDED → ACTIVE")
def t7(ctx):
    rest = ctx.make_active_restaurant()
    ctx.post(f"/api/restaurants/{rest['id']}/suspend", role="PlatformAdmin", user_id="a")
    s, b = ctx.post(f"/api/restaurants/{rest['id']}/reinstate", role="PlatformAdmin", user_id="a")
    assert s == 200 and b["data"]["status"] == "ACTIVE"


@test("restaurant: settle zeroes pending_settlement_cents")
def t8(ctx):
    rest = ctx.make_active_restaurant()
    # Force a non-zero settlement balance via internal access (no public endpoint to set this)
    with ctx.app.config["STORE"].lock:
        ctx.app.config["STORE"].restaurants[rest["id"]]["pending_settlement_cents"] = 2500
    s, b = ctx.post(f"/api/restaurants/{rest['id']}/settle", role="PlatformAdmin", user_id="a")
    assert s == 200
    assert b["data"]["pending_settlement_cents"] == 0


@test("restaurant: PATCH name rejected (immutable)")
def t9(ctx):
    r = ctx.register_restaurant(name="OrigName")
    s, b = ctx.patch(f"/api/restaurants/{r['id']}", role="PlatformAdmin", user_id="a",
                      json_body={"name": "New"})
    assert s == 422 and b["data"]["error_id"] == "ERR_VALIDATION"


@test("restaurant: PATCH OCC mismatch → ERR_VERSION_CONFLICT")
def t10(ctx):
    r = ctx.register_restaurant()
    s, b = ctx.patch(f"/api/restaurants/{r['id']}", role="PlatformAdmin", user_id="a",
                      json_body={"address": "new", "version": 999})
    assert s == 409 and b["data"]["error_id"] == "ERR_VERSION_CONFLICT"


@test("restaurant: PATCH without version succeeds and bumps version")
def t11(ctx):
    r = ctx.register_restaurant()
    s, b = ctx.patch(f"/api/restaurants/{r['id']}", role="PlatformAdmin", user_id="a",
                      json_body={"address": "new"})
    assert s == 200
    assert b["data"]["address"] == "new"
    assert b["data"]["version"] == 2


@test("restaurant: Restaurant role may only PATCH its own record")
def t12(ctx):
    r1 = ctx.register_restaurant(name="A")
    r2 = ctx.register_restaurant(name="B")
    s, b = ctx.patch(f"/api/restaurants/{r2['id']}", role="Restaurant", user_id=r1["id"],
                      json_body={"address": "new"})
    assert s == 403 and b["data"]["error_id"] == "ERR_FORBIDDEN"


@test("menu-item: create with price out of range rejected")
def t13(ctx):
    r = ctx.make_active_restaurant()
    s, b = ctx.post(f"/api/restaurants/{r['id']}/menu-items", role="Restaurant", user_id=r["id"],
                    json_body={"name": "X", "price_cents": 0})
    assert s == 422 and b["data"]["error_id"] == "ERR_VALIDATION"
    s, b = ctx.post(f"/api/restaurants/{r['id']}/menu-items", role="Restaurant", user_id=r["id"],
                    json_body={"name": "X", "price_cents": 1_000_001})
    assert s == 422 and b["data"]["error_id"] == "ERR_VALIDATION"


@test("menu-item: PATCH unlists item without destroying id")
def t14(ctx):
    r = ctx.make_active_restaurant()
    mi = ctx.add_menu_item(r["id"])
    s, b = ctx.patch(f"/api/menu-items/{mi['id']}", role="Restaurant", user_id=r["id"],
                      json_body={"is_listed": False})
    assert s == 200
    assert b["data"]["is_listed"] is False
    assert b["data"]["id"] == mi["id"]


@test("menu-item: list with is_listed filter")
def t15(ctx):
    r = ctx.make_active_restaurant()
    a = ctx.add_menu_item(r["id"], name="A")
    b = ctx.add_menu_item(r["id"], name="B", is_listed=False)
    s, body = ctx.get(f"/api/restaurants/{r['id']}/menu-items", role="PlatformAdmin", user_id="a",
                       query={"is_listed": "true"})
    assert s == 200
    ids = {x["id"] for x in body["data"]}
    assert a["id"] in ids and b["id"] not in ids
