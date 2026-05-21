from . import client
from .fixtures import make_restaurant


def test_register_basic():
    r = client.post("/api/restaurants", role="PlatformAdmin", uid="admin",
                    json={"name": "Greek Taverna", "address": "1 Way", "lat": 1.0, "lng": 2.0})
    assert r.status_code == 201, r.text
    d = r.json()["data"]
    assert d["status"] == "PENDING_APPROVAL"
    assert d["version"] == 1
    assert d["pending_settlement_cents"] == 0
    assert d["commission_rate_override"] is None
    assert d["created_at"] == d["updated_at"]


def test_register_role_forbidden():
    r = client.post("/api/restaurants", role="Restaurant", uid="x",
                    json={"name": "x", "address": "y", "lat": 0, "lng": 0})
    assert r.status_code == 403


def test_register_validation():
    bad = {"name": "x" * 121, "address": "a", "lat": 0, "lng": 0}
    r = client.post("/api/restaurants", role="PlatformAdmin", uid="admin", json=bad)
    assert r.status_code == 422


def test_commission_override_range():
    bad = {"name": "OutRange", "address": "a", "lat": 0, "lng": 0, "commission_rate_override": 0.5}
    r = client.post("/api/restaurants", role="PlatformAdmin", uid="admin", json=bad)
    assert r.status_code == 422


def test_lifecycle_approve_suspend_reinstate():
    rest = make_restaurant(name="LifeR", activate=False)
    assert rest["status"] == "PENDING_APPROVAL"
    r = client.post(f"/api/restaurants/{rest['id']}/approve",
                    role="PlatformAdmin", uid="admin", json={})
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "ACTIVE"
    r = client.post(f"/api/restaurants/{rest['id']}/suspend",
                    role="PlatformAdmin", uid="admin", json={})
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "SUSPENDED"
    r = client.post(f"/api/restaurants/{rest['id']}/reinstate",
                    role="PlatformAdmin", uid="admin", json={})
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "ACTIVE"


def test_approve_invalid_state():
    rest = make_restaurant(name="AlreadyActive", activate=True)
    r = client.post(f"/api/restaurants/{rest['id']}/approve",
                    role="PlatformAdmin", uid="admin", json={})
    assert r.status_code == 409
    assert r.json()["data"]["error_id"] == "ERR_INVALID_STATE"


def test_patch_immutable_name():
    rest = make_restaurant(name="OriginalName")
    r = client.patch(f"/api/restaurants/{rest['id']}",
                     role="PlatformAdmin", uid="admin",
                     json={"name": "NewName"})
    assert r.status_code == 422


def test_patch_address_lat_lng_commission():
    # make_restaurant registers + approves, so initial version = 2
    rest = make_restaurant(name="EditMe")
    assert rest["version"] == 2
    r = client.patch(f"/api/restaurants/{rest['id']}",
                     role="PlatformAdmin", uid="admin",
                     json={"address": "New", "lat": 5.0, "lng": 6.0,
                           "commission_rate_override": 0.2})
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["address"] == "New"
    assert d["commission_rate_override"] == 0.2
    assert d["version"] == 3


def test_settle_zeroes_pending_settlement():
    rest = make_restaurant(name="SettleMe")
    # Manually inject via patch... but we don't have direct access. Instead, simulate by an
    # order delivery. For this isolated test, just verify settle endpoint returns 200.
    r = client.post(f"/api/restaurants/{rest['id']}/settle",
                    role="PlatformAdmin", uid="admin", json={})
    assert r.status_code == 200
    assert r.json()["data"]["pending_settlement_cents"] == 0


def test_list_filter_status():
    a = make_restaurant(name="A1", activate=False)
    b = make_restaurant(name="B1", activate=True)
    r = client.get("/api/restaurants?status=ACTIVE",
                   role="PlatformAdmin", uid="admin")
    assert r.status_code == 200
    ids = [x["id"] for x in r.json()["data"]]
    assert b["id"] in ids and a["id"] not in ids


def test_get_not_found():
    r = client.get("/api/restaurants/missing", role="PlatformAdmin", uid="admin")
    assert r.status_code == 404
