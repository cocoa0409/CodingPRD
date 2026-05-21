"""Tests for §2.1 (RBAC), §2.2 (envelope), §2.3 (pagination)."""
from __future__ import annotations

import re

from .harness import test


_REQ_ID_RE = re.compile(r"^req_[A-Z0-9]{20}$")
_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


@test("envelope: api_request_id and api_request_timestamp shape on success")
def t1(ctx):
    s, body = ctx.get("/api/restaurants", role="PlatformAdmin", user_id="a")
    assert s == 200
    assert _REQ_ID_RE.match(body["meta"]["api_request_id"]), body["meta"]
    assert _TS_RE.match(body["meta"]["api_request_timestamp"]), body["meta"]
    assert body["response_type"] == "array"


@test("envelope: error response format")
def t2(ctx):
    s, body = ctx.get("/api/restaurants/nonexistent", role="PlatformAdmin", user_id="a")
    assert s == 404
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == "ERR_NOT_FOUND"
    assert _REQ_ID_RE.match(body["meta"]["api_request_id"])


@test("auth: missing headers → ERR_AUTH_REQUIRED 401")
def t3(ctx):
    s, body = ctx.get("/api/restaurants")
    assert s == 401
    assert body["data"]["error_id"] == "ERR_AUTH_REQUIRED"


@test("auth: bad role → ERR_AUTH_REQUIRED")
def t4(ctx):
    s, body = ctx.get("/api/restaurants", role="Hacker", user_id="x")
    assert s == 401
    assert body["data"]["error_id"] == "ERR_AUTH_REQUIRED"


@test("auth: role not permitted for endpoint → ERR_FORBIDDEN")
def t5(ctx):
    # Only PlatformAdmin can register
    s, body = ctx.post("/api/restaurants", role="Customer", user_id="c",
                       json_body={"name": "X", "address": "y", "lat": 1, "lng": 2})
    assert s == 403
    assert body["data"]["error_id"] == "ERR_FORBIDDEN"


@test("auth: identity mismatch on read customer → ERR_FORBIDDEN")
def t6(ctx):
    c1 = ctx.register_customer(phone="p1")
    c2 = ctx.register_customer(phone="p2")
    s, body = ctx.get(f"/api/customers/{c2['id']}", role="Customer", user_id=c1["id"])
    assert s == 403, body
    assert body["data"]["error_id"] == "ERR_FORBIDDEN"


@test("pagination: defaults — limit=10, offset=0")
def t7(ctx):
    for i in range(3):
        ctx.register_restaurant(name=f"R{i}")
    s, body = ctx.get("/api/restaurants", role="PlatformAdmin", user_id="a")
    assert s == 200
    assert body["meta"]["limit"] == 10
    assert body["meta"]["offset"] == 0
    assert body["meta"]["total_count"] == 3
    assert body["meta"]["has_more"] is False
    assert len(body["data"]) == 3


@test("pagination: explicit limit=2 page through")
def t8(ctx):
    for i in range(5):
        ctx.register_restaurant(name=f"R{i}")
    s, b = ctx.get("/api/restaurants", role="PlatformAdmin", user_id="a", query={"limit": 2, "offset": 0})
    assert s == 200
    assert b["meta"]["limit"] == 2
    assert b["meta"]["total_count"] == 5
    assert b["meta"]["has_more"] is True
    assert len(b["data"]) == 2
    s, b = ctx.get("/api/restaurants", role="PlatformAdmin", user_id="a", query={"limit": 2, "offset": 4})
    assert b["meta"]["has_more"] is False
    assert len(b["data"]) == 1


@test("pagination: invalid limit/offset → ERR_VALIDATION")
def t9(ctx):
    s, b = ctx.get("/api/restaurants", role="PlatformAdmin", user_id="a", query={"limit": 0})
    assert s == 422 and b["data"]["error_id"] == "ERR_VALIDATION"
    s, b = ctx.get("/api/restaurants", role="PlatformAdmin", user_id="a", query={"limit": 101})
    assert s == 422 and b["data"]["error_id"] == "ERR_VALIDATION"
    s, b = ctx.get("/api/restaurants", role="PlatformAdmin", user_id="a", query={"offset": -1})
    assert s == 422 and b["data"]["error_id"] == "ERR_VALIDATION"


@test("envelope: created resources return 201")
def t10(ctx):
    s, _ = ctx.post("/api/restaurants", role="PlatformAdmin", user_id="a",
                    json_body={"name": "X", "address": "y", "lat": 1, "lng": 2})
    assert s == 201
