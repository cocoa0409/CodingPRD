"""Tests for §3.2 customers and §3.3 riders (basic lifecycle)."""

from tests.harness import (
    test, fresh_client, jget, jpost, body_of,
    assert_eq, assert_err, admin_headers, cs_headers, cust_headers, rider_headers,
)


@test("customer: register by PlatformAdmin yields credit=0, trust=1")
def t_register_customer():
    c = fresh_client()
    resp = jpost(c, "/api/customers",
                 body={"name": "Alice", "phone": "+1", "address": "A",
                       "lat": 1.0, "lng": 2.0},
                 headers=admin_headers())
    d = body_of(resp)["data"]
    assert_eq(resp.status_code, 201, "201")
    assert_eq(d["credit_balance_cents"], 0, "0 credit")
    assert_eq(d["trust_score"], 1.0, "1.0 trust")


@test("customer: read self by customer is OK")
def t_read_self():
    c = fresh_client()
    cid = body_of(jpost(c, "/api/customers",
                        body={"name": "A", "phone": "+1",
                              "address": "x", "lat": 0, "lng": 0},
                        headers=admin_headers()))["data"]["id"]
    resp = jget(c, f"/api/customers/{cid}", headers=cust_headers(cid))
    assert_eq(resp.status_code, 200, "200")


@test("customer: read other by customer -> ERR_FORBIDDEN")
def t_read_other():
    c = fresh_client()
    cid = body_of(jpost(c, "/api/customers",
                        body={"name": "A", "phone": "+1",
                              "address": "x", "lat": 0, "lng": 0},
                        headers=admin_headers()))["data"]["id"]
    resp = jget(c, f"/api/customers/{cid}", headers=cust_headers("other"))
    assert_err(resp, 403, "ERR_FORBIDDEN")


@test("customer: phone uniqueness")
def t_phone_unique():
    c = fresh_client()
    body = {"name": "A", "phone": "+1", "address": "x", "lat": 0, "lng": 0}
    jpost(c, "/api/customers", body=body, headers=admin_headers())
    resp = jpost(c, "/api/customers", body=body, headers=admin_headers())
    assert_err(resp, 409, "ERR_INVALID_STATE")


@test("rider: register -> OFFLINE, defaults bonus_tier=PLATINUM (1,1,5/5)")
def t_register_rider():
    c = fresh_client()
    resp = jpost(c, "/api/riders",
                 body={"name": "Rob", "phone": "+5"},
                 headers=admin_headers())
    d = body_of(resp)["data"]
    assert_eq(d["status"], "OFFLINE", "offline")
    assert_eq(d["bonus_tier"], "PLATINUM", "initial PLATINUM")
    assert_eq(d["wallet_balance_cents"], 0, "wallet=0")


@test("rider: go-online -> AVAILABLE; rider can't go online for someone else")
def t_go_online_identity():
    c = fresh_client()
    rid = body_of(jpost(c, "/api/riders",
                        body={"name": "R", "phone": "+1"},
                        headers=admin_headers()))["data"]["id"]
    bad = jpost(c, f"/api/riders/{rid}/go-online", headers=rider_headers("not-me"))
    assert_err(bad, 403, "ERR_FORBIDDEN")
    good = jpost(c, f"/api/riders/{rid}/go-online", headers=rider_headers(rid))
    assert_eq(body_of(good)["data"]["status"], "AVAILABLE", "available")


@test("rider: suspend without threshold breach -> ERR_SUSPEND_CRITERIA_NOT_MET")
def t_suspend_no_criteria():
    c = fresh_client()
    rid = body_of(jpost(c, "/api/riders",
                        body={"name": "R", "phone": "+1"},
                        headers=admin_headers()))["data"]["id"]
    jpost(c, f"/api/riders/{rid}/go-online", headers=rider_headers(rid))
    resp = jpost(c, f"/api/riders/{rid}/suspend", headers=admin_headers())
    assert_err(resp, 422, "ERR_SUSPEND_CRITERIA_NOT_MET")


@test("rider: go-offline while OFFLINE -> ERR_INVALID_STATE")
def t_offline_then_offline():
    c = fresh_client()
    rid = body_of(jpost(c, "/api/riders",
                        body={"name": "R", "phone": "+1"},
                        headers=admin_headers()))["data"]["id"]
    resp = jpost(c, f"/api/riders/{rid}/go-offline", headers=rider_headers(rid))
    assert_err(resp, 409, "ERR_INVALID_STATE")
