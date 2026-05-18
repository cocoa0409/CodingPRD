import pytest
from tests.conftest import admin_headers, rider_headers, create_rider


def test_create_rider(client):
    resp = client.post("/api/riders", json={
        "name": "Rider One", "phone": "555-1001",
    }, headers=admin_headers())
    assert resp.status_code == 201
    data = resp.get_json()["data"]
    assert data["name"] == "Rider One"
    assert data["status"] == "OFFLINE"
    assert data["wallet_balance_cents"] == 0
    assert data["on_time_rate"] == 1.0
    assert data["acceptance_rate"] == 1.0
    assert data["rating"] == 5.0
    assert data["bonus_tier"] == "BRONZE"
    assert data["version"] == 1


def test_create_rider_duplicate_phone(client):
    create_rider(client, phone="555-1001")
    resp = client.post("/api/riders", json={
        "name": "Rider Two", "phone": "555-1001",
    }, headers=admin_headers())
    assert resp.status_code == 422


def test_get_rider(client):
    r = create_rider(client)
    resp = client.get(f"/api/riders/{r['id']}", headers=rider_headers(r["id"]))
    assert resp.status_code == 200


def test_get_rider_other_forbidden(client):
    r = create_rider(client)
    resp = client.get(f"/api/riders/{r['id']}", headers=rider_headers("other-rider"))
    assert resp.status_code == 403


def test_go_online(client):
    r = create_rider(client)
    resp = client.post(f"/api/riders/{r['id']}/go-online", headers=rider_headers(r["id"]))
    assert resp.status_code == 200
    assert resp.get_json()["data"]["status"] == "AVAILABLE"


def test_go_online_not_offline(client):
    r = create_rider(client)
    client.post(f"/api/riders/{r['id']}/go-online", headers=rider_headers(r["id"]))
    resp = client.post(f"/api/riders/{r['id']}/go-online", headers=rider_headers(r["id"]))
    assert resp.status_code == 409


def test_go_online_other_rider_forbidden(client):
    r = create_rider(client)
    resp = client.post(f"/api/riders/{r['id']}/go-online", headers=rider_headers("other"))
    assert resp.status_code == 403


def test_go_offline(client):
    r = create_rider(client)
    client.post(f"/api/riders/{r['id']}/go-online", headers=rider_headers(r["id"]))
    resp = client.post(f"/api/riders/{r['id']}/go-offline", headers=rider_headers(r["id"]))
    assert resp.status_code == 200
    assert resp.get_json()["data"]["status"] == "OFFLINE"


def test_go_offline_not_available(client):
    r = create_rider(client)
    resp = client.post(f"/api/riders/{r['id']}/go-offline", headers=rider_headers(r["id"]))
    assert resp.status_code == 409


def test_suspend_rider_below_threshold(client):
    from store import store
    r = create_rider(client)
    client.post(f"/api/riders/{r['id']}/go-online", headers=rider_headers(r["id"]))
    store.riders[r["id"]]["on_time_rate"] = 0.60
    resp = client.post(f"/api/riders/{r['id']}/suspend", headers=admin_headers())
    assert resp.status_code == 200
    assert resp.get_json()["data"]["status"] == "SUSPENDED"


def test_suspend_rider_acceptance_below_threshold(client):
    from store import store
    r = create_rider(client)
    client.post(f"/api/riders/{r['id']}/go-online", headers=rider_headers(r["id"]))
    store.riders[r["id"]]["acceptance_rate"] = 0.40
    resp = client.post(f"/api/riders/{r['id']}/suspend", headers=admin_headers())
    assert resp.status_code == 200


def test_suspend_rider_criteria_not_met(client):
    r = create_rider(client)
    client.post(f"/api/riders/{r['id']}/go-online", headers=rider_headers(r["id"]))
    resp = client.post(f"/api/riders/{r['id']}/suspend", headers=admin_headers())
    assert resp.status_code == 422
    assert resp.get_json()["data"]["error_id"] == "ERR_SUSPEND_CRITERIA_NOT_MET"


def test_suspend_rider_not_available(client):
    r = create_rider(client)
    resp = client.post(f"/api/riders/{r['id']}/suspend", headers=admin_headers())
    assert resp.status_code == 409
