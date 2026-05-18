import pytest
from tests.conftest import admin_headers, restaurant_headers, customer_headers, create_restaurant, approve_restaurant


def test_create_restaurant(client):
    resp = client.post("/api/restaurants", json={
        "name": "Pizza Place", "address": "123 Main St", "lat": 40.7, "lng": -74.0,
    }, headers=admin_headers())
    assert resp.status_code == 201
    data = resp.get_json()["data"]
    assert data["name"] == "Pizza Place"
    assert data["status"] == "PENDING_APPROVAL"
    assert data["pending_settlement_cents"] == 0
    assert data["version"] == 1
    assert data["commission_rate_override"] is None


def test_create_restaurant_with_commission_override(client):
    resp = client.post("/api/restaurants", json={
        "name": "Fancy Place", "address": "456 Oak St", "lat": 40.7, "lng": -74.0,
        "commission_rate_override": 0.10,
    }, headers=admin_headers())
    assert resp.status_code == 201
    assert resp.get_json()["data"]["commission_rate_override"] == 0.10


def test_create_restaurant_invalid_commission(client):
    resp = client.post("/api/restaurants", json={
        "name": "Bad Rate", "address": "789 Elm St", "lat": 40.7, "lng": -74.0,
        "commission_rate_override": 0.04,
    }, headers=admin_headers())
    assert resp.status_code == 422


def test_create_restaurant_duplicate_name(client):
    create_restaurant(client, name="Unique Name")
    resp = client.post("/api/restaurants", json={
        "name": "Unique Name", "address": "456 Oak St", "lat": 40.7, "lng": -74.0,
    }, headers=admin_headers())
    assert resp.status_code == 422


def test_create_restaurant_empty_name(client):
    resp = client.post("/api/restaurants", json={
        "name": "", "address": "123 Main St", "lat": 40.7, "lng": -74.0,
    }, headers=admin_headers())
    assert resp.status_code == 422


def test_create_restaurant_name_too_long(client):
    resp = client.post("/api/restaurants", json={
        "name": "A" * 121, "address": "123 Main St", "lat": 40.7, "lng": -74.0,
    }, headers=admin_headers())
    assert resp.status_code == 422


def test_list_restaurants(client):
    create_restaurant(client, name="R1")
    create_restaurant(client, name="R2")
    resp = client.get("/api/restaurants", headers=admin_headers())
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["response_type"] == "array"
    assert len(body["data"]) == 2
    assert body["meta"]["total_count"] == 2


def test_list_restaurants_with_status_filter(client):
    r1 = create_restaurant(client, name="Active Place")
    approve_restaurant(client, r1["id"])
    create_restaurant(client, name="Pending Place")
    resp = client.get("/api/restaurants?status=ACTIVE", headers=admin_headers())
    assert len(resp.get_json()["data"]) == 1


def test_list_restaurants_pagination(client):
    for i in range(15):
        create_restaurant(client, name=f"R{i}")
    resp = client.get("/api/restaurants?limit=5&offset=0", headers=admin_headers())
    body = resp.get_json()
    assert len(body["data"]) == 5
    assert body["meta"]["total_count"] == 15
    assert body["meta"]["has_more"] is True


def test_get_restaurant(client):
    r = create_restaurant(client)
    resp = client.get(f"/api/restaurants/{r['id']}", headers=admin_headers())
    assert resp.status_code == 200
    assert resp.get_json()["data"]["id"] == r["id"]


def test_get_restaurant_not_found(client):
    resp = client.get("/api/restaurants/nonexistent", headers=admin_headers())
    assert resp.status_code == 404


def test_update_restaurant(client):
    r = create_restaurant(client)
    resp = client.patch(f"/api/restaurants/{r['id']}", json={
        "address": "New Address", "lat": 41.0, "lng": -73.5,
    }, headers=restaurant_headers(r["id"]))
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["address"] == "New Address"
    assert data["version"] == 2


