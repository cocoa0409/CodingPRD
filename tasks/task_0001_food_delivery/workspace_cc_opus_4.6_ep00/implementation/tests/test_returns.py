import pytest
from tests.conftest import (
    admin_headers, customer_headers, restaurant_headers, rider_headers, cs_headers,
    create_restaurant, approve_restaurant, create_menu_item, create_customer,
    create_rider, setup_full_order,
)
from store import store


def deliver_order(client, s):
    oid = s["order"]["id"]
    rid = s["rider"]["id"]
    rest_id = s["restaurant"]["id"]

    client.post(f"/api/orders/{oid}/accept", headers=restaurant_headers(rest_id))
    client.post(f"/api/orders/{oid}/start-preparing", headers=restaurant_headers(rest_id))

    assignment = None
    for a in store.assignments.values():
        if a["order_id"] == oid and a["status"] == "OFFERED":
            assignment = a
            break

    client.post(f"/api/assignments/{assignment['id']}/accept", headers=rider_headers(rid))
    client.post(f"/api/orders/{oid}/ready", headers=restaurant_headers(rest_id))
    client.post(f"/api/assignments/{assignment['id']}/pickup", headers=rider_headers(rid))
    client.post(f"/api/assignments/{assignment['id']}/deliver", headers=rider_headers(rid))
    return assignment


def test_create_return(client):
    s = setup_full_order(client)
    deliver_order(client, s)

    resp = client.post(f"/api/orders/{s['order']['id']}/returns", json={
        "reason": "QUALITY_ISSUE",
        "requested_refund_cents": 500,
    }, headers=customer_headers(s["customer"]["id"]))
    assert resp.status_code == 201
    data = resp.get_json()["data"]
    assert data["status"] == "REQUESTED"
    assert data["reason"] == "QUALITY_ISSUE"
    assert data["requested_refund_cents"] == 500

    order = client.get(f"/api/orders/{s['order']['id']}", headers=admin_headers()).get_json()["data"]
    assert order["status"] == "REFUND_REQUESTED"


def test_create_return_not_delivered(client):
    s = setup_full_order(client)
    resp = client.post(f"/api/orders/{s['order']['id']}/returns", json={
        "reason": "QUALITY_ISSUE", "requested_refund_cents": 500,
    }, headers=customer_headers(s["customer"]["id"]))
    assert resp.status_code == 409


def test_create_return_wrong_customer(client):
    s = setup_full_order(client)
    deliver_order(client, s)
    resp = client.post(f"/api/orders/{s['order']['id']}/returns", json={
        "reason": "QUALITY_ISSUE", "requested_refund_cents": 500,
    }, headers=customer_headers("wrong-customer"))
    assert resp.status_code == 403


def test_create_return_invalid_refund_amount(client):
    s = setup_full_order(client)
    deliver_order(client, s)
    resp = client.post(f"/api/orders/{s['order']['id']}/returns", json={
        "reason": "QUALITY_ISSUE", "requested_refund_cents": 0,
    }, headers=customer_headers(s["customer"]["id"]))
    assert resp.status_code == 422

    resp = client.post(f"/api/orders/{s['order']['id']}/returns", json={
        "reason": "QUALITY_ISSUE", "requested_refund_cents": 999999,
    }, headers=customer_headers(s["customer"]["id"]))
    assert resp.status_code == 422


def test_create_return_expired_window(client):
    s = setup_full_order(client)
    deliver_order(client, s)

    client.post("/api/_clock/advance", json={"seconds": 86401}, headers=admin_headers())

    resp = client.post(f"/api/orders/{s['order']['id']}/returns", json={
        "reason": "QUALITY_ISSUE", "requested_refund_cents": 500,
    }, headers=customer_headers(s["customer"]["id"]))
    assert resp.status_code == 422
    assert resp.get_json()["data"]["error_id"] == "ERR_RETURN_WINDOW_EXPIRED"


def test_duplicate_return_state_check_first(client):
    """Per PRD §2.6, state-machine check (step 6) fires before uniqueness (step 8).
    After first return, order is REFUND_REQUESTED, so second attempt gets ERR_INVALID_STATE."""
    s = setup_full_order(client)
    deliver_order(client, s)

    client.post(f"/api/orders/{s['order']['id']}/returns", json={
        "reason": "QUALITY_ISSUE", "requested_refund_cents": 500,
    }, headers=customer_headers(s["customer"]["id"]))

    resp = client.post(f"/api/orders/{s['order']['id']}/returns", json={
        "reason": "WRONG_ITEM", "requested_refund_cents": 300,
    }, headers=customer_headers(s["customer"]["id"]))
    assert resp.status_code == 409
    assert resp.get_json()["data"]["error_id"] == "ERR_INVALID_STATE"


