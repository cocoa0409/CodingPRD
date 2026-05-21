from . import client
from .fixtures import make_restaurant, make_menu_item, make_customer, make_rider, place_order


def test_route_merge_attaches_when_pickups_within_500m():
    # Two restaurants ~250m apart
    rest_a = make_restaurant(name="A", lat=40.0000, lng=-74.0000)
    rest_b = make_restaurant(name="B", lat=40.0020, lng=-74.0000)  # ~222 m
    item_a = make_menu_item(rest_a["id"], price_cents=2000)
    item_b = make_menu_item(rest_b["id"], price_cents=2000)
    c = make_customer(lat=40.0500, lng=-74.0000)
    rider = make_rider(online=True)

    # Order 1
    o1 = place_order(c["id"], rest_a["id"], [{"menu_item_id": item_a["id"], "quantity": 1}])
    client.post(f"/api/orders/{o1['id']}/accept", role="Restaurant", uid=rest_a["id"], json={})
    d1 = client.post(f"/api/orders/{o1['id']}/dispatch", role="PlatformAdmin", uid="admin", json={})
    a1 = d1.json()["data"]
    client.post(f"/api/assignments/{a1['id']}/accept", role="Rider", uid=rider["id"], json={})
    # rider now ON_DELIVERY

    # Order 2 at restaurant B (within 500m of A's pickup)
    o2 = place_order(c["id"], rest_b["id"], [{"menu_item_id": item_b["id"], "quantity": 1}])
    client.post(f"/api/orders/{o2['id']}/accept", role="Restaurant", uid=rest_b["id"], json={})
    d2 = client.post(f"/api/orders/{o2['id']}/dispatch", role="PlatformAdmin", uid="admin", json={})
    a2 = d2.json()["data"]
    client.post(f"/api/assignments/{a2['id']}/accept", role="Rider", uid=rider["id"], json={})

    # a1 and a2 should share route_group_id
    a1_now = client.get(f"/api/assignments/{a1['id']}", role="Rider", uid=rider["id"]).json()["data"]
    a2_now = client.get(f"/api/assignments/{a2['id']}", role="Rider", uid=rider["id"]).json()["data"]
    assert a1_now["route_group_id"] is not None
    assert a1_now["route_group_id"] == a2_now["route_group_id"]


def test_route_merge_discount_25_percent():
    """When delivering a merged assignment, final_fee = solo_fee - floor(solo_fee * 0.25)."""
    rest_a = make_restaurant(name="A", lat=40.0000, lng=-74.0000)
    rest_b = make_restaurant(name="B", lat=40.0020, lng=-74.0000)
    item_a = make_menu_item(rest_a["id"], price_cents=2000)
    item_b = make_menu_item(rest_b["id"], price_cents=2000)
    c = make_customer(lat=40.0500, lng=-74.0000)
    rider = make_rider(online=True)
    o1 = place_order(c["id"], rest_a["id"], [{"menu_item_id": item_a["id"], "quantity": 1}])
    client.post(f"/api/orders/{o1['id']}/accept", role="Restaurant", uid=rest_a["id"], json={})
    d1 = client.post(f"/api/orders/{o1['id']}/dispatch", role="PlatformAdmin", uid="admin", json={})
    a1 = d1.json()["data"]
    client.post(f"/api/assignments/{a1['id']}/accept", role="Rider", uid=rider["id"], json={})
    o2 = place_order(c["id"], rest_b["id"], [{"menu_item_id": item_b["id"], "quantity": 1}])
    client.post(f"/api/orders/{o2['id']}/accept", role="Restaurant", uid=rest_b["id"], json={})
    d2 = client.post(f"/api/orders/{o2['id']}/dispatch", role="PlatformAdmin", uid="admin", json={})
    a2 = d2.json()["data"]
    client.post(f"/api/assignments/{a2['id']}/accept", role="Rider", uid=rider["id"], json={})
    client.post(f"/api/orders/{o1['id']}/start-preparing", role="Restaurant", uid=rest_a["id"], json={})
    client.post(f"/api/orders/{o1['id']}/ready", role="Restaurant", uid=rest_a["id"], json={})
    client.post(f"/api/assignments/{a1['id']}/pickup", role="Rider", uid=rider["id"], json={})
    client.post(f"/api/assignments/{a1['id']}/deliver", role="Rider", uid=rider["id"], json={})
    o1_now = client.get(f"/api/orders/{o1['id']}", role="PlatformAdmin", uid="admin").json()["data"]
    # Solo fee for ~5.6km distance + bands of ceil(distance) = 6 bands
    # final_fee should be less than the provisional
    assert o1_now["final_delivery_fee_cents"] < o1_now["provisional_delivery_fee_cents"]
    # Verify discount math precisely:
    import math
    solo = o1_now["provisional_delivery_fee_cents"]
    expected = solo - math.floor(solo * 0.25)
    assert o1_now["final_delivery_fee_cents"] == expected


def test_solo_delivery_no_route_group():
    rest = make_restaurant()
    item = make_menu_item(rest["id"], price_cents=2000)
    c = make_customer()
    rider = make_rider(online=True)
    o = place_order(c["id"], rest["id"], [{"menu_item_id": item["id"], "quantity": 1}])
    client.post(f"/api/orders/{o['id']}/accept", role="Restaurant", uid=rest["id"], json={})
    d = client.post(f"/api/orders/{o['id']}/dispatch", role="PlatformAdmin", uid="admin", json={})
    a = d.json()["data"]
    client.post(f"/api/assignments/{a['id']}/accept", role="Rider", uid=rider["id"], json={})
    a_now = client.get(f"/api/assignments/{a['id']}", role="Rider", uid=rider["id"]).json()["data"]
    assert a_now["route_group_id"] is None
