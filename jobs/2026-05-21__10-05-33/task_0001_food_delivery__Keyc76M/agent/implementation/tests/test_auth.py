"""Tests for §2.1 (auth headers, RBAC) and §2.6 (priority of auth check)."""

from tests.harness import (
    test, fresh_client, jget, jpost, body_of,
    assert_eq, assert_err, admin_headers, cust_headers,
)


@test("auth: missing headers yields ERR_AUTH_REQUIRED")
def t_missing_headers():
    c = fresh_client()
    resp = c.get("/api/restaurants")
    assert_err(resp, 401, "ERR_AUTH_REQUIRED")


@test("auth: unknown role yields ERR_AUTH_REQUIRED")
def t_unknown_role():
    c = fresh_client()
    resp = c.get("/api/restaurants", headers={"X-User-ID": "x", "X-User-Role": "Wizard"})
    assert_err(resp, 401, "ERR_AUTH_REQUIRED")


@test("auth: header missing only X-User-ID yields ERR_AUTH_REQUIRED")
def t_missing_user_id():
    c = fresh_client()
    resp = c.get("/api/restaurants", headers={"X-User-Role": "PlatformAdmin"})
    assert_err(resp, 401, "ERR_AUTH_REQUIRED")


@test("rbac: Rider can not create a restaurant -> ERR_FORBIDDEN")
def t_rider_cannot_create_restaurant():
    c = fresh_client()
    resp = jpost(c, "/api/restaurants",
                 body={"name": "X", "address": "A", "lat": 1, "lng": 2},
                 headers={"X-User-ID": "r1", "X-User-Role": "Rider"})
    assert_err(resp, 403, "ERR_FORBIDDEN")


@test("envelope: success has api_request_id with req_ prefix")
def t_envelope_success():
    c = fresh_client()
    resp = jpost(c, "/api/restaurants",
                 body={"name": "R", "address": "A", "lat": 1, "lng": 2},
                 headers=admin_headers())
    assert_eq(resp.status_code, 201, "201 Created")
    body = body_of(resp)
    assert "req_" in body["meta"]["api_request_id"], "api_request_id starts with req_"
    assert_eq(body["response_type"], "object", "object response")


@test("envelope: error has only id and timestamp meta")
def t_envelope_error_meta():
    c = fresh_client()
    resp = c.get("/api/restaurants/does-not-exist", headers=admin_headers())
    body = body_of(resp)
    assert_eq(set(body["meta"].keys()), {"api_request_id", "api_request_timestamp"}, "meta keys")
    assert_eq(body["response_type"], "error", "error type")