def test_duplicate_return_after_rejection(client):
    """After a return is rejected, order goes back to DELIVERED. A new return should succeed."""
    s = setup_full_order(client)
    deliver_order(client, s)

    resp = client.post(f"/api/orders/{s['order']['id']}/returns", json={
        "reason": "QUALITY_ISSUE", "requested_refund_cents": 500,
    }, headers=customer_headers(s["customer"]["id"]))
    return_id = resp.get_json()["data"]["id"]

    client.post(f"/api/returns/{return_id}/reject", headers=cs_headers())

    resp = client.post(f"/api/orders/{s['order']['id']}/returns", json={
        "reason": "WRONG_ITEM", "requested_refund_cents": 300,
    }, headers=customer_headers(s["customer"]["id"]))
    assert resp.status_code == 201


def test_approve_return(client):
    s = setup_full_order(client)
    deliver_order(client, s)

    resp = client.post(f"/api/orders/{s['order']['id']}/returns", json={
        "reason": "QUALITY_ISSUE", "requested_refund_cents": 500,
    }, headers=customer_headers(s["customer"]["id"]))
    return_id = resp.get_json()["data"]["id"]

    resp = client.post(f"/api/returns/{return_id}/approve", json={
        "approved_refund_cents": 400,
    }, headers=cs_headers())
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["status"] == "APPROVED"
    assert data["approved_refund_cents"] == 400

    order = client.get(f"/api/orders/{s['order']['id']}", headers=admin_headers()).get_json()["data"]
    assert order["status"] == "REFUNDED"
    assert order["payment_status"] == "PARTIALLY_REFUNDED"

    customer = client.get(f"/api/customers/{s['customer']['id']}",
                          headers=admin_headers()).get_json()["data"]
    assert customer["credit_balance_cents"] == 400


def test_approve_return_full_refund(client):
    s = setup_full_order(client)
    deliver_order(client, s)
    subtotal = s["order"]["subtotal_cents"]

    resp = client.post(f"/api/orders/{s['order']['id']}/returns", json={
        "reason": "WRONG_ITEM", "requested_refund_cents": subtotal,
    }, headers=customer_headers(s["customer"]["id"]))
    return_id = resp.get_json()["data"]["id"]

    resp = client.post(f"/api/returns/{return_id}/approve", json={
        "approved_refund_cents": subtotal,
    }, headers=cs_headers())
    assert resp.status_code == 200

    order = client.get(f"/api/orders/{s['order']['id']}", headers=admin_headers()).get_json()["data"]
    assert order["payment_status"] == "FULLY_REFUNDED"


def test_approve_return_invalid_amount(client):
    s = setup_full_order(client)
    deliver_order(client, s)

    resp = client.post(f"/api/orders/{s['order']['id']}/returns", json={
        "reason": "QUALITY_ISSUE", "requested_refund_cents": 500,
    }, headers=customer_headers(s["customer"]["id"]))
    return_id = resp.get_json()["data"]["id"]

    resp = client.post(f"/api/returns/{return_id}/approve", json={
        "approved_refund_cents": 600,
    }, headers=cs_headers())
    assert resp.status_code == 422
    assert resp.get_json()["data"]["error_id"] == "ERR_REFUND_AMOUNT_INVALID"


def test_reject_return(client):
    s = setup_full_order(client)
    deliver_order(client, s)

    resp = client.post(f"/api/orders/{s['order']['id']}/returns", json={
        "reason": "QUALITY_ISSUE", "requested_refund_cents": 500,
    }, headers=customer_headers(s["customer"]["id"]))
    return_id = resp.get_json()["data"]["id"]

    resp = client.post(f"/api/returns/{return_id}/reject", headers=cs_headers())
    assert resp.status_code == 200
    assert resp.get_json()["data"]["status"] == "REJECTED"

    order = client.get(f"/api/orders/{s['order']['id']}", headers=admin_headers()).get_json()["data"]
    assert order["status"] == "DELIVERED"


def test_escalate_return(client):
    s = setup_full_order(client)
    deliver_order(client, s)

    resp = client.post(f"/api/orders/{s['order']['id']}/returns", json={
        "reason": "OTHER", "requested_refund_cents": 500,
    }, headers=customer_headers(s["customer"]["id"]))
    return_id = resp.get_json()["data"]["id"]

    resp = client.post(f"/api/returns/{return_id}/escalate", headers=cs_headers())
    assert resp.status_code == 200
    assert resp.get_json()["data"]["status"] == "ESCALATED"

    wos = [wo for wo in store.work_orders.values() if wo.get("related_return_id") == return_id]
    assert len(wos) == 1


