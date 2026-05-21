from . import client
from .fixtures import make_restaurant, make_menu_item, make_customer, make_rider, place_order


def test_restaurant_accept_to_preparing():
    rest = make_restaurant()
    item = make_menu_item(rest["id"], price_cents=2000)
    c = make_customer()
    rider = make_rider(online=True)  # needed for dispatch on start-preparing
    o = place_order(c["id"], rest["id"], [{"menu_item_id": item["id"], "quantity": 1}])

    r = client.post(f"/api/orders/{o['id']}/accept",
                    role="Restaurant", uid=rest["id"], json={})
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "RESTAURANT_ACCEPTED"

    p = client.post(f"/api/orders/{o['id']}/start-preparing",
                    role="Restaurant", uid=rest["id"], json={})
    assert p.status_code == 200
    assert p.json()["data"]["status"] == "PREPARING"


def test_restaurant_ready_blocked_without_accepted_rider():
    rest = make_restaurant()
    item = make_menu_item(rest["id"], price_cents=2000)
    c = make_customer()
    # no rider exists, so start-preparing won't create an OFFERED assignment that resolves to ACCEPTED
    rider = make_rider(online=True)
    o = place_order(c["id"], rest["id"], [{"menu_item_id": item["id"], "quantity": 1}])
    client.post(f"/api/orders/{o['id']}/accept", role="Restaurant", uid=rest["id"], json={})
    client.post(f"/api/orders/{o['id']}/start-preparing", role="Restaurant", uid=rest["id"], json={})
    # rider only OFFERED, not ACCEPTED
    r = client.post(f"/api/orders/{o['id']}/ready", role="Restaurant", uid=rest["id"], json={})
    assert r.status_code == 409, r.text
    assert r.json()["data"]["error_id"] == "ERR_INVALID_STATE"


def test_cancel_placed_order():
    rest = make_restaurant()
    item = make_menu_item(rest["id"], price_cents=2000)
    c = make_customer()
    o = place_order(c["id"], rest["id"], [{"menu_item_id": item["id"], "quantity": 1}])
    r = client.post(f"/api/orders/{o['id']}/cancel", role="Customer", uid=c["id"], json={})
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["status"] == "CANCELLED"
    assert d["payment_status"] == "VOIDED"


def test_cannot_cancel_beyond_placed():
    rest = make_restaurant()
    item = make_menu_item(rest["id"], price_cents=2000)
    c = make_customer()
    o = place_order(c["id"], rest["id"], [{"menu_item_id": item["id"], "quantity": 1}])
    client.post(f"/api/orders/{o['id']}/accept", role="Restaurant", uid=rest["id"], json={})
    r = client.post(f"/api/orders/{o['id']}/cancel", role="Customer", uid=c["id"], json={})
    assert r.status_code == 409


def test_suspend_restaurant_cancels_placed_orders():
    rest = make_restaurant()
    item = make_menu_item(rest["id"], price_cents=2000)
    c = make_customer()
    o = place_order(c["id"], rest["id"], [{"menu_item_id": item["id"], "quantity": 1}])
    s = client.post(f"/api/restaurants/{rest['id']}/suspend",
                    role="PlatformAdmin", uid="admin", json={})
    assert s.status_code == 200
    o_after = client.get(f"/api/orders/{o['id']}", role="PlatformAdmin", uid="admin").json()["data"]
    assert o_after["status"] == "CANCELLED"
    assert o_after["payment_status"] == "VOIDED"


def test_dispatch_endpoint_creates_assignment():
    rest = make_restaurant()
    item = make_menu_item(rest["id"], price_cents=2000)
    c = make_customer()
    rider = make_rider(online=True)
    o = place_order(c["id"], rest["id"], [{"menu_item_id": item["id"], "quantity": 1}])
    client.post(f"/api/orders/{o['id']}/accept", role="Restaurant", uid=rest["id"], json={})
    r = client.post(f"/api/orders/{o['id']}/dispatch", role="PlatformAdmin", uid="admin", json={})
    assert r.status_code == 201, r.text
    assert r.json()["data"]["status"] == "OFFERED"


def test_dispatch_no_eligible_rider():
    rest = make_restaurant()
    item = make_menu_item(rest["id"], price_cents=2000)
    c = make_customer()
    o = place_order(c["id"], rest["id"], [{"menu_item_id": item["id"], "quantity": 1}])
    client.post(f"/api/orders/{o['id']}/accept", role="Restaurant", uid=rest["id"], json={})
    r = client.post(f"/api/orders/{o['id']}/dispatch", role="PlatformAdmin", uid="admin", json={})
    assert r.status_code == 409
    assert r.json()["data"]["error_id"] == "ERR_INVALID_STATE"
