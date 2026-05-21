"""Auth headers, envelope, error format (§2.1, §2.2)."""
from __future__ import annotations

from ._harness import Client, expect_err, expect_ok, test


@test("auth headers missing -> ERR_AUTH_REQUIRED")
def t():
    c = Client()
    status, body = c.c.get("/api/restaurants").status_code, c.c.get("/api/restaurants").get_json()
    assert status == 401, status
    assert body["data"]["error_id"] == "ERR_AUTH_REQUIRED"


@test("unknown role -> ERR_AUTH_REQUIRED")
def t():
    c = Client()
    resp = c.c.get("/api/restaurants", headers={"X-User-ID": "x", "X-User-Role": "Wizard"})
    assert resp.status_code == 401
    assert resp.get_json()["data"]["error_id"] == "ERR_AUTH_REQUIRED"


@test("envelope has api_request_id, timestamp, response_type, data on success")
def t():
    c = Client()
    status, body = c.get("/api/restaurants", role="PlatformAdmin")
    assert status == 200
    assert "api_request_id" in body["meta"]
    assert body["meta"]["api_request_id"].startswith("req_")
    assert "api_request_timestamp" in body["meta"]
    assert body["response_type"] == "array"
    assert body["data"] == []
    # Pagination fields
    assert body["meta"]["limit"] == 10
    assert body["meta"]["offset"] == 0
    assert body["meta"]["total_count"] == 0
    assert body["meta"]["has_more"] is False


@test("error envelope shape")
def t():
    c = Client()
    status, body = c.get("/api/restaurants/nonexistent", role="PlatformAdmin")
    assert status == 404
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == "ERR_NOT_FOUND"
    assert "message" in body["data"]


@test("role-to-endpoint forbidden -> ERR_FORBIDDEN")
def t():
    c = Client()
    # Customer cannot register a restaurant
    s, b = c.post("/api/restaurants", role="Customer",
                  body={"name": "x", "address": "a", "lat": 0, "lng": 0})
    assert s == 403, s
    assert b["data"]["error_id"] == "ERR_FORBIDDEN"
