import pytest
from tests.conftest import admin_headers


def test_missing_headers(client):
    resp = client.get("/api/restaurants")
    assert resp.status_code == 401
    assert resp.get_json()["data"]["error_id"] == "ERR_AUTH_REQUIRED"


def test_missing_user_id(client):
    resp = client.get("/api/restaurants", headers={"X-User-Role": "PlatformAdmin"})
    assert resp.status_code == 401


def test_missing_role(client):
    resp = client.get("/api/restaurants", headers={"X-User-ID": "user1"})
    assert resp.status_code == 401


def test_invalid_role(client):
    resp = client.get("/api/restaurants", headers={"X-User-ID": "user1", "X-User-Role": "InvalidRole"})
    assert resp.status_code == 401
    assert resp.get_json()["data"]["error_id"] == "ERR_AUTH_REQUIRED"


def test_forbidden_role(client):
    resp = client.post("/api/restaurants", json={"name": "Test"},
                       headers={"X-User-ID": "c1", "X-User-Role": "Customer"})
    assert resp.status_code == 403
    assert resp.get_json()["data"]["error_id"] == "ERR_FORBIDDEN"


def test_response_envelope_format(client):
    resp = client.get("/api/restaurants", headers=admin_headers())
    body = resp.get_json()
    assert "meta" in body
    assert body["meta"]["api_request_id"].startswith("req_")
    assert "api_request_timestamp" in body["meta"]
    assert body["response_type"] == "array"
    assert isinstance(body["data"], list)


def test_error_response_envelope(client):
    resp = client.get("/api/restaurants")
    body = resp.get_json()
    assert body["response_type"] == "error"
    assert "error_id" in body["data"]
    assert "message" in body["data"]
