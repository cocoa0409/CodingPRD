import pytest
from tests.conftest import admin_headers, customer_headers, cs_headers, create_customer


def test_create_customer(client):
    resp = client.post("/api/customers", json={
        "name": "Jane Doe", "phone": "555-0001",
        "address": "456 Oak Ave", "lat": 40.75, "lng": -73.99,
    }, headers=admin_headers())
    assert resp.status_code == 201
    data = resp.get_json()["data"]
    assert data["name"] == "Jane Doe"
    assert data["credit_balance_cents"] == 0
    assert data["trust_score"] == 1.0
    assert data["version"] == 1


def test_create_customer_by_cs(client):
    resp = client.post("/api/customers", json={
        "name": "CS Created", "phone": "555-0002",
        "address": "789 Elm St", "lat": 40.75, "lng": -73.99,
    }, headers=cs_headers())
    assert resp.status_code == 201


def test_create_customer_duplicate_phone(client):
    create_customer(client, phone="555-0001")
    resp = client.post("/api/customers", json={
        "name": "Duplicate", "phone": "555-0001",
        "address": "789 Elm St", "lat": 40.75, "lng": -73.99,
    }, headers=admin_headers())
    assert resp.status_code == 422


def test_get_customer_own_profile(client):
    c = create_customer(client)
    resp = client.get(f"/api/customers/{c['id']}", headers=customer_headers(c["id"]))
    assert resp.status_code == 200
    assert resp.get_json()["data"]["id"] == c["id"]


def test_get_customer_other_profile_forbidden(client):
    c = create_customer(client)
    resp = client.get(f"/api/customers/{c['id']}", headers=customer_headers("other-customer"))
    assert resp.status_code == 403


def test_get_customer_by_admin(client):
    c = create_customer(client)
    resp = client.get(f"/api/customers/{c['id']}", headers=admin_headers())
    assert resp.status_code == 200


def test_get_customer_by_cs(client):
    c = create_customer(client)
    resp = client.get(f"/api/customers/{c['id']}", headers=cs_headers())
    assert resp.status_code == 200


def test_get_customer_not_found(client):
    resp = client.get("/api/customers/nonexistent", headers=admin_headers())
    assert resp.status_code == 404
