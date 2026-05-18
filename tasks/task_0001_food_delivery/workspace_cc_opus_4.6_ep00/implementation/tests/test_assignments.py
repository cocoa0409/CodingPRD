import pytest
from tests.conftest import (
    admin_headers, customer_headers, restaurant_headers, rider_headers,
    create_restaurant, approve_restaurant, create_menu_item, create_customer,
    create_rider, setup_full_order,
)
from store import store


def get_assignment_for_order(order_id):
    for a in store.assignments.values():
        if a["order_id"] == order_id and a["status"] == "OFFERED":
            return a
    return None


def progress_to_dispatch(client, setup):
    s = setup
    client.post(f"/api/orders/{s['order']['id']}/accept",
                headers=restaurant_headers(s["restaurant"]["id"]))
    client.post(f"/api/orders/{s['order']['id']}/start-preparing",
                headers=restaurant_headers(s["restaurant"]["id"]))
    return get_assignment_for_order(s["order"]["id"])


def test_assignment_created_on_dispatch(client):
    s = setup_full_order(client)
    a = progress_to_dispatch(client, s)
    assert a is not None
    assert a["status"] == "OFFERED"
    assert a["rider_id"] == s["rider"]["id"]
    assert a["order_id"] == s["order"]["id"]


def test_accept_assignment(client):
    s = setup_full_order(client)
    a = progress_to_dispatch(client, s)
    resp = client.post(f"/api/assignments/{a['id']}/accept",
                       headers=rider_headers(s["rider"]["id"]))
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["status"] == "ACCEPTED"
    assert data["accepted_at"] is not None

    rider = client.get(f"/api/riders/{s['rider']['id']}",
                       headers=rider_headers(s["rider"]["id"])).get_json()["data"]
    assert rider["status"] == "ON_DELIVERY"


def test_accept_assignment_wrong_rider(client):
    s = setup_full_order(client)
    a = progress_to_dispatch(client, s)
    r2 = create_rider(client, name="R2", phone="555-2002")
    resp = client.post(f"/api/assignments/{a['id']}/accept",
                       headers=rider_headers(r2["id"]))
    assert resp.status_code == 403


def test_accept_assignment_not_offered(client):
    s = setup_full_order(client)
    a = progress_to_dispatch(client, s)
    client.post(f"/api/assignments/{a['id']}/accept",
                headers=rider_headers(s["rider"]["id"]))
    resp = client.post(f"/api/assignments/{a['id']}/accept",
                       headers=rider_headers(s["rider"]["id"]))
    assert resp.status_code == 409


def test_reject_assignment(client):
    s = setup_full_order(client)
    a = progress_to_dispatch(client, s)
    resp = client.post(f"/api/assignments/{a['id']}/reject",
                       headers=rider_headers(s["rider"]["id"]))
    assert resp.status_code == 200
    assert resp.get_json()["data"]["status"] == "REJECTED"


def test_reject_triggers_redispatch(client):
    r2 = create_rider(client, name="Rider Two", phone="555-2002")
    client.post(f"/api/riders/{r2['id']}/go-online", headers=rider_headers(r2["id"]))
    s = setup_full_order(client)
    a = progress_to_dispatch(client, s)

    client.post(f"/api/assignments/{a['id']}/reject",
                headers=rider_headers(s["rider"]["id"]))

    new_assignments = [
        aa for aa in store.assignments.values()
        if aa["order_id"] == s["order"]["id"] and aa["status"] == "OFFERED"
    ]
    assert len(new_assignments) >= 1


def test_pickup_assignment(client):
    s = setup_full_order(client)
    a = progress_to_dispatch(client, s)
    client.post(f"/api/assignments/{a['id']}/accept",
                headers=rider_headers(s["rider"]["id"]))
    client.post(f"/api/orders/{s['order']['id']}/ready",
                headers=restaurant_headers(s["restaurant"]["id"]))

    resp = client.post(f"/api/assignments/{a['id']}/pickup",
                       headers=rider_headers(s["rider"]["id"]))
    assert resp.status_code == 200
    assert resp.get_json()["data"]["status"] == "PICKED_UP"

    order = client.get(f"/api/orders/{s['order']['id']}", headers=admin_headers()).get_json()["data"]
    assert order["status"] == "PICKED_UP"


