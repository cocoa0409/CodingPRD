import pytest
from tests.conftest import (
    admin_headers, rider_headers, customer_headers, cs_headers,
    create_rider, setup_full_order,
)
from store import store
from models import make_unversioned


def test_get_fine(client):
    rider = create_rider(client)
    fine = make_unversioned({
        "subject_type": "RIDER", "subject_id": rider["id"],
        "reason": "LATE_DELIVERY", "amount_cents": 200,
        "settlement_status": "PENDING", "order_id": "test-order",
    })
    store.fines[fine["id"]] = fine

    resp = client.get(f"/api/fines/{fine['id']}", headers=rider_headers(rider["id"]))
    assert resp.status_code == 200
    assert resp.get_json()["data"]["amount_cents"] == 200


def test_get_fine_not_found(client):
    resp = client.get("/api/fines/nonexistent", headers=admin_headers())
    assert resp.status_code == 404


def test_get_fine_wrong_subject(client):
    rider = create_rider(client)
    rider2 = create_rider(client, name="R2", phone="555-2002")
    fine = make_unversioned({
        "subject_type": "RIDER", "subject_id": rider["id"],
        "reason": "LATE_DELIVERY", "amount_cents": 200,
        "settlement_status": "PENDING", "order_id": "test-order",
    })
    store.fines[fine["id"]] = fine

    resp = client.get(f"/api/fines/{fine['id']}", headers=rider_headers(rider2["id"]))
    assert resp.status_code == 403


def test_list_fines(client):
    rider = create_rider(client)
    for i in range(3):
        fine = make_unversioned({
            "subject_type": "RIDER", "subject_id": rider["id"],
            "reason": "LATE_DELIVERY", "amount_cents": 200,
            "settlement_status": "PENDING", "order_id": f"order-{i}",
        })
        store.fines[fine["id"]] = fine

    resp = client.get(f"/api/fines?subject_id={rider['id']}", headers=rider_headers(rider["id"]))
    assert resp.status_code == 200
    assert len(resp.get_json()["data"]) == 3


def test_list_fines_filters(client):
    rider = create_rider(client)
    fine1 = make_unversioned({
        "subject_type": "RIDER", "subject_id": rider["id"],
        "reason": "LATE_DELIVERY", "amount_cents": 200,
        "settlement_status": "PENDING", "order_id": "order-1",
    })
    fine2 = make_unversioned({
        "subject_type": "RIDER", "subject_id": rider["id"],
        "reason": "RIDER_NO_SHOW", "amount_cents": 500,
        "settlement_status": "WAIVED", "order_id": "order-2",
    })
    store.fines[fine1["id"]] = fine1
    store.fines[fine2["id"]] = fine2

    resp = client.get(f"/api/fines?settlement_status=PENDING", headers=admin_headers())
    assert len(resp.get_json()["data"]) == 1

    resp = client.get(f"/api/fines?subject_type=RIDER", headers=admin_headers())
    assert len(resp.get_json()["data"]) == 2


def test_waive_fine(client):
    rider = create_rider(client)
    store.riders[rider["id"]]["wallet_balance_cents"] = -500
    fine = make_unversioned({
        "subject_type": "RIDER", "subject_id": rider["id"],
        "reason": "RIDER_NO_SHOW", "amount_cents": 500,
        "settlement_status": "PENDING", "order_id": "test-order",
    })
    store.fines[fine["id"]] = fine

    resp = client.post(f"/api/fines/{fine['id']}/waive", headers=cs_headers())
    assert resp.status_code == 200
    assert resp.get_json()["data"]["settlement_status"] == "WAIVED"

    r = client.get(f"/api/riders/{rider['id']}", headers=admin_headers()).get_json()["data"]
    assert r["wallet_balance_cents"] == 0


