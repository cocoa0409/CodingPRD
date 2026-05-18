import pytest
from tests.conftest import (
    admin_headers, customer_headers, restaurant_headers, rider_headers, cs_headers,
    create_restaurant, approve_restaurant, create_menu_item, create_customer,
    create_rider, setup_full_order,
)


def test_place_order(client):
    s = setup_full_order(client)
    order = s["order"]
    assert order["status"] == "PLACED"
    assert order["payment_status"] == "AUTHORIZED"
    assert order["subtotal_cents"] == 1000
    assert order["provisional_delivery_fee_cents"] > 0
    assert order["provisional_commission_cents"] > 0
    assert order["is_peak"] is not None
    assert order["distance_km"] is not None
    assert order["final_delivery_fee_cents"] is None
    assert order["final_commission_cents"] is None
    assert order["version"] == 1


def test_place_order_empty_items(client):
    r = create_restaurant(client)
    approve_restaurant(client, r["id"])
    c = create_customer(client)
    resp = client.post("/api/orders", json={
        "customer_id": c["id"], "restaurant_id": r["id"], "items": [],
    }, headers=customer_headers(c["id"]))
    assert resp.status_code == 422
    assert resp.get_json()["data"]["error_id"] == "ERR_ORDER_INVALID"


def test_place_order_below_minimum(client):
    r = create_restaurant(client)
    approve_restaurant(client, r["id"])
    mi = create_menu_item(client, r["id"], price_cents=10)
    c = create_customer(client)
    resp = client.post("/api/orders", json={
        "customer_id": c["id"], "restaurant_id": r["id"],
        "items": [{"menu_item_id": mi["id"], "quantity": 1}],
    }, headers=customer_headers(c["id"]))
    assert resp.status_code == 422
    assert resp.get_json()["data"]["error_id"] == "ERR_ORDER_INVALID"


def test_place_order_inactive_restaurant(client):
    r = create_restaurant(client)
    mi = create_menu_item(client, r["id"], price_cents=1000)
    c = create_customer(client)
    resp = client.post("/api/orders", json={
        "customer_id": c["id"], "restaurant_id": r["id"],
        "items": [{"menu_item_id": mi["id"], "quantity": 1}],
    }, headers=customer_headers(c["id"]))
    assert resp.status_code == 422
    assert resp.get_json()["data"]["error_id"] == "ERR_RESTAURANT_UNAVAILABLE"


def test_place_order_unlisted_item(client):
    r = create_restaurant(client)
    approve_restaurant(client, r["id"])
    mi = create_menu_item(client, r["id"], price_cents=1000)
    client.patch(f"/api/menu-items/{mi['id']}", json={"is_listed": False},
                 headers=restaurant_headers(r["id"]))
    c = create_customer(client)
    resp = client.post("/api/orders", json={
        "customer_id": c["id"], "restaurant_id": r["id"],
        "items": [{"menu_item_id": mi["id"], "quantity": 1}],
    }, headers=customer_headers(c["id"]))
    assert resp.status_code == 422


def test_place_order_wrong_customer(client):
    s = setup_full_order(client)
    r2 = create_restaurant(client, name="R2")
    approve_restaurant(client, r2["id"])
    mi2 = create_menu_item(client, r2["id"])
    resp = client.post("/api/orders", json={
        "customer_id": s["customer"]["id"], "restaurant_id": r2["id"],
        "items": [{"menu_item_id": mi2["id"], "quantity": 1}],
    }, headers=customer_headers("wrong-customer"))
    assert resp.status_code == 403


def test_place_order_item_wrong_restaurant(client):
    r1 = create_restaurant(client, name="R1")
    approve_restaurant(client, r1["id"])
    r2 = create_restaurant(client, name="R2")
    approve_restaurant(client, r2["id"])
    mi = create_menu_item(client, r1["id"])
    c = create_customer(client)
    resp = client.post("/api/orders", json={
        "customer_id": c["id"], "restaurant_id": r2["id"],
        "items": [{"menu_item_id": mi["id"], "quantity": 1}],
    }, headers=customer_headers(c["id"]))
    assert resp.status_code == 422


def test_get_order(client):
    s = setup_full_order(client)
    resp = client.get(f"/api/orders/{s['order']['id']}",
                      headers=customer_headers(s["customer"]["id"]))
    assert resp.status_code == 200


