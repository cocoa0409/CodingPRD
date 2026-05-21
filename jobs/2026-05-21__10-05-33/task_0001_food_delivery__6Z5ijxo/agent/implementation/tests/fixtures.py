"""Reusable fixture builders. Each builder returns the created resource."""
from . import client


def make_restaurant(name="Pizza Place", lat=40.7128, lng=-74.0060,
                    address="123 Main St", commission_rate_override=None,
                    activate=True):
    body = {"name": name, "lat": lat, "lng": lng, "address": address}
    if commission_rate_override is not None:
        body["commission_rate_override"] = commission_rate_override
    r = client.post("/api/restaurants", role="PlatformAdmin", uid=client.ADMIN_ID, json=body)
    assert r.status_code == 201, r.text
    rest = r.json()["data"]
    if activate:
        ap = client.post(f"/api/restaurants/{rest['id']}/approve",
                         role="PlatformAdmin", uid=client.ADMIN_ID, json={})
        assert ap.status_code == 200, ap.text
        rest = ap.json()["data"]
    return rest


def make_menu_item(restaurant_id, name="Margherita", price_cents=1500, is_listed=True,
                   restaurant_uid=None):
    uid = restaurant_uid or restaurant_id
    role = "Restaurant" if restaurant_uid else "PlatformAdmin"
    if restaurant_uid is None:
        uid = client.ADMIN_ID
    r = client.post(f"/api/restaurants/{restaurant_id}/menu-items",
                    role=role, uid=uid,
                    json={"name": name, "price_cents": price_cents, "is_listed": is_listed})
    assert r.status_code == 201, r.text
    return r.json()["data"]


def make_customer(name="Alice", phone=None, address="221B Baker St",
                  lat=40.7138, lng=-74.0040):
    import uuid as _uuid
    if phone is None:
        phone = "+1555" + str(_uuid.uuid4().int)[:7]
    r = client.post("/api/customers", role="PlatformAdmin", uid=client.ADMIN_ID,
                    json={"name": name, "phone": phone, "address": address,
                          "lat": lat, "lng": lng})
    assert r.status_code == 201, r.text
    return r.json()["data"]


def make_rider(name="Bob", phone=None, online=False):
    import uuid as _uuid
    if phone is None:
        phone = "+1555" + str(_uuid.uuid4().int)[:7]
    r = client.post("/api/riders", role="PlatformAdmin", uid=client.ADMIN_ID,
                    json={"name": name, "phone": phone})
    assert r.status_code == 201, r.text
    rider = r.json()["data"]
    if online:
        go = client.post(f"/api/riders/{rider['id']}/go-online",
                         role="Rider", uid=rider["id"], json={})
        assert go.status_code == 200, go.text
        rider = go.json()["data"]
    return rider


def place_order(customer_id, restaurant_id, items):
    r = client.post("/api/orders", role="Customer", uid=customer_id,
                    json={"customer_id": customer_id,
                          "restaurant_id": restaurant_id,
                          "items": items})
    assert r.status_code == 201, r.text
    return r.json()["data"]


def advance(seconds):
    r = client.post("/api/_clock/advance", role="PlatformAdmin", uid=client.ADMIN_ID,
                    json={"seconds": seconds})
    assert r.status_code == 200, r.text
    return r.json()["data"]
