from . import client
from .fixtures import make_rider


def test_rider_register_defaults():
    r = make_rider()
    assert r["status"] == "OFFLINE"
    assert r["bonus_tier"] == "BRONZE"
    assert r["wallet_balance_cents"] == 0
    assert r["on_time_rate"] == 1.0
    assert r["acceptance_rate"] == 1.0
    assert r["rating"] == 5.0


def test_rider_go_online_offline_cycle():
    r = make_rider()
    g = client.post(f"/api/riders/{r['id']}/go-online", role="Rider", uid=r["id"], json={})
    assert g.status_code == 200
    assert g.json()["data"]["status"] == "AVAILABLE"
    off = client.post(f"/api/riders/{r['id']}/go-offline", role="Rider", uid=r["id"], json={})
    assert off.status_code == 200
    assert off.json()["data"]["status"] == "OFFLINE"


def test_rider_go_online_invalid_state():
    r = make_rider(online=True)
    g = client.post(f"/api/riders/{r['id']}/go-online", role="Rider", uid=r["id"], json={})
    assert g.status_code == 409
    assert g.json()["data"]["error_id"] == "ERR_INVALID_STATE"


def test_rider_identity_match():
    r = make_rider()
    g = client.post(f"/api/riders/{r['id']}/go-online", role="Rider", uid="other", json={})
    assert g.status_code == 403


def test_rider_suspend_criteria_not_met():
    r = make_rider(online=True)
    s = client.post(f"/api/riders/{r['id']}/suspend",
                    role="PlatformAdmin", uid="admin", json={})
    assert s.status_code == 422
    assert s.json()["data"]["error_id"] == "ERR_SUSPEND_CRITERIA_NOT_MET"


def test_rider_get_forbidden_other():
    a = make_rider()
    b = make_rider()
    r = client.get(f"/api/riders/{b['id']}", role="Rider", uid=a["id"])
    assert r.status_code == 403
