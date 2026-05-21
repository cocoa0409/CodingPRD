"""Rider lifecycle, metrics, suspension (§3.3)."""
from __future__ import annotations

from ._factories import make_rider
from ._harness import Client, expect_err, expect_ok, test


@test("new rider starts OFFLINE, metrics initialized, bonus_tier BRONZE")
def t():
    c = Client()
    r = make_rider(c, online=False)
    assert r["status"] == "OFFLINE"
    assert r["on_time_rate"] == 1.0
    assert r["acceptance_rate"] == 1.0
    assert r["rating"] == 5.0
    assert r["wallet_balance_cents"] == 0
    # bonus_tier from initial metrics: score = 0.6*1 + 0.3*1 + 0.1*1 = 1.0 -> PLATINUM
    # PRD: BRONZE is default for a new rider. Reading carefully: PRD says "BRONZE as the default for a new rider"
    # but if initialized rates are all 1.0 and tier formula yields 1.0, mapping is PLATINUM.
    # We respect the explicit "default for a new rider" as BRONZE on creation; tier is recomputed later.
    assert r["bonus_tier"] == "BRONZE"


@test("go-online OFFLINE -> AVAILABLE")
def t():
    c = Client()
    r = make_rider(c, online=False)
    s, b = c.post(f"/api/riders/{r['id']}/go-online", role="Rider", user_id=r["id"])
    assert s == 200 and b["data"]["status"] == "AVAILABLE"


@test("go-online when already AVAILABLE -> ERR_INVALID_STATE")
def t():
    c = Client()
    r = make_rider(c)
    s, b = c.post(f"/api/riders/{r['id']}/go-online", role="Rider", user_id=r["id"])
    assert s == 409 and b["data"]["error_id"] == "ERR_INVALID_STATE"


@test("go-offline AVAILABLE -> OFFLINE")
def t():
    c = Client()
    r = make_rider(c)
    s, b = c.post(f"/api/riders/{r['id']}/go-offline", role="Rider", user_id=r["id"])
    assert s == 200 and b["data"]["status"] == "OFFLINE"


@test("rider identity mismatch on go-online -> ERR_FORBIDDEN")
def t():
    c = Client()
    r = make_rider(c, online=False)
    s, b = c.post(f"/api/riders/{r['id']}/go-online", role="Rider", user_id="someone-else")
    assert s == 403


@test("suspend rider requires breached threshold")
def t():
    c = Client()
    r = make_rider(c)
    s, b = c.post(f"/api/riders/{r['id']}/suspend", role="PlatformAdmin")
    assert s == 422 and b["data"]["error_id"] == "ERR_SUSPEND_CRITERIA_NOT_MET"


@test("suspend rider succeeds when acceptance_rate < 0.50")
def t():
    c = Client()
    r = make_rider(c)
    from app.store import store
    rider = store.riders[r["id"]]
    rider["acceptance_rate"] = 0.49
    s, b = c.post(f"/api/riders/{r['id']}/suspend", role="PlatformAdmin")
    assert s == 200 and b["data"]["status"] == "SUSPENDED"


@test("suspend SUSPENDED rider -> ERR_INVALID_STATE")
def t():
    c = Client()
    r = make_rider(c)
    from app.store import store
    rider = store.riders[r["id"]]
    rider["acceptance_rate"] = 0.49
    c.post(f"/api/riders/{r['id']}/suspend", role="PlatformAdmin")
    s, b = c.post(f"/api/riders/{r['id']}/suspend", role="PlatformAdmin")
    assert s == 409
