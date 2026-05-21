from . import client
from .fixtures import make_restaurant, make_menu_item, make_customer, make_rider, place_order


def drive_to_delivered(quantity=1, item_price=2000, peak_skip=False):
    rest = make_restaurant(lat=0.0, lng=0.0)
    item = make_menu_item(rest["id"], price_cents=item_price)
    c = make_customer(lat=0.0, lng=0.0)
    rider = make_rider(online=True)
    o = place_order(c["id"], rest["id"], [{"menu_item_id": item["id"], "quantity": quantity}])
    client.post(f"/api/orders/{o['id']}/accept", role="Restaurant", uid=rest["id"], json={})
    d = client.post(f"/api/orders/{o['id']}/dispatch", role="PlatformAdmin", uid="admin", json={})
    a = d.json()["data"]
    client.post(f"/api/assignments/{a['id']}/accept", role="Rider", uid=rider["id"], json={})
    client.post(f"/api/orders/{o['id']}/start-preparing", role="Restaurant", uid=rest["id"], json={})
    client.post(f"/api/orders/{o['id']}/ready", role="Restaurant", uid=rest["id"], json={})
    client.post(f"/api/assignments/{a['id']}/pickup", role="Rider", uid=rider["id"], json={})
    client.post(f"/api/assignments/{a['id']}/deliver", role="Rider", uid=rider["id"], json={})
    return rest, item, c, rider, o, a


def test_open_return_basic():
    rest, item, c, rider, o, a = drive_to_delivered()
    r = client.post(f"/api/orders/{o['id']}/returns", role="Customer", uid=c["id"],
                    json={"reason": "QUALITY_ISSUE", "requested_refund_cents": 500})
    assert r.status_code == 201, r.text
    d = r.json()["data"]
    assert d["status"] == "REQUESTED"
    assert d["requested_refund_cents"] == 500
    # Order moved to REFUND_REQUESTED
    od = client.get(f"/api/orders/{o['id']}", role="Customer", uid=c["id"]).json()["data"]
    assert od["status"] == "REFUND_REQUESTED"


def test_return_window_expired():
    rest, item, c, rider, o, a = drive_to_delivered()
    # Advance > 24h
    client.post("/api/_clock/advance", role="PlatformAdmin", uid="admin",
                json={"seconds": 25 * 3600})
    r = client.post(f"/api/orders/{o['id']}/returns", role="Customer", uid=c["id"],
                    json={"reason": "QUALITY_ISSUE", "requested_refund_cents": 100})
    assert r.status_code == 422
    assert r.json()["data"]["error_id"] == "ERR_RETURN_WINDOW_EXPIRED"


def test_return_refund_amount_invalid_low():
    rest, item, c, rider, o, a = drive_to_delivered()
    r = client.post(f"/api/orders/{o['id']}/returns", role="Customer", uid=c["id"],
                    json={"reason": "OTHER", "requested_refund_cents": 0})
    assert r.status_code == 422
    assert r.json()["data"]["error_id"] == "ERR_REFUND_AMOUNT_INVALID"


def test_return_refund_amount_invalid_high():
    rest, item, c, rider, o, a = drive_to_delivered()
    r = client.post(f"/api/orders/{o['id']}/returns", role="Customer", uid=c["id"],
                    json={"reason": "OTHER", "requested_refund_cents": o["subtotal_cents"] + 1})
    assert r.status_code == 422
    assert r.json()["data"]["error_id"] == "ERR_REFUND_AMOUNT_INVALID"


def test_duplicate_return_blocked():
    rest, item, c, rider, o, a = drive_to_delivered()
    r = client.post(f"/api/orders/{o['id']}/returns", role="Customer", uid=c["id"],
                    json={"reason": "OTHER", "requested_refund_cents": 100})
    assert r.status_code == 201
    r2 = client.post(f"/api/orders/{o['id']}/returns", role="Customer", uid=c["id"],
                     json={"reason": "OTHER", "requested_refund_cents": 100})
    assert r2.status_code == 409
    assert r2.json()["data"]["error_id"] == "ERR_DUPLICATE_RETURN"


