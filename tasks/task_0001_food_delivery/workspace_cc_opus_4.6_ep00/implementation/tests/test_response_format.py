import pytest
import re
from tests.conftest import (
    admin_headers, customer_headers, restaurant_headers, rider_headers,
    create_restaurant, approve_restaurant, create_menu_item, create_customer,
    create_rider, setup_full_order,
)
from store import store


TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z")


def test_request_id_format(client):
    resp = client.get("/api/restaurants", headers=admin_headers())
    meta = resp.get_json()["meta"]
    assert meta["api_request_id"].startswith("req_")
    assert len(meta["api_request_id"]) > 4


def test_timestamp_format(client):
    resp = client.get("/api/restaurants", headers=admin_headers())
    ts = resp.get_json()["meta"]["api_request_timestamp"]
    assert TIMESTAMP_RE.match(ts), f"Timestamp {ts} doesn't match expected format"


def test_versioned_entity_fields(client):
    r = create_restaurant(client)
    assert "id" in r
    assert "created_at" in r
    assert "updated_at" in r
    assert "version" in r
    assert r["version"] == 1
    assert TIMESTAMP_RE.match(r["created_at"])
    assert TIMESTAMP_RE.match(r["updated_at"])


def test_unversioned_assignment_fields(client):
    s = setup_full_order(client)
    client.post(f"/api/orders/{s['order']['id']}/accept",
                headers=restaurant_headers(s["restaurant"]["id"]))
    client.post(f"/api/orders/{s['order']['id']}/start-preparing",
                headers=restaurant_headers(s["restaurant"]["id"]))

    a = next(a for a in store.assignments.values()
             if a["order_id"] == s["order"]["id"] and a["status"] == "OFFERED")
    resp = client.get(f"/api/assignments/{a['id']}", headers=admin_headers())
    data = resp.get_json()["data"]

    assert "id" in data
    assert "created_at" in data
    assert "version" not in data
    assert "updated_at" not in data


def test_unversioned_fine_fields(client):
    from models import make_unversioned
    rider = create_rider(client)
    fine = make_unversioned({
        "subject_type": "RIDER", "subject_id": rider["id"],
        "reason": "LATE_DELIVERY", "amount_cents": 200,
        "settlement_status": "PENDING", "order_id": "test",
    })
    store.fines[fine["id"]] = fine

    resp = client.get(f"/api/fines/{fine['id']}", headers=admin_headers())
    data = resp.get_json()["data"]
    assert "id" in data
    assert "created_at" in data
    assert "version" not in data
    assert "updated_at" not in data


def test_order_fields_complete(client):
    s = setup_full_order(client)
    resp = client.get(f"/api/orders/{s['order']['id']}",
                      headers=admin_headers())
    data = resp.get_json()["data"]

    assert "id" in data
    assert "customer_id" in data
    assert "restaurant_id" in data
    assert "items" in data
    assert "subtotal_cents" in data
    assert "distance_km" in data
    assert "is_peak" in data
    assert "promised_delivery_time" in data
    assert "provisional_delivery_fee_cents" in data
    assert "provisional_commission_cents" in data
    assert "final_delivery_fee_cents" in data
    assert data["final_delivery_fee_cents"] is None
    assert "final_commission_cents" in data
    assert data["final_commission_cents"] is None
    assert "actual_delivery_time" in data
    assert "minutes_late" in data
    assert "status" in data
    assert "payment_status" in data
    assert "version" in data
    assert "created_at" in data
    assert "updated_at" in data


def test_list_response_format(client):
    create_restaurant(client, name="R1")
    create_restaurant(client, name="R2")
    resp = client.get("/api/restaurants", headers=admin_headers())
    body = resp.get_json()
    assert body["response_type"] == "array"
    assert isinstance(body["data"], list)
    assert "limit" in body["meta"]
    assert "offset" in body["meta"]
    assert "total_count" in body["meta"]
    assert "has_more" in body["meta"]
    assert body["meta"]["limit"] == 10
    assert body["meta"]["offset"] == 0
    assert body["meta"]["total_count"] == 2
    assert body["meta"]["has_more"] is False


def test_single_resource_response_format(client):
    r = create_restaurant(client)
    resp = client.get(f"/api/restaurants/{r['id']}", headers=admin_headers())
    body = resp.get_json()
    assert body["response_type"] == "object"
    assert isinstance(body["data"], dict)
    assert "limit" not in body["meta"]


def test_error_response_format(client):
    resp = client.get("/api/restaurants/nonexistent", headers=admin_headers())
    body = resp.get_json()
    assert body["response_type"] == "error"
    assert "error_id" in body["data"]
    assert "message" in body["data"]
    assert body["meta"]["api_request_id"].startswith("req_")


def test_order_items_snapshot(client):
    s = setup_full_order(client)
    order = s["order"]
    assert len(order["items"]) == 1
    item = order["items"][0]
    assert "menu_item_id" in item
    assert "name" in item
    assert "unit_price_cents" in item
    assert "quantity" in item


def test_rider_has_all_metrics(client):
    rider = create_rider(client)
    resp = client.get(f"/api/riders/{rider['id']}",
                      headers=rider_headers(rider["id"]))
    data = resp.get_json()["data"]
    assert "on_time_rate" in data
    assert "acceptance_rate" in data
    assert "rating" in data
    assert "bonus_tier" in data
    assert "wallet_balance_cents" in data
    assert data["on_time_rate"] == 1.0
    assert data["acceptance_rate"] == 1.0
    assert data["rating"] == 5.0
    assert data["bonus_tier"] == "BRONZE"


def test_customer_has_credit_and_trust(client):
    c = create_customer(client)
    resp = client.get(f"/api/customers/{c['id']}",
                      headers=admin_headers())
    data = resp.get_json()["data"]
    assert data["credit_balance_cents"] == 0
    assert data["trust_score"] == 1.0


def test_201_for_creation_endpoints(client):
    r = create_restaurant(client)
    resp = client.post(f"/api/restaurants/{r['id']}/menu-items", json={
        "name": "Item", "price_cents": 500,
    }, headers=admin_headers())
    assert resp.status_code == 201

    resp = client.post("/api/riders", json={
        "name": "R", "phone": "555-0099",
    }, headers=admin_headers())
    assert resp.status_code == 201

    resp = client.post("/api/customers", json={
        "name": "C", "phone": "555-0098", "address": "Addr", "lat": 0, "lng": 0,
    }, headers=admin_headers())
    assert resp.status_code == 201


def test_200_for_action_endpoints(client):
    r = create_restaurant(client)
    resp = client.post(f"/api/restaurants/{r['id']}/approve", headers=admin_headers())
    assert resp.status_code == 200

    rider = create_rider(client)
    resp = client.post(f"/api/riders/{rider['id']}/go-online",
                       headers=rider_headers(rider["id"]))
    assert resp.status_code == 200
