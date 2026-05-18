import pytest
from tests.conftest import (
    admin_headers, customer_headers, restaurant_headers, rider_headers, cs_headers,
    create_restaurant, approve_restaurant, create_menu_item, create_customer,
    create_rider, setup_full_order,
)
from store import store


def full_delivery(client, s, advance_seconds=0):
    """Take an order through the full lifecycle to DELIVERED."""
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
    assert assignment is not None

    client.post(f"/api/assignments/{assignment['id']}/accept", headers=rider_headers(rid))
    client.post(f"/api/orders/{oid}/ready", headers=restaurant_headers(rest_id))
    client.post(f"/api/assignments/{assignment['id']}/pickup", headers=rider_headers(rid))

    if advance_seconds > 0:
        client.post("/api/_clock/advance", json={"seconds": advance_seconds}, headers=admin_headers())

    resp = client.post(f"/api/assignments/{assignment['id']}/deliver", headers=rider_headers(rid))
    return resp.get_json()["data"], assignment


def test_late_delivery_fine_1_to_10_minutes(client):
    s = setup_full_order(client)
    data, assignment = full_delivery(client, s, advance_seconds=46 * 60)

    order = client.get(f"/api/orders/{s['order']['id']}", headers=admin_headers()).get_json()["data"]
    assert order["minutes_late"] >= 1
    assert order["minutes_late"] <= 10

    fines = [f for f in store.fines.values() if f["reason"] == "LATE_DELIVERY"]
    assert len(fines) == 1
    assert fines[0]["amount_cents"] == 200


def test_late_delivery_fine_11_to_30_minutes(client):
    s = setup_full_order(client)
    data, assignment = full_delivery(client, s, advance_seconds=60 * 60)

    order = client.get(f"/api/orders/{s['order']['id']}", headers=admin_headers()).get_json()["data"]
    ml = order["minutes_late"]
    assert ml >= 11

    fines = [f for f in store.fines.values() if f["reason"] == "LATE_DELIVERY"]
    assert len(fines) == 1
    expected = 500 + 50 * (ml - 10)
    assert fines[0]["amount_cents"] == expected


def test_on_time_delivery_no_fine(client):
    s = setup_full_order(client)
    data, assignment = full_delivery(client, s, advance_seconds=0)

    order = client.get(f"/api/orders/{s['order']['id']}", headers=admin_headers()).get_json()["data"]
    assert order["minutes_late"] == 0

    fines = [f for f in store.fines.values() if f["reason"] == "LATE_DELIVERY"]
    assert len(fines) == 0


def test_delivery_commission_override(client):
    r = create_restaurant(client, name="Override Restaurant")
    approve_restaurant(client, r["id"])
    mi = create_menu_item(client, r["id"], price_cents=10000)
    c = create_customer(client)
    rider = create_rider(client)
    client.post(f"/api/riders/{rider['id']}/go-online", headers=rider_headers(rider["id"]))

    resp = client.post("/api/orders", json={
        "customer_id": c["id"], "restaurant_id": r["id"],
        "items": [{"menu_item_id": mi["id"], "quantity": 1}],
    }, headers=customer_headers(c["id"]))
    order = resp.get_json()["data"]

    from services.computations import compute_tiered_commission
    assert order["provisional_commission_cents"] == compute_tiered_commission(10000)

    client.patch(f"/api/restaurants/{r['id']}", json={
        "commission_rate_override": 0.10,
    }, headers=admin_headers())

    s = {"order": order, "rider": rider, "restaurant": r, "customer": c, "menu_item": mi}
    full_delivery(client, s)

    order = client.get(f"/api/orders/{order['id']}", headers=admin_headers()).get_json()["data"]
    assert order["final_commission_cents"] == 1000  # 10000 * 0.10


