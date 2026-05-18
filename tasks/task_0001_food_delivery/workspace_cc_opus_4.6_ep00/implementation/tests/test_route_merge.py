import pytest
from tests.conftest import (
    admin_headers, customer_headers, restaurant_headers, rider_headers,
    create_restaurant, approve_restaurant, create_menu_item, create_customer,
    create_rider, setup_full_order,
)
from store import store
import math


def test_route_merge_on_accept(client):
    """Two orders from nearby restaurants get merged when the same rider accepts both."""
    r1 = create_restaurant(client, name="R1", lat=40.71280, lng=-74.00600)
    approve_restaurant(client, r1["id"])
    mi1 = create_menu_item(client, r1["id"], name="Burger", price_cents=1000)

    r2 = create_restaurant(client, name="R2", lat=40.71281, lng=-74.00601)
    approve_restaurant(client, r2["id"])
    mi2 = create_menu_item(client, r2["id"], name="Pizza", price_cents=1500)

    c = create_customer(client, lat=40.758, lng=-73.985)
    rider = create_rider(client)
    client.post(f"/api/riders/{rider['id']}/go-online", headers=rider_headers(rider["id"]))

    resp1 = client.post("/api/orders", json={
        "customer_id": c["id"], "restaurant_id": r1["id"],
        "items": [{"menu_item_id": mi1["id"], "quantity": 1}],
    }, headers=customer_headers(c["id"]))
    order1 = resp1.get_json()["data"]

    resp2 = client.post("/api/orders", json={
        "customer_id": c["id"], "restaurant_id": r2["id"],
        "items": [{"menu_item_id": mi2["id"], "quantity": 1}],
    }, headers=customer_headers(c["id"]))
    order2 = resp2.get_json()["data"]

    # Accept and prepare both orders
    client.post(f"/api/orders/{order1['id']}/accept", headers=restaurant_headers(r1["id"]))
    client.post(f"/api/orders/{order1['id']}/start-preparing", headers=restaurant_headers(r1["id"]))
    a1 = next(a for a in store.assignments.values() if a["order_id"] == order1["id"] and a["status"] == "OFFERED")
    client.post(f"/api/assignments/{a1['id']}/accept", headers=rider_headers(rider["id"]))

    client.post(f"/api/orders/{order2['id']}/accept", headers=restaurant_headers(r2["id"]))
    client.post(f"/api/orders/{order2['id']}/start-preparing", headers=restaurant_headers(r2["id"]))
    a2 = next(a for a in store.assignments.values() if a["order_id"] == order2["id"] and a["status"] == "OFFERED")
    client.post(f"/api/assignments/{a2['id']}/accept", headers=rider_headers(rider["id"]))

    a2_updated = store.assignments[a2["id"]]
    assert a2_updated.get("route_group_id") is not None

    rg = store.route_groups.get(a2_updated["route_group_id"])
    assert rg is not None
    assert rg["status"] == "ACTIVE"
    assert len(rg["assignment_ids"]) == 2


def test_route_merge_delivery_discount(client):
    """Merged route deliveries get a 25% fee discount."""
    r1 = create_restaurant(client, name="R1", lat=40.71280, lng=-74.00600)
    approve_restaurant(client, r1["id"])
    mi1 = create_menu_item(client, r1["id"], name="Burger", price_cents=1000)

    r2 = create_restaurant(client, name="R2", lat=40.71281, lng=-74.00601)
    approve_restaurant(client, r2["id"])
    mi2 = create_menu_item(client, r2["id"], name="Pizza", price_cents=1500)

    c = create_customer(client, lat=40.758, lng=-73.985)
    rider = create_rider(client)
    client.post(f"/api/riders/{rider['id']}/go-online", headers=rider_headers(rider["id"]))

    resp1 = client.post("/api/orders", json={
        "customer_id": c["id"], "restaurant_id": r1["id"],
        "items": [{"menu_item_id": mi1["id"], "quantity": 1}],
    }, headers=customer_headers(c["id"]))
    order1 = resp1.get_json()["data"]

    resp2 = client.post("/api/orders", json={
        "customer_id": c["id"], "restaurant_id": r2["id"],
        "items": [{"menu_item_id": mi2["id"], "quantity": 1}],
    }, headers=customer_headers(c["id"]))
    order2 = resp2.get_json()["data"]

    client.post(f"/api/orders/{order1['id']}/accept", headers=restaurant_headers(r1["id"]))
    client.post(f"/api/orders/{order1['id']}/start-preparing", headers=restaurant_headers(r1["id"]))
    a1 = next(a for a in store.assignments.values() if a["order_id"] == order1["id"] and a["status"] == "OFFERED")
    client.post(f"/api/assignments/{a1['id']}/accept", headers=rider_headers(rider["id"]))

    client.post(f"/api/orders/{order2['id']}/accept", headers=restaurant_headers(r2["id"]))
    client.post(f"/api/orders/{order2['id']}/start-preparing", headers=restaurant_headers(r2["id"]))
    a2 = next(a for a in store.assignments.values() if a["order_id"] == order2["id"] and a["status"] == "OFFERED")
    client.post(f"/api/assignments/{a2['id']}/accept", headers=rider_headers(rider["id"]))

    # Deliver first order
    client.post(f"/api/orders/{order1['id']}/ready", headers=restaurant_headers(r1["id"]))
    client.post(f"/api/assignments/{a1['id']}/pickup", headers=rider_headers(rider["id"]))
    resp = client.post(f"/api/assignments/{a1['id']}/deliver", headers=rider_headers(rider["id"]))
    a1_data = resp.get_json()["data"]

    from services.computations import compute_delivery_fee
    solo_fee = compute_delivery_fee(order1["distance_km"], order1["is_peak"])
    discount = int(math.floor(solo_fee * 0.25))
    expected_fee = solo_fee - discount
    assert a1_data["final_delivery_fee_cents"] == expected_fee

    rider_data = client.get(f"/api/riders/{rider['id']}",
                            headers=rider_headers(rider["id"])).get_json()["data"]
    assert rider_data["status"] == "ON_DELIVERY"

    # Deliver second order
    client.post(f"/api/orders/{order2['id']}/ready", headers=restaurant_headers(r2["id"]))
    client.post(f"/api/assignments/{a2['id']}/pickup", headers=rider_headers(rider["id"]))
    client.post(f"/api/assignments/{a2['id']}/deliver", headers=rider_headers(rider["id"]))

    rider_data = client.get(f"/api/riders/{rider['id']}",
                            headers=rider_headers(rider["id"])).get_json()["data"]
    assert rider_data["status"] == "AVAILABLE"

    rg_id = store.assignments[a2["id"]]["route_group_id"]
    rg = store.route_groups[rg_id]
    assert rg["status"] == "COMPLETED"


