import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from app import create_app
from store import store
from clock import clock


@pytest.fixture(autouse=True)
def reset_state():
    store.clear()
    clock.reset()
    yield
    store.clear()
    clock.reset()


@pytest.fixture
def app():
    app = create_app()
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def admin_headers(user_id="admin1"):
    return {"X-User-ID": user_id, "X-User-Role": "PlatformAdmin"}


def customer_headers(user_id):
    return {"X-User-ID": user_id, "X-User-Role": "Customer"}


def restaurant_headers(user_id):
    return {"X-User-ID": user_id, "X-User-Role": "Restaurant"}


def rider_headers(user_id):
    return {"X-User-ID": user_id, "X-User-Role": "Rider"}


def cs_headers(user_id="cs1"):
    return {"X-User-ID": user_id, "X-User-Role": "CustomerService"}


def create_restaurant(client, name="Test Restaurant", lat=40.7128, lng=-74.0060):
    resp = client.post("/api/restaurants", json={
        "name": name, "address": "123 Main St", "lat": lat, "lng": lng,
    }, headers=admin_headers())
    return resp.get_json()["data"]


def approve_restaurant(client, restaurant_id):
    resp = client.post(f"/api/restaurants/{restaurant_id}/approve", headers=admin_headers())
    return resp.get_json()["data"]


def create_menu_item(client, restaurant_id, name="Burger", price_cents=1000):
    resp = client.post(f"/api/restaurants/{restaurant_id}/menu-items", json={
        "name": name, "price_cents": price_cents,
    }, headers=restaurant_headers(restaurant_id))
    return resp.get_json()["data"]


def create_customer(client, name="John Doe", phone="555-0001", lat=40.7580, lng=-73.9855):
    resp = client.post("/api/customers", json={
        "name": name, "phone": phone, "address": "456 Oak Ave",
        "lat": lat, "lng": lng,
    }, headers=admin_headers())
    return resp.get_json()["data"]


def create_rider(client, name="Rider One", phone="555-1001"):
    resp = client.post("/api/riders", json={
        "name": name, "phone": phone,
    }, headers=admin_headers())
    return resp.get_json()["data"]


def setup_full_order(client, restaurant_lat=40.7128, restaurant_lng=-74.0060,
                     customer_lat=40.7580, customer_lng=-73.9855,
                     item_price=1000, item_quantity=1):
    r = create_restaurant(client, lat=restaurant_lat, lng=restaurant_lng)
    approve_restaurant(client, r["id"])
    mi = create_menu_item(client, r["id"], price_cents=item_price)
    c = create_customer(client, lat=customer_lat, lng=customer_lng)
    rider = create_rider(client)
    client.post(f"/api/riders/{rider['id']}/go-online", headers=rider_headers(rider["id"]))

    resp = client.post("/api/orders", json={
        "customer_id": c["id"], "restaurant_id": r["id"],
        "items": [{"menu_item_id": mi["id"], "quantity": item_quantity}],
    }, headers=customer_headers(c["id"]))
    order = resp.get_json()["data"]
    return {"restaurant": r, "menu_item": mi, "customer": c, "rider": rider, "order": order}