def test_return_approve_cascade():
    rest, item, c, rider, o, a = drive_to_delivered()
    r = client.post(f"/api/orders/{o['id']}/returns", role="Customer", uid=c["id"],
                    json={"reason": "OTHER", "requested_refund_cents": 500}).json()["data"]
    # Restaurant pending settlement was incremented by subtotal - final_commission
    before = client.get(f"/api/restaurants/{rest['id']}", role="PlatformAdmin", uid="admin").json()["data"]["pending_settlement_cents"]
    ap = client.post(f"/api/returns/{r['id']}/approve", role="CustomerService", uid="cs-1",
                     json={"approved_refund_cents": 500})
    assert ap.status_code == 200, ap.text
    assert ap.json()["data"]["status"] == "APPROVED"
    assert ap.json()["data"]["reviewer_cs_user_id"] == "cs-1"
    od = client.get(f"/api/orders/{o['id']}", role="PlatformAdmin", uid="admin").json()["data"]
    assert od["status"] == "REFUNDED"
    assert od["payment_status"] == "PARTIALLY_REFUNDED"
    cd = client.get(f"/api/customers/{c['id']}", role="Customer", uid=c["id"]).json()["data"]
    assert cd["credit_balance_cents"] == 500
    rr = client.get(f"/api/restaurants/{rest['id']}", role="PlatformAdmin", uid="admin").json()["data"]
    assert rr["pending_settlement_cents"] == before - 500


def test_return_approve_full_refund():
    rest, item, c, rider, o, a = drive_to_delivered()
    sub = o["subtotal_cents"]
    r = client.post(f"/api/orders/{o['id']}/returns", role="Customer", uid=c["id"],
                    json={"reason": "OTHER", "requested_refund_cents": sub}).json()["data"]
    ap = client.post(f"/api/returns/{r['id']}/approve", role="CustomerService", uid="cs-1",
                     json={"approved_refund_cents": sub})
    assert ap.status_code == 200
    od = client.get(f"/api/orders/{o['id']}", role="PlatformAdmin", uid="admin").json()["data"]
    assert od["payment_status"] == "FULLY_REFUNDED"


def test_return_approve_exceeds_requested():
    rest, item, c, rider, o, a = drive_to_delivered()
    r = client.post(f"/api/orders/{o['id']}/returns", role="Customer", uid=c["id"],
                    json={"reason": "OTHER", "requested_refund_cents": 500}).json()["data"]
    ap = client.post(f"/api/returns/{r['id']}/approve", role="CustomerService", uid="cs-1",
                     json={"approved_refund_cents": 600})
    assert ap.status_code == 422
    assert ap.json()["data"]["error_id"] == "ERR_REFUND_AMOUNT_INVALID"


def test_return_reject_reverts_order():
    rest, item, c, rider, o, a = drive_to_delivered()
    r = client.post(f"/api/orders/{o['id']}/returns", role="Customer", uid=c["id"],
                    json={"reason": "OTHER", "requested_refund_cents": 500}).json()["data"]
    rj = client.post(f"/api/returns/{r['id']}/reject", role="CustomerService", uid="cs-1", json={})
    assert rj.status_code == 200
    od = client.get(f"/api/orders/{o['id']}", role="PlatformAdmin", uid="admin").json()["data"]
    assert od["status"] == "DELIVERED"


def test_return_escalate_opens_workorder():
    rest, item, c, rider, o, a = drive_to_delivered()
    r = client.post(f"/api/orders/{o['id']}/returns", role="Customer", uid=c["id"],
                    json={"reason": "OTHER", "requested_refund_cents": 500}).json()["data"]
    es = client.post(f"/api/returns/{r['id']}/escalate", role="CustomerService", uid="cs-1", json={})
    assert es.status_code == 200
    assert es.json()["data"]["status"] == "ESCALATED"


def test_return_reopen_closes_workorder():
    rest, item, c, rider, o, a = drive_to_delivered()
    r = client.post(f"/api/orders/{o['id']}/returns", role="Customer", uid=c["id"],
                    json={"reason": "OTHER", "requested_refund_cents": 500}).json()["data"]
    client.post(f"/api/returns/{r['id']}/escalate", role="CustomerService", uid="cs-1", json={})
    re = client.post(f"/api/returns/{r['id']}/reopen", role="CustomerService", uid="cs-1", json={})
    assert re.status_code == 200
    assert re.json()["data"]["status"] == "REQUESTED"
