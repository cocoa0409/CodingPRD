"""Tests for §3.1 restaurant and menu lifecycle."""

from tests.harness import (
    test, fresh_client, jget, jpost, jpatch, body_of,
    assert_eq, assert_err, admin_headers, rest_headers,
)


def _new_restaurant(c, name="Foo", admin="adminA"):
    return jpost(c, "/api/restaurants",
                 body={"name": name, "address": "A", "lat": 40.0, "lng": -73.0},
                 headers=admin_headers(admin))


@test("restaurant: register -> PENDING_APPROVAL, version=1")
def t_register():
    c = fresh_client()
    resp = _new_restaurant(c)
    body = body_of(resp)
    assert_eq(resp.status_code, 201, "201")
    d = body["data"]
    assert_eq(d["status"], "PENDING_APPROVAL", "status")
    assert_eq(d["pending_settlement_cents"], 0, "pending settle 0")
    assert_eq(d["version"], 1, "version 1")
    assert_eq(d["commission_rate_override"], None, "no override")


@test("restaurant: approve PENDING_APPROVAL -> ACTIVE")
def t_approve():
    c = fresh_client()
    rid = body_of(_new_restaurant(c))["data"]["id"]
    resp = jpost(c, f"/api/restaurants/{rid}/approve", headers=admin_headers())
    body = body_of(resp)
    assert_eq(body["data"]["status"], "ACTIVE", "active")
    assert_eq(body["data"]["version"], 2, "version bumped")


@test("restaurant: approve twice -> ERR_INVALID_STATE on second")
def t_approve_twice():
    c = fresh_client()
    rid = body_of(_new_restaurant(c))["data"]["id"]
    jpost(c, f"/api/restaurants/{rid}/approve", headers=admin_headers())
    resp = jpost(c, f"/api/restaurants/{rid}/approve", headers=admin_headers())
    assert_err(resp, 409, "ERR_INVALID_STATE")


@test("restaurant: suspend ACTIVE -> SUSPENDED")
def t_suspend():
    c = fresh_client()
    rid = body_of(_new_restaurant(c))["data"]["id"]
    jpost(c, f"/api/restaurants/{rid}/approve", headers=admin_headers())
    resp = jpost(c, f"/api/restaurants/{rid}/suspend", headers=admin_headers())
    assert_eq(body_of(resp)["data"]["status"], "SUSPENDED", "suspended")


@test("restaurant: reinstate SUSPENDED -> ACTIVE")
def t_reinstate():
    c = fresh_client()
    rid = body_of(_new_restaurant(c))["data"]["id"]
    jpost(c, f"/api/restaurants/{rid}/approve", headers=admin_headers())
    jpost(c, f"/api/restaurants/{rid}/suspend", headers=admin_headers())
    resp = jpost(c, f"/api/restaurants/{rid}/reinstate", headers=admin_headers())
    assert_eq(body_of(resp)["data"]["status"], "ACTIVE", "active again")


@test("restaurant: name immutable on PATCH")
def t_name_immutable():
    c = fresh_client()
    rid = body_of(_new_restaurant(c))["data"]["id"]
    resp = jpatch(c, f"/api/restaurants/{rid}", body={"name": "New"}, headers=admin_headers())
    assert_err(resp, 422, "ERR_VALIDATION")


@test("restaurant: PATCH OCC mismatch -> ERR_VERSION_CONFLICT")
def t_patch_occ():
    c = fresh_client()
    rid = body_of(_new_restaurant(c))["data"]["id"]
    resp = jpatch(c, f"/api/restaurants/{rid}",
                  body={"address": "B", "version": 99}, headers=admin_headers())
    assert_err(resp, 409, "ERR_VERSION_CONFLICT")


@test("restaurant: PATCH commission_rate_override accepted in range")
def t_patch_override():
    c = fresh_client()
    rid = body_of(_new_restaurant(c))["data"]["id"]
    resp = jpatch(c, f"/api/restaurants/{rid}",
                  body={"commission_rate_override": 0.20, "version": 1},
                  headers=admin_headers())
    assert_eq(body_of(resp)["data"]["commission_rate_override"], 0.20, "override set")


@test("restaurant: PATCH commission_rate_override out of range -> ERR_VALIDATION")
def t_patch_override_oob():
    c = fresh_client()
    rid = body_of(_new_restaurant(c))["data"]["id"]
    resp = jpatch(c, f"/api/restaurants/{rid}",
                  body={"commission_rate_override": 0.5},
                  headers=admin_headers())
    assert_err(resp, 422, "ERR_VALIDATION")


@test("restaurant: list with status filter")
def t_list_filter():
    c = fresh_client()
    r1 = body_of(_new_restaurant(c, name="A"))["data"]["id"]
    r2 = body_of(_new_restaurant(c, name="B"))["data"]["id"]
    jpost(c, f"/api/restaurants/{r1}/approve", headers=admin_headers())
    resp = jget(c, "/api/restaurants?status=ACTIVE", headers=admin_headers())
    body = body_of(resp)
    assert_eq(body["meta"]["total_count"], 1, "one active")
    assert_eq(body["data"][0]["id"], r1, "filtered restaurant id")


@test("restaurant: NOT_FOUND on missing path id")
def t_not_found():
    c = fresh_client()
    resp = jget(c, "/api/restaurants/nope", headers=admin_headers())
    assert_err(resp, 404, "ERR_NOT_FOUND")


@test("restaurant: name uniqueness among active blocks register")
def t_name_unique_active():
    c = fresh_client()
    rid = body_of(_new_restaurant(c, name="Twin"))["data"]["id"]
    jpost(c, f"/api/restaurants/{rid}/approve", headers=admin_headers())
    resp = _new_restaurant(c, name="Twin")
    assert_err(resp, 409, "ERR_INVALID_STATE")


@test("restaurant: settle zeroes pending_settlement_cents")
def t_settle():
    c = fresh_client()
    rid = body_of(_new_restaurant(c))["data"]["id"]
    # Manually nudge the value to confirm zeroing happens.
    import state
    state.STORE.restaurants[rid]["pending_settlement_cents"] = 12345
    resp = jpost(c, f"/api/restaurants/{rid}/settle", headers=admin_headers())
    assert_eq(body_of(resp)["data"]["pending_settlement_cents"], 0, "zeroed")
