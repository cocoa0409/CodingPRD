"""Tests for menu item CRUD (§3.1 last paragraph)."""

from tests.harness import (
    test, fresh_client, jget, jpost, jpatch, body_of,
    assert_eq, assert_err, admin_headers, rest_headers,
)


def _setup_active_restaurant(c):
    r = body_of(jpost(c, "/api/restaurants",
                     body={"name": "R", "address": "A", "lat": 0, "lng": 0},
                     headers=admin_headers()))["data"]
    jpost(c, f"/api/restaurants/{r['id']}/approve", headers=admin_headers())
    return r["id"]


@test("menu: restaurant creates item, default is_listed=true")
def t_create_menu():
    c = fresh_client()
    rid = _setup_active_restaurant(c)
    resp = jpost(c, f"/api/restaurants/{rid}/menu-items",
                 body={"name": "Burger", "price_cents": 1500},
                 headers=rest_headers(rid))
    assert_eq(resp.status_code, 201, "201")
    d = body_of(resp)["data"]
    assert_eq(d["is_listed"], True, "default is_listed true")
    assert_eq(d["restaurant_id"], rid, "fk set")
    assert_eq(d["version"], 1, "v=1")


@test("menu: another restaurant cannot create on someone else's menu -> 403")
def t_foreign_restaurant():
    c = fresh_client()
    rid = _setup_active_restaurant(c)
    resp = jpost(c, f"/api/restaurants/{rid}/menu-items",
                 body={"name": "X", "price_cents": 1},
                 headers=rest_headers("not-the-owner"))
    assert_err(resp, 403, "ERR_FORBIDDEN")


@test("menu: price_cents range enforced")
def t_price_range():
    c = fresh_client()
    rid = _setup_active_restaurant(c)
    bad_low = jpost(c, f"/api/restaurants/{rid}/menu-items",
                    body={"name": "X", "price_cents": 0},
                    headers=rest_headers(rid))
    assert_err(bad_low, 422, "ERR_VALIDATION")
    bad_hi = jpost(c, f"/api/restaurants/{rid}/menu-items",
                   body={"name": "X", "price_cents": 1_000_001},
                   headers=rest_headers(rid))
    assert_err(bad_hi, 422, "ERR_VALIDATION")


@test("menu: PATCH price by Restaurant updates and bumps version")
def t_patch_menu():
    c = fresh_client()
    rid = _setup_active_restaurant(c)
    mid = body_of(jpost(c, f"/api/restaurants/{rid}/menu-items",
                       body={"name": "X", "price_cents": 100},
                       headers=rest_headers(rid)))["data"]["id"]
    resp = jpatch(c, f"/api/menu-items/{mid}",
                  body={"price_cents": 200},
                  headers=rest_headers(rid))
    d = body_of(resp)["data"]
    assert_eq(d["price_cents"], 200, "new price")
    assert_eq(d["version"], 2, "bumped")


@test("menu: list filters by is_listed")
def t_list_filter():
    c = fresh_client()
    rid = _setup_active_restaurant(c)
    a = body_of(jpost(c, f"/api/restaurants/{rid}/menu-items",
                     body={"name": "A", "price_cents": 100},
                     headers=rest_headers(rid)))["data"]["id"]
    b = body_of(jpost(c, f"/api/restaurants/{rid}/menu-items",
                     body={"name": "B", "price_cents": 200, "is_listed": False},
                     headers=rest_headers(rid)))["data"]["id"]
    resp = jget(c, f"/api/restaurants/{rid}/menu-items?is_listed=true",
                headers=admin_headers())
    body = body_of(resp)
    ids = {m["id"] for m in body["data"]}
    assert_eq(ids, {a}, "only listed items")


@test("menu: not found restaurant -> ERR_NOT_FOUND before body checks")
def t_path_first():
    c = fresh_client()
    resp = jpost(c, "/api/restaurants/no-such/menu-items",
                 body={"name": "X", "price_cents": -1},
                 headers=admin_headers())
    assert_err(resp, 404, "ERR_NOT_FOUND")
