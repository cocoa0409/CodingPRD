from . import client


def test_envelope_success_shape():
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert "meta" in body and "data" in body and "response_type" in body
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")
    assert "T" in body["meta"]["api_request_timestamp"]
    assert body["meta"]["api_request_timestamp"].endswith("Z")


def test_auth_required_missing_headers():
    r = client.get("/api/restaurants")
    body = r.json()
    assert r.status_code == 401, r.text
    assert body["data"]["error_id"] == "ERR_AUTH_REQUIRED"


def test_auth_invalid_role():
    r = client.get("/api/restaurants",
                   headers={"X-User-ID": "x", "X-User-Role": "NotAReal"})
    assert r.status_code == 401
    assert r.json()["data"]["error_id"] == "ERR_AUTH_REQUIRED"


def test_forbidden_role():
    # Only PlatformAdmin can register a restaurant
    r = client.post("/api/restaurants", role="Customer", uid="c1",
                    json={"name": "x", "address": "y", "lat": 0, "lng": 0})
    assert r.status_code == 403
    assert r.json()["data"]["error_id"] == "ERR_FORBIDDEN"


def test_error_response_shape():
    r = client.get("/api/restaurants/nonexistent",
                   role="PlatformAdmin", uid="admin")
    assert r.status_code == 404
    body = r.json()
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == "ERR_NOT_FOUND"
    assert "message" in body["data"]


def test_meta_only_id_and_timestamp_on_error():
    r = client.get("/api/restaurants/nope", role="PlatformAdmin", uid="admin")
    keys = set(r.json()["meta"].keys())
    assert keys == {"api_request_id", "api_request_timestamp"}