def test_update_restaurant_immutable_name(client):
    r = create_restaurant(client)
    resp = client.patch(f"/api/restaurants/{r['id']}", json={
        "name": "New Name",
    }, headers=restaurant_headers(r["id"]))
    assert resp.status_code == 422


def test_update_restaurant_version_conflict(client):
    r = create_restaurant(client)
    resp = client.patch(f"/api/restaurants/{r['id']}", json={
        "address": "New Address", "version": 999,
    }, headers=restaurant_headers(r["id"]))
    assert resp.status_code == 409
    assert resp.get_json()["data"]["error_id"] == "ERR_VERSION_CONFLICT"


def test_update_restaurant_version_correct(client):
    r = create_restaurant(client)
    resp = client.patch(f"/api/restaurants/{r['id']}", json={
        "address": "New Address", "version": 1,
    }, headers=restaurant_headers(r["id"]))
    assert resp.status_code == 200


def test_update_restaurant_other_restaurant_forbidden(client):
    r = create_restaurant(client)
    resp = client.patch(f"/api/restaurants/{r['id']}", json={
        "address": "New Address",
    }, headers=restaurant_headers("other-restaurant"))
    assert resp.status_code == 403


def test_approve_restaurant(client):
    r = create_restaurant(client)
    resp = client.post(f"/api/restaurants/{r['id']}/approve", headers=admin_headers())
    assert resp.status_code == 200
    assert resp.get_json()["data"]["status"] == "ACTIVE"
    assert resp.get_json()["data"]["version"] == 2


def test_approve_not_pending(client):
    r = create_restaurant(client)
    approve_restaurant(client, r["id"])
    resp = client.post(f"/api/restaurants/{r['id']}/approve", headers=admin_headers())
    assert resp.status_code == 409


def test_suspend_restaurant(client):
    r = create_restaurant(client)
    approve_restaurant(client, r["id"])
    resp = client.post(f"/api/restaurants/{r['id']}/suspend", headers=admin_headers())
    assert resp.status_code == 200
    assert resp.get_json()["data"]["status"] == "SUSPENDED"


def test_suspend_not_active(client):
    r = create_restaurant(client)
    resp = client.post(f"/api/restaurants/{r['id']}/suspend", headers=admin_headers())
    assert resp.status_code == 409


def test_reinstate_restaurant(client):
    r = create_restaurant(client)
    approve_restaurant(client, r["id"])
    client.post(f"/api/restaurants/{r['id']}/suspend", headers=admin_headers())
    resp = client.post(f"/api/restaurants/{r['id']}/reinstate", headers=admin_headers())
    assert resp.status_code == 200
    assert resp.get_json()["data"]["status"] == "ACTIVE"


def test_reinstate_not_suspended(client):
    r = create_restaurant(client)
    approve_restaurant(client, r["id"])
    resp = client.post(f"/api/restaurants/{r['id']}/reinstate", headers=admin_headers())
    assert resp.status_code == 409


def test_settle_restaurant(client):
    r = create_restaurant(client)
    resp = client.post(f"/api/restaurants/{r['id']}/settle", headers=admin_headers())
    assert resp.status_code == 200
    assert resp.get_json()["data"]["pending_settlement_cents"] == 0


def test_suspend_cancels_placed_orders(client):
    from tests.conftest import create_menu_item, create_customer
    r = create_restaurant(client)
    approve_restaurant(client, r["id"])
    mi = create_menu_item(client, r["id"])
    c = create_customer(client)
    resp = client.post("/api/orders", json={
        "customer_id": c["id"], "restaurant_id": r["id"],
        "items": [{"menu_item_id": mi["id"], "quantity": 1}],
    }, headers=customer_headers(c["id"]))
    order = resp.get_json()["data"]

    client.post(f"/api/restaurants/{r['id']}/suspend", headers=admin_headers())

    resp = client.get(f"/api/orders/{order['id']}", headers=admin_headers())
    assert resp.get_json()["data"]["status"] == "CANCELLED"
    assert resp.get_json()["data"]["payment_status"] == "VOIDED"