def test_pickup_not_accepted(client):
    s = setup_full_order(client)
    a = progress_to_dispatch(client, s)
    resp = client.post(f"/api/assignments/{a['id']}/pickup",
                       headers=rider_headers(s["rider"]["id"]))
    assert resp.status_code == 409


def test_deliver_assignment(client):
    s = setup_full_order(client)
    a = progress_to_dispatch(client, s)
    client.post(f"/api/assignments/{a['id']}/accept",
                headers=rider_headers(s["rider"]["id"]))
    client.post(f"/api/orders/{s['order']['id']}/ready",
                headers=restaurant_headers(s["restaurant"]["id"]))
    client.post(f"/api/assignments/{a['id']}/pickup",
                headers=rider_headers(s["rider"]["id"]))

    resp = client.post(f"/api/assignments/{a['id']}/deliver",
                       headers=rider_headers(s["rider"]["id"]))
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["status"] == "DELIVERED"
    assert data["delivered_at"] is not None
    assert data["final_delivery_fee_cents"] is not None

    order = client.get(f"/api/orders/{s['order']['id']}", headers=admin_headers()).get_json()["data"]
    assert order["status"] == "DELIVERED"
    assert order["payment_status"] == "CAPTURED"
    assert order["final_delivery_fee_cents"] is not None
    assert order["final_commission_cents"] is not None
    assert order["actual_delivery_time"] is not None
    assert order["minutes_late"] == 0

    rider = client.get(f"/api/riders/{s['rider']['id']}",
                       headers=rider_headers(s["rider"]["id"])).get_json()["data"]
    assert rider["status"] == "AVAILABLE"
    assert rider["wallet_balance_cents"] > 0

    restaurant = client.get(f"/api/restaurants/{s['restaurant']['id']}",
                            headers=admin_headers()).get_json()["data"]
    assert restaurant["pending_settlement_cents"] > 0


def test_deliver_not_picked_up(client):
    s = setup_full_order(client)
    a = progress_to_dispatch(client, s)
    client.post(f"/api/assignments/{a['id']}/accept",
                headers=rider_headers(s["rider"]["id"]))
    resp = client.post(f"/api/assignments/{a['id']}/deliver",
                       headers=rider_headers(s["rider"]["id"]))
    assert resp.status_code == 409


def test_cancel_assignment_after_accept(client):
    s = setup_full_order(client)
    a = progress_to_dispatch(client, s)
    client.post(f"/api/assignments/{a['id']}/accept",
                headers=rider_headers(s["rider"]["id"]))

    resp = client.post(f"/api/assignments/{a['id']}/cancel",
                       headers=rider_headers(s["rider"]["id"]))
    assert resp.status_code == 200
    assert resp.get_json()["data"]["status"] == "CANCELLED"

    rider = client.get(f"/api/riders/{s['rider']['id']}",
                       headers=rider_headers(s["rider"]["id"])).get_json()["data"]
    assert rider["wallet_balance_cents"] == -500

    fines = [f for f in store.fines.values() if f["reason"] == "RIDER_NO_SHOW"]
    assert len(fines) == 1
    assert fines[0]["amount_cents"] == 500


def test_cancel_assignment_not_accepted(client):
    s = setup_full_order(client)
    a = progress_to_dispatch(client, s)
    resp = client.post(f"/api/assignments/{a['id']}/cancel",
                       headers=rider_headers(s["rider"]["id"]))
    assert resp.status_code == 409


def test_get_assignment(client):
    s = setup_full_order(client)
    a = progress_to_dispatch(client, s)
    resp = client.get(f"/api/assignments/{a['id']}",
                      headers=rider_headers(s["rider"]["id"]))
    assert resp.status_code == 200
    assert resp.get_json()["data"]["id"] == a["id"]


def test_get_assignment_not_found(client):
    resp = client.get("/api/assignments/nonexistent", headers=admin_headers())
    assert resp.status_code == 404


def test_get_assignment_wrong_rider(client):
    s = setup_full_order(client)
    a = progress_to_dispatch(client, s)
    r2 = create_rider(client, name="R2", phone="555-2002")
    resp = client.get(f"/api/assignments/{a['id']}", headers=rider_headers(r2["id"]))
    assert resp.status_code == 403
