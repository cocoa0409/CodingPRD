from . import client
from .fixtures import make_restaurant, make_menu_item, make_customer, make_rider, place_order


def drive_to_delivered(restaurant, item, customer, rider, qty=1):
    o = place_order(customer["id"], restaurant["id"], [{"menu_item_id": item["id"], "quantity": qty}])
    client.post(f"/api/orders/{o['id']}/accept", role="Restaurant", uid=restaurant["id"], json={})
    d = client.post(f"/api/orders/{o['id']}/dispatch", role="PlatformAdmin", uid="admin", json={})
    a = d.json()["data"]
    client.post(f"/api/assignments/{a['id']}/accept", role="Rider", uid=rider["id"], json={})
    client.post(f"/api/orders/{o['id']}/start-preparing", role="Restaurant", uid=restaurant["id"], json={})
    client.post(f"/api/orders/{o['id']}/ready", role="Restaurant", uid=restaurant["id"], json={})
    client.post(f"/api/assignments/{a['id']}/pickup", role="Rider", uid=rider["id"], json={})
    return o, a


def test_on_time_delivery_no_fine():
    rest = make_restaurant(lat=0.0, lng=0.0)
    item = make_menu_item(rest["id"], price_cents=2000)
    c = make_customer(lat=0.0, lng=0.0)
    rider = make_rider(online=True)
    o, a = drive_to_delivered(rest, item, c, rider)
    # Deliver immediately => on-time
    r = client.post(f"/api/assignments/{a['id']}/deliver", role="Rider", uid=rider["id"], json={})
    assert r.status_code == 200, r.text
    od = client.get(f"/api/orders/{o['id']}", role="PlatformAdmin", uid="admin").json()["data"]
    assert od["status"] == "DELIVERED"
    assert od["minutes_late"] == 0
    assert od["payment_status"] == "CAPTURED"
    assert od["final_delivery_fee_cents"] is not None
    assert od["final_commission_cents"] is not None
    # No fine
    fs = client.get(f"/api/fines?subject_type=RIDER&subject_id={rider['id']}",
                    role="PlatformAdmin", uid="admin").json()["data"]
    assert not [f for f in fs if f["reason"] == "LATE_DELIVERY"]
    # Wallet credited fee
    rd = client.get(f"/api/riders/{rider['id']}", role="Rider", uid=rider["id"]).json()["data"]
    assert rd["wallet_balance_cents"] == od["final_delivery_fee_cents"]
    # Restaurant pending settlement increment
    rr = client.get(f"/api/restaurants/{rest['id']}", role="PlatformAdmin", uid="admin").json()["data"]
    assert rr["pending_settlement_cents"] == od["subtotal_cents"] - od["final_commission_cents"]
    # Rider returns to AVAILABLE
    assert rd["status"] == "AVAILABLE"


def test_late_delivery_tier1_fine_200():
    rest = make_restaurant(lat=0.0, lng=0.0)
    item = make_menu_item(rest["id"], price_cents=2000)
    c = make_customer(lat=0.0, lng=0.0)
    rider = make_rider(online=True)
    o, a = drive_to_delivered(rest, item, c, rider)
    # Advance 46 minutes = 2760s. Promised was placement + 45min. So delivery is 1 minute late.
    client.post("/api/_clock/advance", role="PlatformAdmin", uid="admin", json={"seconds": 46 * 60})
    client.post(f"/api/assignments/{a['id']}/deliver", role="Rider", uid=rider["id"], json={})
    od = client.get(f"/api/orders/{o['id']}", role="PlatformAdmin", uid="admin").json()["data"]
    assert od["minutes_late"] == 1
    fs = client.get(f"/api/fines?subject_type=RIDER&subject_id={rider['id']}",
                    role="PlatformAdmin", uid="admin").json()["data"]
    late = [f for f in fs if f["reason"] == "LATE_DELIVERY"]
    assert len(late) == 1
    assert late[0]["amount_cents"] == 200


def test_late_delivery_tier2_fine():
    """20 min late: 500 + 50*(20-10) = 1000."""
    rest = make_restaurant(lat=0.0, lng=0.0)
    item = make_menu_item(rest["id"], price_cents=2000)
    c = make_customer(lat=0.0, lng=0.0)
    rider = make_rider(online=True)
    o, a = drive_to_delivered(rest, item, c, rider)
    client.post("/api/_clock/advance", role="PlatformAdmin", uid="admin", json={"seconds": 65 * 60})
    client.post(f"/api/assignments/{a['id']}/deliver", role="Rider", uid=rider["id"], json={})
    od = client.get(f"/api/orders/{o['id']}", role="PlatformAdmin", uid="admin").json()["data"]
    assert od["minutes_late"] == 20
    fs = client.get(f"/api/fines?subject_type=RIDER&subject_id={rider['id']}",
                    role="PlatformAdmin", uid="admin").json()["data"]
    late = [f for f in fs if f["reason"] == "LATE_DELIVERY"]
    assert late[0]["amount_cents"] == 1000


def test_late_delivery_tier3_capped():
    """>30 min late: min(final_fee, 1500) + 500."""
    rest = make_restaurant(lat=0.0, lng=0.0)
    item = make_menu_item(rest["id"], price_cents=2000)
    c = make_customer(lat=0.0, lng=0.0)
    rider = make_rider(online=True)
    o, a = drive_to_delivered(rest, item, c, rider)
    client.post("/api/_clock/advance", role="PlatformAdmin", uid="admin", json={"seconds": 90 * 60})
    client.post(f"/api/assignments/{a['id']}/deliver", role="Rider", uid=rider["id"], json={})
    od = client.get(f"/api/orders/{o['id']}", role="PlatformAdmin", uid="admin").json()["data"]
    assert od["minutes_late"] >= 45
    fs = client.get(f"/api/fines?subject_type=RIDER&subject_id={rider['id']}",
                    role="PlatformAdmin", uid="admin").json()["data"]
    late = [f for f in fs if f["reason"] == "LATE_DELIVERY"]
    # fee for 0km, may be peak or not — but the formula caps at 1500 + 500 = 2000 at most
    fee = od["final_delivery_fee_cents"]
    expected = min(fee, 1500) + 500
    assert late[0]["amount_cents"] == expected


def test_commission_override_used_at_delivery():
    rest = make_restaurant(lat=0.0, lng=0.0, commission_rate_override=0.10)
    item = make_menu_item(rest["id"], price_cents=10000)
    c = make_customer(lat=0.0, lng=0.0)
    rider = make_rider(online=True)
    o, a = drive_to_delivered(rest, item, c, rider)
    client.post(f"/api/assignments/{a['id']}/deliver", role="Rider", uid=rider["id"], json={})
    od = client.get(f"/api/orders/{o['id']}", role="PlatformAdmin", uid="admin").json()["data"]
    # 10000 * 0.10 = 1000
    assert od["final_commission_cents"] == 1000
    # provisional was the tiered calculation: 10000 * 0.15 = 1500
    assert od["provisional_commission_cents"] == 1500
