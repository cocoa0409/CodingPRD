import pytest
from tests.conftest import (
    admin_headers, customer_headers, restaurant_headers, rider_headers, cs_headers,
    create_customer, create_rider, create_restaurant,
)
from store import store


def test_create_work_order(client):
    c = create_customer(client)
    resp = client.post("/api/work-orders", json={
        "opened_by_role": "CUSTOMER", "opened_by_id": c["id"],
        "category": "PAYMENT_ISSUE",
    }, headers=customer_headers(c["id"]))
    assert resp.status_code == 201
    data = resp.get_json()["data"]
    assert data["status"] == "OPEN"
    assert data["opened_by_role"] == "CUSTOMER"
    assert data["assigned_cs_user_id"] is None


def test_create_work_order_with_related_ids(client):
    from tests.conftest import setup_full_order
    s = setup_full_order(client)
    resp = client.post("/api/work-orders", json={
        "opened_by_role": "CUSTOMER", "opened_by_id": s["customer"]["id"],
        "category": "DELIVERY_LATE",
        "related_order_id": s["order"]["id"],
    }, headers=customer_headers(s["customer"]["id"]))
    assert resp.status_code == 201


def test_create_work_order_invalid_category(client):
    c = create_customer(client)
    resp = client.post("/api/work-orders", json={
        "opened_by_role": "CUSTOMER", "opened_by_id": c["id"],
        "category": "INVALID",
    }, headers=customer_headers(c["id"]))
    assert resp.status_code == 422


def test_get_work_order(client):
    c = create_customer(client)
    resp = client.post("/api/work-orders", json={
        "opened_by_role": "CUSTOMER", "opened_by_id": c["id"],
        "category": "OTHER",
    }, headers=customer_headers(c["id"]))
    wo_id = resp.get_json()["data"]["id"]

    resp = client.get(f"/api/work-orders/{wo_id}", headers=cs_headers())
    assert resp.status_code == 200


def test_get_work_order_not_found(client):
    resp = client.get("/api/work-orders/nonexistent", headers=admin_headers())
    assert resp.status_code == 404


def test_assign_work_order(client):
    c = create_customer(client)
    resp = client.post("/api/work-orders", json={
        "opened_by_role": "CUSTOMER", "opened_by_id": c["id"],
        "category": "OTHER",
    }, headers=customer_headers(c["id"]))
    wo_id = resp.get_json()["data"]["id"]

    resp = client.post(f"/api/work-orders/{wo_id}/assign", headers=cs_headers())
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["status"] == "UNDER_REVIEW"
    assert data["assigned_cs_user_id"] == "cs1"


def test_assign_not_open(client):
    c = create_customer(client)
    resp = client.post("/api/work-orders", json={
        "opened_by_role": "CUSTOMER", "opened_by_id": c["id"],
        "category": "OTHER",
    }, headers=customer_headers(c["id"]))
    wo_id = resp.get_json()["data"]["id"]

    client.post(f"/api/work-orders/{wo_id}/assign", headers=cs_headers())
    resp = client.post(f"/api/work-orders/{wo_id}/assign", headers=cs_headers())
    assert resp.status_code == 409


def test_request_info(client):
    c = create_customer(client)
    resp = client.post("/api/work-orders", json={
        "opened_by_role": "CUSTOMER", "opened_by_id": c["id"],
        "category": "OTHER",
    }, headers=customer_headers(c["id"]))
    wo_id = resp.get_json()["data"]["id"]

    client.post(f"/api/work-orders/{wo_id}/assign", headers=cs_headers())
    resp = client.post(f"/api/work-orders/{wo_id}/request-info", headers=cs_headers())
    assert resp.status_code == 200
    assert resp.get_json()["data"]["status"] == "AWAITING_INFO"


def test_submit_info(client):
    c = create_customer(client)
    resp = client.post("/api/work-orders", json={
        "opened_by_role": "CUSTOMER", "opened_by_id": c["id"],
        "category": "OTHER",
    }, headers=customer_headers(c["id"]))
    wo_id = resp.get_json()["data"]["id"]

    client.post(f"/api/work-orders/{wo_id}/assign", headers=cs_headers())
    client.post(f"/api/work-orders/{wo_id}/request-info", headers=cs_headers())
    resp = client.post(f"/api/work-orders/{wo_id}/submit-info", headers=customer_headers(c["id"]))
    assert resp.status_code == 200
    assert resp.get_json()["data"]["status"] == "UNDER_REVIEW"


def test_submit_info_wrong_opener(client):
    c = create_customer(client)
    resp = client.post("/api/work-orders", json={
        "opened_by_role": "CUSTOMER", "opened_by_id": c["id"],
        "category": "OTHER",
    }, headers=customer_headers(c["id"]))
    wo_id = resp.get_json()["data"]["id"]

    client.post(f"/api/work-orders/{wo_id}/assign", headers=cs_headers())
    client.post(f"/api/work-orders/{wo_id}/request-info", headers=cs_headers())

    c2 = create_customer(client, name="Other", phone="555-9999")
    resp = client.post(f"/api/work-orders/{wo_id}/submit-info", headers=customer_headers(c2["id"]))
    assert resp.status_code == 403