def test_delivery_version_increments_once(client):
    s = setup_full_order(client)

    order_before = client.get(f"/api/orders/{s['order']['id']}", headers=admin_headers()).get_json()["data"]
    rider_before = client.get(f"/api/riders/{s['rider']['id']}",
                              headers=rider_headers(s["rider"]["id"])).get_json()["data"]
    rest_before = client.get(f"/api/restaurants/{s['restaurant']['id']}",
                             headers=admin_headers()).get_json()["data"]

    client.post(f"/api/orders/{s['order']['id']}/accept",
                headers=restaurant_headers(s["restaurant"]["id"]))
    client.post(f"/api/orders/{s['order']['id']}/start-preparing",
                headers=restaurant_headers(s["restaurant"]["id"]))

    assignment = None
    for a in store.assignments.values():
        if a["order_id"] == s["order"]["id"] and a["status"] == "OFFERED":
            assignment = a
            break

    client.post(f"/api/assignments/{assignment['id']}/accept",
                headers=rider_headers(s["rider"]["id"]))
    client.post(f"/api/orders/{s['order']['id']}/ready",
                headers=restaurant_headers(s["restaurant"]["id"]))
    client.post(f"/api/assignments/{assignment['id']}/pickup",
                headers=rider_headers(s["rider"]["id"]))

    rider_pre_deliver = client.get(f"/api/riders/{s['rider']['id']}",
                                    headers=rider_headers(s["rider"]["id"])).get_json()["data"]
    rest_pre_deliver = client.get(f"/api/restaurants/{s['restaurant']['id']}",
                                   headers=admin_headers()).get_json()["data"]

    client.post(f"/api/assignments/{assignment['id']}/deliver",
                headers=rider_headers(s["rider"]["id"]))

    rider_after = client.get(f"/api/riders/{s['rider']['id']}",
                             headers=rider_headers(s["rider"]["id"])).get_json()["data"]
    rest_after = client.get(f"/api/restaurants/{s['restaurant']['id']}",
                            headers=admin_headers()).get_json()["data"]

    assert rider_after["version"] == rider_pre_deliver["version"] + 1
    assert rest_after["version"] == rest_pre_deliver["version"] + 1


def test_delivery_rider_returns_to_available(client):
    s = setup_full_order(client)
    full_delivery(client, s)

    rider = client.get(f"/api/riders/{s['rider']['id']}",
                       headers=rider_headers(s["rider"]["id"])).get_json()["data"]
    assert rider["status"] == "AVAILABLE"


def test_delivery_restaurant_settlement(client):
    s = setup_full_order(client)
    full_delivery(client, s)

    rest = client.get(f"/api/restaurants/{s['restaurant']['id']}",
                      headers=admin_headers()).get_json()["data"]
    order = client.get(f"/api/orders/{s['order']['id']}",
                       headers=admin_headers()).get_json()["data"]
    expected = order["subtotal_cents"] - order["final_commission_cents"]
    assert rest["pending_settlement_cents"] == expected


def test_delivery_payment_captured(client):
    s = setup_full_order(client)
    full_delivery(client, s)

    order = client.get(f"/api/orders/{s['order']['id']}",
                       headers=admin_headers()).get_json()["data"]
    assert order["payment_status"] == "CAPTURED"


def test_delivery_zero_distance(client):
    from services.computations import compute_delivery_fee
    fee = compute_delivery_fee(0.0, False)
    assert fee == 300  # base only, 0 bands


def test_delivery_rider_wallet_credited(client):
    s = setup_full_order(client)
    full_delivery(client, s)

    rider = client.get(f"/api/riders/{s['rider']['id']}",
                       headers=rider_headers(s["rider"]["id"])).get_json()["data"]
    order = client.get(f"/api/orders/{s['order']['id']}",
                       headers=admin_headers()).get_json()["data"]
    assert rider["wallet_balance_cents"] == order["final_delivery_fee_cents"]


def test_cancel_by_cs(client):
    s = setup_full_order(client)
    resp = client.post(f"/api/orders/{s['order']['id']}/cancel", headers=cs_headers())
    assert resp.status_code == 200
    assert resp.get_json()["data"]["status"] == "CANCELLED"


def test_order_not_found_returns_err(client):
    resp = client.post("/api/orders/nonexistent/accept", headers=restaurant_headers("r1"))
    assert resp.status_code == 404


def test_dispatch_manual(client):
    s = setup_full_order(client)
    client.post(f"/api/orders/{s['order']['id']}/accept",
                headers=restaurant_headers(s["restaurant"]["id"]))
    client.post(f"/api/orders/{s['order']['id']}/start-preparing",
                headers=restaurant_headers(s["restaurant"]["id"]))

    for a in list(store.assignments.values()):
        if a["order_id"] == s["order"]["id"] and a["status"] == "OFFERED":
            a["status"] = "REJECTED"

    r2 = create_rider(client, name="R2", phone="555-2222")
    client.post(f"/api/riders/{r2['id']}/go-online", headers=rider_headers(r2["id"]))

    resp = client.post(f"/api/orders/{s['order']['id']}/dispatch", headers=admin_headers())
    assert resp.status_code == 201
    assert resp.get_json()["data"]["status"] == "OFFERED"
