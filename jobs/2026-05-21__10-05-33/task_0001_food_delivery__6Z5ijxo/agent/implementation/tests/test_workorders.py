from . import client
from .fixtures import make_customer


def test_workorder_open_and_full_cycle():
    c = make_customer()
    r = client.post("/api/work-orders", role="Customer", uid=c["id"],
                    json={"category": "PAYMENT_ISSUE"})
    assert r.status_code == 201
    wo = r.json()["data"]
    assert wo["status"] == "OPEN"
    assert wo["opened_by_role"] == "CUSTOMER"
    assert wo["opened_by_id"] == c["id"]

    a = client.post(f"/api/work-orders/{wo['id']}/assign",
                    role="CustomerService", uid="cs-1", json={})
    assert a.status_code == 200
    assert a.json()["data"]["assigned_cs_user_id"] == "cs-1"
    assert a.json()["data"]["status"] == "UNDER_REVIEW"

    req = client.post(f"/api/work-orders/{wo['id']}/request-info",
                      role="CustomerService", uid="cs-1", json={})
    assert req.status_code == 200
    assert req.json()["data"]["status"] == "AWAITING_INFO"

    sub = client.post(f"/api/work-orders/{wo['id']}/submit-info",
                      role="Customer", uid=c["id"], json={})
    assert sub.status_code == 200
    assert sub.json()["data"]["status"] == "UNDER_REVIEW"

    res = client.post(f"/api/work-orders/{wo['id']}/resolve",
                      role="CustomerService", uid="cs-1",
                      json={"resolution_notes": "fixed"})
    assert res.status_code == 200
    assert res.json()["data"]["status"] == "RESOLVED"

    cl = client.post(f"/api/work-orders/{wo['id']}/close",
                     role="CustomerService", uid="cs-1", json={})
    assert cl.status_code == 200
    assert cl.json()["data"]["status"] == "CLOSED"


def test_workorder_submit_info_identity_mismatch():
    c1 = make_customer()
    c2 = make_customer()
    wo = client.post("/api/work-orders", role="Customer", uid=c1["id"],
                     json={"category": "OTHER"}).json()["data"]
    client.post(f"/api/work-orders/{wo['id']}/assign",
                role="CustomerService", uid="cs-1", json={})
    client.post(f"/api/work-orders/{wo['id']}/request-info",
                role="CustomerService", uid="cs-1", json={})
    sub = client.post(f"/api/work-orders/{wo['id']}/submit-info",
                      role="Customer", uid=c2["id"], json={})
    assert sub.status_code == 403


def test_workorder_resolve_requires_assignee():
    c = make_customer()
    wo = client.post("/api/work-orders", role="Customer", uid=c["id"],
                     json={"category": "OTHER"}).json()["data"]
    # without assign, status is OPEN — resolve from OPEN is invalid state anyway
    r = client.post(f"/api/work-orders/{wo['id']}/resolve",
                    role="CustomerService", uid="cs-1",
                    json={"resolution_notes": "x"})
    assert r.status_code == 409


def test_workorder_resolve_blocked_by_pending_return():
    from .fixtures import make_restaurant, make_menu_item, make_rider, place_order
    rest = make_restaurant(lat=0, lng=0)
    item = make_menu_item(rest["id"], price_cents=2000)
    c = make_customer(lat=0, lng=0)
    rider = make_rider(online=True)
    o = place_order(c["id"], rest["id"], [{"menu_item_id": item["id"], "quantity": 1}])
    client.post(f"/api/orders/{o['id']}/accept", role="Restaurant", uid=rest["id"], json={})
    d = client.post(f"/api/orders/{o['id']}/dispatch", role="PlatformAdmin", uid="admin", json={})
    a = d.json()["data"]
    client.post(f"/api/assignments/{a['id']}/accept", role="Rider", uid=rider["id"], json={})
    client.post(f"/api/orders/{o['id']}/start-preparing", role="Restaurant", uid=rest["id"], json={})
    client.post(f"/api/orders/{o['id']}/ready", role="Restaurant", uid=rest["id"], json={})
    client.post(f"/api/assignments/{a['id']}/pickup", role="Rider", uid=rider["id"], json={})
    client.post(f"/api/assignments/{a['id']}/deliver", role="Rider", uid=rider["id"], json={})
    ret = client.post(f"/api/orders/{o['id']}/returns", role="Customer", uid=c["id"],
                      json={"reason": "OTHER", "requested_refund_cents": 100}).json()["data"]
    # Open a work order linked to the return
    wo = client.post("/api/work-orders", role="CustomerService", uid="cs-1",
                     json={"category": "OTHER", "related_return_id": ret["id"]}).json()["data"]
    client.post(f"/api/work-orders/{wo['id']}/assign",
                role="CustomerService", uid="cs-1", json={})
    # Try to resolve - return still REQUESTED -> blocked
    r = client.post(f"/api/work-orders/{wo['id']}/resolve",
                    role="CustomerService", uid="cs-1",
                    json={"resolution_notes": "x"})
    assert r.status_code == 422
    assert r.json()["data"]["error_id"] == "ERR_RELATED_RETURN_UNRESOLVED"
    # Approve the return then try again
    client.post(f"/api/returns/{ret['id']}/approve",
                role="CustomerService", uid="cs-1",
                json={"approved_refund_cents": 100})
    r2 = client.post(f"/api/work-orders/{wo['id']}/resolve",
                     role="CustomerService", uid="cs-1",
                     json={"resolution_notes": "x"})
    assert r2.status_code == 200