def test_reopen_return(client):
    s = setup_full_order(client)
    deliver_order(client, s)

    resp = client.post(f"/api/orders/{s['order']['id']}/returns", json={
        "reason": "OTHER", "requested_refund_cents": 500,
    }, headers=customer_headers(s["customer"]["id"]))
    return_id = resp.get_json()["data"]["id"]

    client.post(f"/api/returns/{return_id}/escalate", headers=cs_headers())
    resp = client.post(f"/api/returns/{return_id}/reopen", headers=cs_headers())
    assert resp.status_code == 200
    assert resp.get_json()["data"]["status"] == "REQUESTED"

    wos = [wo for wo in store.work_orders.values() if wo.get("related_return_id") == return_id]
    for wo in wos:
        assert wo["status"] == "CLOSED"


def test_reopen_not_escalated(client):
    s = setup_full_order(client)
    deliver_order(client, s)

    resp = client.post(f"/api/orders/{s['order']['id']}/returns", json={
        "reason": "OTHER", "requested_refund_cents": 500,
    }, headers=customer_headers(s["customer"]["id"]))
    return_id = resp.get_json()["data"]["id"]

    resp = client.post(f"/api/returns/{return_id}/reopen", headers=cs_headers())
    assert resp.status_code == 409


def test_get_return(client):
    s = setup_full_order(client)
    deliver_order(client, s)

    resp = client.post(f"/api/orders/{s['order']['id']}/returns", json={
        "reason": "QUALITY_ISSUE", "requested_refund_cents": 500,
    }, headers=customer_headers(s["customer"]["id"]))
    return_id = resp.get_json()["data"]["id"]

    resp = client.get(f"/api/returns/{return_id}", headers=cs_headers())
    assert resp.status_code == 200
    assert resp.get_json()["data"]["id"] == return_id


def test_get_return_not_found(client):
    resp = client.get("/api/returns/nonexistent", headers=cs_headers())
    assert resp.status_code == 404


def test_abusive_return_fine(client):
    s = setup_full_order(client)
    deliver_order(client, s)
    store.customers[s["customer"]["id"]]["trust_score"] = 0.3

    resp = client.post(f"/api/orders/{s['order']['id']}/returns", json={
        "reason": "QUALITY_ISSUE", "requested_refund_cents": 500,
    }, headers=customer_headers(s["customer"]["id"]))
    return_id = resp.get_json()["data"]["id"]

    client.post(f"/api/returns/{return_id}/approve", json={
        "approved_refund_cents": 500,
    }, headers=cs_headers())

    fines = [f for f in store.fines.values() if f["reason"] == "ABUSIVE_RETURN"]
    assert len(fines) == 1
    assert fines[0]["subject_type"] == "CUSTOMER"
    assert fines[0]["amount_cents"] == 500


def test_abusive_return_fine_debits_credit(client):
    """ABUSIVE_RETURN fine creation debits customer credit_balance_cents."""
    s = setup_full_order(client)
    deliver_order(client, s)
    store.customers[s["customer"]["id"]]["trust_score"] = 0.3

    resp = client.post(f"/api/orders/{s['order']['id']}/returns", json={
        "reason": "QUALITY_ISSUE", "requested_refund_cents": 500,
    }, headers=customer_headers(s["customer"]["id"]))
    return_id = resp.get_json()["data"]["id"]

    client.post(f"/api/returns/{return_id}/approve", json={
        "approved_refund_cents": 500,
    }, headers=cs_headers())

    customer = client.get(f"/api/customers/{s['customer']['id']}",
                          headers=admin_headers()).get_json()["data"]
    # Credit was +500 from refund, then -500 from abusive fine = net 0
    assert customer["credit_balance_cents"] == 0

    fines = [f for f in store.fines.values() if f["reason"] == "ABUSIVE_RETURN"]
    assert len(fines) == 1
    assert fines[0]["amount_cents"] == 500


def test_approve_escalated_return(client):
    s = setup_full_order(client)
    deliver_order(client, s)

    resp = client.post(f"/api/orders/{s['order']['id']}/returns", json={
        "reason": "OTHER", "requested_refund_cents": 500,
    }, headers=customer_headers(s["customer"]["id"]))
    return_id = resp.get_json()["data"]["id"]

    client.post(f"/api/returns/{return_id}/escalate", headers=cs_headers())

    resp = client.post(f"/api/returns/{return_id}/approve", json={
        "approved_refund_cents": 400,
    }, headers=cs_headers())
    assert resp.status_code == 200
    assert resp.get_json()["data"]["status"] == "APPROVED"