def test_get_order_not_found(client):
    resp = client.get("/api/orders/nonexistent", headers=admin_headers())
    assert resp.status_code == 404


def test_list_orders(client):
    s = setup_full_order(client)
    resp = client.get("/api/orders", headers=admin_headers())
    assert resp.status_code == 200
    assert len(resp.get_json()["data"]) == 1


def test_list_orders_with_filters(client):
    s = setup_full_order(client)
    resp = client.get(f"/api/orders?customer_id={s['customer']['id']}", headers=admin_headers())
    assert len(resp.get_json()["data"]) == 1
    resp = client.get(f"/api/orders?status=PLACED", headers=admin_headers())
    assert len(resp.get_json()["data"]) == 1
    resp = client.get(f"/api/orders?status=DELIVERED", headers=admin_headers())
    assert len(resp.get_json()["data"]) == 0


def test_accept_order(client):
    s = setup_full_order(client)
    resp = client.post(f"/api/orders/{s['order']['id']}/accept",
                       headers=restaurant_headers(s["restaurant"]["id"]))
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["status"] == "RESTAURANT_ACCEPTED"


def test_accept_order_wrong_restaurant(client):
    s = setup_full_order(client)
    resp = client.post(f"/api/orders/{s['order']['id']}/accept",
                       headers=restaurant_headers("wrong-restaurant"))
    assert resp.status_code == 403


def test_accept_order_not_placed(client):
    s = setup_full_order(client)
    client.post(f"/api/orders/{s['order']['id']}/accept",
                headers=restaurant_headers(s["restaurant"]["id"]))
    resp = client.post(f"/api/orders/{s['order']['id']}/accept",
                       headers=restaurant_headers(s["restaurant"]["id"]))
    assert resp.status_code == 409


def test_cancel_order_by_customer(client):
    s = setup_full_order(client)
    resp = client.post(f"/api/orders/{s['order']['id']}/cancel",
                       headers=customer_headers(s["customer"]["id"]))
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["status"] == "CANCELLED"
    assert data["payment_status"] == "VOIDED"


def test_cancel_order_by_restaurant(client):
    s = setup_full_order(client)
    resp = client.post(f"/api/orders/{s['order']['id']}/cancel",
                       headers=restaurant_headers(s["restaurant"]["id"]))
    assert resp.status_code == 200
    assert resp.get_json()["data"]["status"] == "CANCELLED"


def test_cancel_order_not_placed(client):
    s = setup_full_order(client)
    client.post(f"/api/orders/{s['order']['id']}/accept",
                headers=restaurant_headers(s["restaurant"]["id"]))
    resp = client.post(f"/api/orders/{s['order']['id']}/cancel",
                       headers=customer_headers(s["customer"]["id"]))
    assert resp.status_code == 409


def test_start_preparing(client):
    s = setup_full_order(client)
    client.post(f"/api/orders/{s['order']['id']}/accept",
                headers=restaurant_headers(s["restaurant"]["id"]))
    resp = client.post(f"/api/orders/{s['order']['id']}/start-preparing",
                       headers=restaurant_headers(s["restaurant"]["id"]))
    assert resp.status_code == 200
    assert resp.get_json()["data"]["status"] == "PREPARING"


def test_start_preparing_not_accepted(client):
    s = setup_full_order(client)
    resp = client.post(f"/api/orders/{s['order']['id']}/start-preparing",
                       headers=restaurant_headers(s["restaurant"]["id"]))
    assert resp.status_code == 409


def test_ready_for_pickup(client):
    s = setup_full_order(client)
    client.post(f"/api/orders/{s['order']['id']}/accept",
                headers=restaurant_headers(s["restaurant"]["id"]))
    client.post(f"/api/orders/{s['order']['id']}/start-preparing",
                headers=restaurant_headers(s["restaurant"]["id"]))

    from store import store
    assignments = [a for a in store.assignments.values() if a["order_id"] == s["order"]["id"]]
    assert len(assignments) == 1
    assignment = assignments[0]

    client.post(f"/api/assignments/{assignment['id']}/accept",
                headers=rider_headers(s["rider"]["id"]))

    resp = client.post(f"/api/orders/{s['order']['id']}/ready",
                       headers=restaurant_headers(s["restaurant"]["id"]))
    assert resp.status_code == 200
    assert resp.get_json()["data"]["status"] == "READY_FOR_PICKUP"


