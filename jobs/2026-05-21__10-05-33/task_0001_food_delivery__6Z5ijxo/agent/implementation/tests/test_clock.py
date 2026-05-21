from . import client


def test_clock_advance_requires_admin():
    r = client.post("/api/_clock/advance", role="Customer", uid="c1", json={"seconds": 1})
    assert r.status_code == 403


def test_clock_advance_returns_now():
    r = client.post("/api/_clock/advance", role="PlatformAdmin", uid="admin", json={"seconds": 60})
    assert r.status_code == 200, r.text
    assert "now" in r.json()["data"]


def test_clock_seconds_required():
    r = client.post("/api/_clock/advance", role="PlatformAdmin", uid="admin", json={})
    assert r.status_code == 422
    assert r.json()["data"]["error_id"] == "ERR_VALIDATION"


def test_clock_negative_rejected():
    r = client.post("/api/_clock/advance", role="PlatformAdmin", uid="admin", json={"seconds": -1})
    assert r.status_code == 422