def test_waive_fine_not_pending(client):
    rider = create_rider(client)
    fine = make_unversioned({
        "subject_type": "RIDER", "subject_id": rider["id"],
        "reason": "RIDER_NO_SHOW", "amount_cents": 500,
        "settlement_status": "SETTLED", "order_id": "test-order",
    })
    store.fines[fine["id"]] = fine

    resp = client.post(f"/api/fines/{fine['id']}/waive", headers=cs_headers())
    assert resp.status_code == 409


def test_waive_customer_fine(client):
    from tests.conftest import create_customer
    c = create_customer(client)
    fine = make_unversioned({
        "subject_type": "CUSTOMER", "subject_id": c["id"],
        "reason": "ABUSIVE_RETURN", "amount_cents": 300,
        "settlement_status": "PENDING", "order_id": "test-order",
    })
    store.fines[fine["id"]] = fine

    resp = client.post(f"/api/fines/{fine['id']}/waive", headers=admin_headers())
    assert resp.status_code == 200

    customer = client.get(f"/api/customers/{c['id']}", headers=admin_headers()).get_json()["data"]
    assert customer["credit_balance_cents"] == 300


def test_waive_abusive_return_fine_restores_credit(client):
    """End-to-end: approve return with abusive fine → credit debited → waive → credit restored."""
    from tests.conftest import (
        create_restaurant, approve_restaurant, create_menu_item,
        create_customer, create_rider, restaurant_headers, rider_headers,
        customer_headers,
    )
    from tests.test_returns import deliver_order

    r = create_restaurant(client)
    approve_restaurant(client, r["id"])
    mi = create_menu_item(client, r["id"], price_cents=1000)
    c = create_customer(client)
    rider = create_rider(client)
    client.post(f"/api/riders/{rider['id']}/go-online", headers=rider_headers(rider["id"]))

    resp = client.post("/api/orders", json={
        "customer_id": c["id"], "restaurant_id": r["id"],
        "items": [{"menu_item_id": mi["id"], "quantity": 1}],
    }, headers=customer_headers(c["id"]))
    order = resp.get_json()["data"]

    s = {"order": order, "rider": rider, "restaurant": r, "customer": c, "menu_item": mi}
    deliver_order(client, s)

    store.customers[c["id"]]["trust_score"] = 0.3

    resp = client.post(f"/api/orders/{order['id']}/returns", json={
        "reason": "QUALITY_ISSUE", "requested_refund_cents": 500,
    }, headers=customer_headers(c["id"]))
    return_id = resp.get_json()["data"]["id"]

    client.post(f"/api/returns/{return_id}/approve", json={
        "approved_refund_cents": 500,
    }, headers=cs_headers())

    cust = client.get(f"/api/customers/{c['id']}", headers=admin_headers()).get_json()["data"]
    assert cust["credit_balance_cents"] == 0  # +500 refund, -500 abusive fine

    fine = next(f for f in store.fines.values() if f["reason"] == "ABUSIVE_RETURN")
    resp = client.post(f"/api/fines/{fine['id']}/waive", headers=cs_headers())
    assert resp.status_code == 200

    cust = client.get(f"/api/customers/{c['id']}", headers=admin_headers()).get_json()["data"]
    assert cust["credit_balance_cents"] == 500  # fine waived, credit restored


def test_waive_restaurant_fine(client):
    from tests.conftest import create_restaurant
    r = create_restaurant(client)
    fine = make_unversioned({
        "subject_type": "RESTAURANT", "subject_id": r["id"],
        "reason": "RESTAURANT_STOCKOUT", "amount_cents": 1000,
        "settlement_status": "PENDING", "order_id": "test-order",
    })
    store.fines[fine["id"]] = fine

    resp = client.post(f"/api/fines/{fine['id']}/waive", headers=admin_headers())
    assert resp.status_code == 200

    rest = client.get(f"/api/restaurants/{r['id']}", headers=admin_headers()).get_json()["data"]
    assert rest["pending_settlement_cents"] == 1000