def test_no_merge_far_restaurants(client):
    """Restaurants > 500m apart don't trigger route merge."""
    r1 = create_restaurant(client, name="R1", lat=40.71280, lng=-74.00600)
    approve_restaurant(client, r1["id"])
    mi1 = create_menu_item(client, r1["id"], name="Burger", price_cents=1000)

    r2 = create_restaurant(client, name="R2", lat=40.72000, lng=-74.01000)
    approve_restaurant(client, r2["id"])
    mi2 = create_menu_item(client, r2["id"], name="Pizza", price_cents=1500)

    c = create_customer(client, lat=40.758, lng=-73.985)
    rider = create_rider(client)
    client.post(f"/api/riders/{rider['id']}/go-online", headers=rider_headers(rider["id"]))

    resp1 = client.post("/api/orders", json={
        "customer_id": c["id"], "restaurant_id": r1["id"],
        "items": [{"menu_item_id": mi1["id"], "quantity": 1}],
    }, headers=customer_headers(c["id"]))
    order1 = resp1.get_json()["data"]

    resp2 = client.post("/api/orders", json={
        "customer_id": c["id"], "restaurant_id": r2["id"],
        "items": [{"menu_item_id": mi2["id"], "quantity": 1}],
    }, headers=customer_headers(c["id"]))
    order2 = resp2.get_json()["data"]

    client.post(f"/api/orders/{order1['id']}/accept", headers=restaurant_headers(r1["id"]))
    client.post(f"/api/orders/{order1['id']}/start-preparing", headers=restaurant_headers(r1["id"]))
    a1 = next(a for a in store.assignments.values() if a["order_id"] == order1["id"] and a["status"] == "OFFERED")
    client.post(f"/api/assignments/{a1['id']}/accept", headers=rider_headers(rider["id"]))

    client.post(f"/api/orders/{order2['id']}/accept", headers=restaurant_headers(r2["id"]))
    client.post(f"/api/orders/{order2['id']}/start-preparing", headers=restaurant_headers(r2["id"]))
    a2 = next(a for a in store.assignments.values() if a["order_id"] == order2["id"] and a["status"] == "OFFERED")
    client.post(f"/api/assignments/{a2['id']}/accept", headers=rider_headers(rider["id"]))

    a2_data = store.assignments[a2["id"]]
    assert a2_data.get("route_group_id") is None
    assert len(store.route_groups) == 0


def test_rider_goes_offline_blocked_by_active_assignment(client):
    """Rider can't go offline with active assignment."""
    s = setup_full_order(client)
    client.post(f"/api/orders/{s['order']['id']}/accept",
                headers=restaurant_headers(s["restaurant"]["id"]))
    client.post(f"/api/orders/{s['order']['id']}/start-preparing",
                headers=restaurant_headers(s["restaurant"]["id"]))

    a = next(a for a in store.assignments.values()
             if a["order_id"] == s["order"]["id"] and a["status"] == "OFFERED")
    client.post(f"/api/assignments/{a['id']}/accept", headers=rider_headers(s["rider"]["id"]))

    resp = client.post(f"/api/riders/{s['rider']['id']}/go-offline",
                       headers=rider_headers(s["rider"]["id"]))
    assert resp.status_code == 409


def test_pagination_invalid_limit(client):
    resp = client.get("/api/restaurants?limit=0", headers=admin_headers())
    assert resp.status_code == 422

    resp = client.get("/api/restaurants?limit=101", headers=admin_headers())
    assert resp.status_code == 422

    resp = client.get("/api/restaurants?offset=-1", headers=admin_headers())
    assert resp.status_code == 422