def test_resolve_work_order(client):
    c = create_customer(client)
    resp = client.post("/api/work-orders", json={
        "opened_by_role": "CUSTOMER", "opened_by_id": c["id"],
        "category": "OTHER",
    }, headers=customer_headers(c["id"]))
    wo_id = resp.get_json()["data"]["id"]

    client.post(f"/api/work-orders/{wo_id}/assign", headers=cs_headers())
    resp = client.post(f"/api/work-orders/{wo_id}/resolve", json={
        "resolution_notes": "Fixed the issue",
    }, headers=cs_headers())
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["status"] == "RESOLVED"
    assert data["resolution_notes"] == "Fixed the issue"


def test_resolve_without_assignment(client):
    c = create_customer(client)
    resp = client.post("/api/work-orders", json={
        "opened_by_role": "CUSTOMER", "opened_by_id": c["id"],
        "category": "OTHER",
    }, headers=customer_headers(c["id"]))
    wo_id = resp.get_json()["data"]["id"]
    store.work_orders[wo_id]["status"] = "UNDER_REVIEW"
    resp = client.post(f"/api/work-orders/{wo_id}/resolve", json={
        "resolution_notes": "Fixed",
    }, headers=cs_headers())
    assert resp.status_code == 409


def test_resolve_with_unresolved_return(client):
    from tests.conftest import setup_full_order
    from tests.test_returns import deliver_order
    s = setup_full_order(client)
    deliver_order(client, s)

    resp = client.post(f"/api/orders/{s['order']['id']}/returns", json={
        "reason": "OTHER", "requested_refund_cents": 500,
    }, headers=customer_headers(s["customer"]["id"]))
    return_id = resp.get_json()["data"]["id"]

    resp = client.post("/api/work-orders", json={
        "opened_by_role": "CUSTOMER", "opened_by_id": s["customer"]["id"],
        "category": "OTHER", "related_return_id": return_id,
    }, headers=customer_headers(s["customer"]["id"]))
    wo_id = resp.get_json()["data"]["id"]

    client.post(f"/api/work-orders/{wo_id}/assign", headers=cs_headers())
    resp = client.post(f"/api/work-orders/{wo_id}/resolve", json={
        "resolution_notes": "Done",
    }, headers=cs_headers())
    assert resp.status_code == 422
    assert resp.get_json()["data"]["error_id"] == "ERR_RELATED_RETURN_UNRESOLVED"


def test_escalate_work_order(client):
    c = create_customer(client)
    resp = client.post("/api/work-orders", json={
        "opened_by_role": "CUSTOMER", "opened_by_id": c["id"],
        "category": "OTHER",
    }, headers=customer_headers(c["id"]))
    wo_id = resp.get_json()["data"]["id"]

    client.post(f"/api/work-orders/{wo_id}/assign", headers=cs_headers())
    resp = client.post(f"/api/work-orders/{wo_id}/escalate", headers=cs_headers())
    assert resp.status_code == 200
    assert resp.get_json()["data"]["status"] == "ESCALATED"


def test_close_work_order(client):
    c = create_customer(client)
    resp = client.post("/api/work-orders", json={
        "opened_by_role": "CUSTOMER", "opened_by_id": c["id"],
        "category": "OTHER",
    }, headers=customer_headers(c["id"]))
    wo_id = resp.get_json()["data"]["id"]

    client.post(f"/api/work-orders/{wo_id}/assign", headers=cs_headers())
    client.post(f"/api/work-orders/{wo_id}/resolve", json={
        "resolution_notes": "Done",
    }, headers=cs_headers())
    resp = client.post(f"/api/work-orders/{wo_id}/close", headers=cs_headers())
    assert resp.status_code == 200
    assert resp.get_json()["data"]["status"] == "CLOSED"


def test_close_not_resolved(client):
    c = create_customer(client)
    resp = client.post("/api/work-orders", json={
        "opened_by_role": "CUSTOMER", "opened_by_id": c["id"],
        "category": "OTHER",
    }, headers=customer_headers(c["id"]))
    wo_id = resp.get_json()["data"]["id"]

    resp = client.post(f"/api/work-orders/{wo_id}/close", headers=cs_headers())
    assert resp.status_code == 409


def test_resolve_escalated_work_order(client):
    c = create_customer(client)
    resp = client.post("/api/work-orders", json={
        "opened_by_role": "CUSTOMER", "opened_by_id": c["id"],
        "category": "OTHER",
    }, headers=customer_headers(c["id"]))
    wo_id = resp.get_json()["data"]["id"]

    client.post(f"/api/work-orders/{wo_id}/assign", headers=cs_headers())
    client.post(f"/api/work-orders/{wo_id}/escalate", headers=cs_headers())
    resp = client.post(f"/api/work-orders/{wo_id}/resolve", json={
        "resolution_notes": "Escalated and resolved",
    }, headers=cs_headers())
    assert resp.status_code == 200
    assert resp.get_json()["data"]["status"] == "RESOLVED"
