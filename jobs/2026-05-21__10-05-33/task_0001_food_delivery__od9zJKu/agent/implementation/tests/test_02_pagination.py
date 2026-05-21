"""Pagination behavior (§2.3)."""
from __future__ import annotations

from ._harness import Client, expect_err, expect_ok, test


@test("pagination invalid limit/offset -> ERR_VALIDATION")
def t():
    c = Client()
    s, b = c.get("/api/restaurants", role="PlatformAdmin", query={"limit": 0})
    assert s == 422 and b["data"]["error_id"] == "ERR_VALIDATION"
    s, b = c.get("/api/restaurants", role="PlatformAdmin", query={"limit": 101})
    assert s == 422 and b["data"]["error_id"] == "ERR_VALIDATION"
    s, b = c.get("/api/restaurants", role="PlatformAdmin", query={"offset": -1})
    assert s == 422 and b["data"]["error_id"] == "ERR_VALIDATION"


@test("pagination has_more / total_count semantics")
def t():
    c = Client()
    # Create 3 restaurants
    from ._factories import make_restaurant
    rs = [make_restaurant(c, name=f"Rest{i}", approve=False) for i in range(3)]
    # limit=2 offset=0 -> 2 items, has_more True, total 3
    data = expect_ok(c.get("/api/restaurants", role="PlatformAdmin", query={"limit": 2, "offset": 0}))
    s, b = c.get("/api/restaurants", role="PlatformAdmin", query={"limit": 2, "offset": 0})
    assert b["meta"]["total_count"] == 3
    assert b["meta"]["has_more"] is True
    assert len(b["data"]) == 2
    s, b = c.get("/api/restaurants", role="PlatformAdmin", query={"limit": 2, "offset": 2})
    assert b["meta"]["has_more"] is False
    assert len(b["data"]) == 1


@test("list sorted by created_at ascending")
def t():
    c = Client()
    from ._factories import make_restaurant
    a = make_restaurant(c, name="A", approve=False)
    b = make_restaurant(c, name="B", approve=False)
    cc = make_restaurant(c, name="C", approve=False)
    s, body = c.get("/api/restaurants", role="PlatformAdmin")
    ids = [r["id"] for r in body["data"]]
    assert ids == [a["id"], b["id"], cc["id"]], ids