def test_ready_without_rider(client):
    s = setup_full_order(client)
    client.post(f"/api/orders/{s['order']['id']}/accept",
                headers=restaurant_headers(s["restaurant"]["id"]))
    client.post(f"/api/orders/{s['order']['id']}/start-preparing",
                headers=restaurant_headers(s["restaurant"]["id"]))

    from store import store
    assignments = [a for a in store.assignments.values() if a["order_id"] == s["order"]["id"]]
    for a in assignments:
        a["status"] = "REJECTED"

    resp = client.post(f"/api/orders/{s['order']['id']}/ready",
                       headers=restaurant_headers(s["restaurant"]["id"]))
    assert resp.status_code == 409


def test_order_commission_tiered(client):
    s = setup_full_order(client, item_price=25000, item_quantity=1)
    order = s["order"]
    from services.computations import compute_tiered_commission
    expected = compute_tiered_commission(25000)
    assert order["provisional_commission_cents"] == expected


def test_order_delivery_fee_calculation(client):
    s = setup_full_order(client, restaurant_lat=40.7128, restaurant_lng=-74.0060,
                         customer_lat=40.7128, customer_lng=-74.0060, item_price=1000)
    fee = s["order"]["provisional_delivery_fee_cents"]
    assert fee >= 300


def test_credit_drawdown_at_placement(client):
    """§3.4: credit_balance_cents is drawn down at order placement."""
    from store import store
    r = create_restaurant(client)
    approve_restaurant(client, r["id"])
    mi = create_menu_item(client, r["id"], price_cents=1000)
    c = create_customer(client)

    store.customers[c["id"]]["credit_balance_cents"] = 500
    rider = create_rider(client)
    client.post(f"/api/riders/{rider['id']}/go-online", headers=rider_headers(rider["id"]))

    resp = client.post("/api/orders", json={
        "customer_id": c["id"], "restaurant_id": r["id"],
        "items": [{"menu_item_id": mi["id"], "quantity": 1}],
    }, headers=customer_headers(c["id"]))
    assert resp.status_code == 201

    customer = client.get(f"/api/customers/{c['id']}",
                          headers=admin_headers()).get_json()["data"]
    assert customer["credit_balance_cents"] == 0


def test_credit_drawdown_partial(client):
    """When credit < order total, only available credit is drawn down."""
    from store import store
    r = create_restaurant(client)
    approve_restaurant(client, r["id"])
    mi = create_menu_item(client, r["id"], price_cents=5000)
    c = create_customer(client)

    store.customers[c["id"]]["credit_balance_cents"] = 200
    rider = create_rider(client)
    client.post(f"/api/riders/{rider['id']}/go-online", headers=rider_headers(rider["id"]))

    resp = client.post("/api/orders", json={
        "customer_id": c["id"], "restaurant_id": r["id"],
        "items": [{"menu_item_id": mi["id"], "quantity": 1}],
    }, headers=customer_headers(c["id"]))
    assert resp.status_code == 201

    customer = client.get(f"/api/customers/{c['id']}",
                          headers=admin_headers()).get_json()["data"]
    assert customer["credit_balance_cents"] == 0


def test_credit_drawdown_zero_credit(client):
    """When credit is 0, no drawdown happens and customer is not touched."""
    s = setup_full_order(client)
    from store import store
    customer = store.customers[s["customer"]["id"]]
    assert customer["credit_balance_cents"] == 0
    assert customer["version"] == 1


def test_list_orders_customer_sees_only_own(client):
    """Customer only sees their own orders in list endpoint."""
    s1 = setup_full_order(client)
    c2 = create_customer(client, name="C2", phone="555-9998")

    resp = client.get("/api/orders", headers=customer_headers(c2["id"]))
    assert resp.status_code == 200
    assert len(resp.get_json()["data"]) == 0

    resp = client.get("/api/orders", headers=customer_headers(s1["customer"]["id"]))
    assert len(resp.get_json()["data"]) == 1


def test_list_orders_restaurant_sees_only_own(client):
    """Restaurant only sees orders for their restaurant."""
    s1 = setup_full_order(client)
    r2 = create_restaurant(client, name="R2")

    resp = client.get("/api/orders", headers=restaurant_headers(r2["id"]))
    assert resp.status_code == 200
    assert len(resp.get_json()["data"]) == 0

    resp = client.get("/api/orders", headers=restaurant_headers(s1["restaurant"]["id"]))
    assert len(resp.get_json()["data"]) == 1
