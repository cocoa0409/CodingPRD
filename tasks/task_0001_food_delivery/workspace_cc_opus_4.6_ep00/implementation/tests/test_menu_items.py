import pytest
from tests.conftest import (
    admin_headers, restaurant_headers, customer_headers,
    create_restaurant, approve_restaurant, create_menu_item,
)


def test_create_menu_item(client):
    r = create_restaurant(client)
    resp = client.post(f"/api/restaurants/{r['id']}/menu-items", json={
        "name": "Burger", "price_cents": 1500,
    }, headers=restaurant_headers(r["id"]))
    assert resp.status_code == 201
    data = resp.get_json()["data"]
    assert data["name"] == "Burger"
    assert data["price_cents"] == 1500
    assert data["is_listed"] is True
    assert data["restaurant_id"] == r["id"]
    assert data["version"] == 1


def test_create_menu_item_admin(client):
    r = create_restaurant(client)
    resp = client.post(f"/api/restaurants/{r['id']}/menu-items", json={
        "name": "Salad", "price_cents": 800,
    }, headers=admin_headers())
    assert resp.status_code == 201


def test_create_menu_item_other_restaurant_forbidden(client):
    r = create_restaurant(client)
    resp = client.post(f"/api/restaurants/{r['id']}/menu-items", json={
        "name": "Fries", "price_cents": 500,
    }, headers=restaurant_headers("other-restaurant"))
    assert resp.status_code == 403


def test_create_menu_item_restaurant_not_found(client):
    resp = client.post("/api/restaurants/nonexistent/menu-items", json={
        "name": "Fries", "price_cents": 500,
    }, headers=admin_headers())
    assert resp.status_code == 404


def test_create_menu_item_invalid_price(client):
    r = create_restaurant(client)
    resp = client.post(f"/api/restaurants/{r['id']}/menu-items", json={
        "name": "Cheap", "price_cents": 0,
    }, headers=restaurant_headers(r["id"]))
    assert resp.status_code == 422

    resp = client.post(f"/api/restaurants/{r['id']}/menu-items", json={
        "name": "Expensive", "price_cents": 1000001,
    }, headers=restaurant_headers(r["id"]))
    assert resp.status_code == 422


def test_update_menu_item(client):
    r = create_restaurant(client)
    mi = create_menu_item(client, r["id"])
    resp = client.patch(f"/api/menu-items/{mi['id']}", json={
        "price_cents": 2000, "is_listed": False,
    }, headers=restaurant_headers(r["id"]))
    assert resp.status_code == 200
    data = resp.get_json()["data"]
    assert data["price_cents"] == 2000
    assert data["is_listed"] is False
    assert data["version"] == 2


def test_update_menu_item_version_conflict(client):
    r = create_restaurant(client)
    mi = create_menu_item(client, r["id"])
    resp = client.patch(f"/api/menu-items/{mi['id']}", json={
        "price_cents": 2000, "version": 999,
    }, headers=restaurant_headers(r["id"]))
    assert resp.status_code == 409


def test_update_menu_item_other_restaurant(client):
    r = create_restaurant(client)
    mi = create_menu_item(client, r["id"])
    resp = client.patch(f"/api/menu-items/{mi['id']}", json={
        "price_cents": 2000,
    }, headers=restaurant_headers("other-restaurant"))
    assert resp.status_code == 403


def test_list_menu_items(client):
    r = create_restaurant(client)
    create_menu_item(client, r["id"], name="Burger")
    create_menu_item(client, r["id"], name="Fries")
    resp = client.get(f"/api/restaurants/{r['id']}/menu-items", headers=admin_headers())
    assert resp.status_code == 200
    assert len(resp.get_json()["data"]) == 2


def test_list_menu_items_filter_listed(client):
    r = create_restaurant(client)
    mi1 = create_menu_item(client, r["id"], name="Listed")
    mi2 = create_menu_item(client, r["id"], name="Unlisted")
    client.patch(f"/api/menu-items/{mi2['id']}", json={"is_listed": False},
                 headers=restaurant_headers(r["id"]))
    resp = client.get(f"/api/restaurants/{r['id']}/menu-items?is_listed=true",
                      headers=admin_headers())
    assert len(resp.get_json()["data"]) == 1


def test_list_menu_items_restaurant_not_found(client):
    resp = client.get("/api/restaurants/nonexistent/menu-items", headers=admin_headers())
    assert resp.status_code == 404
