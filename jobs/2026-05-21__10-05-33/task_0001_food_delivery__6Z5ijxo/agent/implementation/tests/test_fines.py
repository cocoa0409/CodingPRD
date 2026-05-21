from . import client
from .fixtures import make_restaurant, make_menu_item, make_customer, make_rider, place_order


def _setup_no_show_fine():
    rest = make_restaurant()
    item = make_menu_item(rest["id"], price_cents=2000)
    c = make_customer()
    rider = make_rider(online=True)
    o = place_order(c["id"], rest["id"], [{"menu_item_id": item["id"], "quantity": 1}])
    client.post(f"/api/orders/{o['id']}/accept", role="Restaurant", uid=rest["id"], json={})
    d = client.post(f"/api/orders/{o['id']}/dispatch", role="PlatformAdmin", uid="admin", json={})
    a = d.json()["data"]
    client.post(f"/api/assignments/{a['id']}/accept", role="Rider", uid=rider["id"], json={})
    client.post(f"/api/assignments/{a['id']}/cancel", role="Rider", uid=rider["id"], json={})
    return rider


def test_fines_list_by_subject():
    rider = _setup_no_show_fine()
    r = client.get(f"/api/fines?subject_type=RIDER&subject_id={rider['id']}",
                   role="Rider", uid=rider["id"])
    assert r.status_code == 200
    data = r.json()["data"]
    assert len(data) >= 1
    assert all(f["subject_id"] == rider["id"] for f in data)


def test_fines_list_role_scoping():
    rider = _setup_no_show_fine()
    # Wrong subject_id for the role
    r = client.get(f"/api/fines?subject_type=RIDER&subject_id=other-rider",
                   role="Rider", uid=rider["id"])
    assert r.status_code == 403


def test_fines_waive_reverses_wallet():
    rider = _setup_no_show_fine()
    fs = client.get(f"/api/fines?subject_type=RIDER&subject_id={rider['id']}",
                    role="Rider", uid=rider["id"]).json()["data"]
    fid = fs[0]["id"]
    pre = client.get(f"/api/riders/{rider['id']}", role="Rider", uid=rider["id"]).json()["data"]
    assert pre["wallet_balance_cents"] == -500
    w = client.post(f"/api/fines/{fid}/waive",
                    role="CustomerService", uid="cs-1", json={})
    assert w.status_code == 200, w.text
    assert w.json()["data"]["settlement_status"] == "WAIVED"
    post = client.get(f"/api/riders/{rider['id']}", role="Rider", uid=rider["id"]).json()["data"]
    assert post["wallet_balance_cents"] == 0


def test_fines_waive_already_waived_blocked():
    rider = _setup_no_show_fine()
    fs = client.get(f"/api/fines?subject_type=RIDER&subject_id={rider['id']}",
                    role="Rider", uid=rider["id"]).json()["data"]
    fid = fs[0]["id"]
    client.post(f"/api/fines/{fid}/waive", role="CustomerService", uid="cs-1", json={})
    r = client.post(f"/api/fines/{fid}/waive", role="CustomerService", uid="cs-1", json={})
    assert r.status_code == 409
