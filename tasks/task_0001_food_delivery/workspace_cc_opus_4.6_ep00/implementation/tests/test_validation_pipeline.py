"""Tests verifying the validation pipeline ordering per §2.6."""
import pytest
from tests.conftest import (
    admin_headers, customer_headers, restaurant_headers, rider_headers, cs_headers,
    create_restaurant, approve_restaurant, create_menu_item, create_customer,
    create_rider, setup_full_order,
)
from store import store


def test_auth_before_everything(client):
    """Step 1: Missing auth fires before any other check."""
    resp = client.get("/api/restaurants/nonexistent")
    assert resp.status_code == 401


def test_role_before_not_found(client):
    """Step 2: Role check fires before path param existence."""
    resp = client.post("/api/restaurants/nonexistent/approve",
                       headers={"X-User-ID": "c1", "X-User-Role": "Customer"})
    assert resp.status_code == 403  # Customer not authorized to approve


def test_not_found_before_forbidden(client):
    """Step 3: Path param existence fires before identity match."""
    resp = client.patch("/api/restaurants/nonexistent", json={"address": "new"},
                        headers=restaurant_headers("some-restaurant"))
    assert resp.status_code == 404


def test_fk_not_found_before_identity(client):
    """Step 4: FK existence fires before identity match on order placement."""
    resp = client.post("/api/orders", json={
        "customer_id": "nonexistent-customer",
        "restaurant_id": "nonexistent-restaurant",
        "items": [],
    }, headers=customer_headers("wrong-customer"))
    assert resp.status_code == 404
    assert resp.get_json()["data"]["error_id"] == "ERR_NOT_FOUND"


def test_identity_before_state(client):
    """Step 5: Identity match fires before state-machine check."""
    r = create_restaurant(client)
    approve_restaurant(client, r["id"])
    mi = create_menu_item(client, r["id"], price_cents=1000)
    c = create_customer(client)
    rider = create_rider(client)
    client.post(f"/api/riders/{rider['id']}/go-online", headers=rider_headers(rider["id"]))

    resp = client.post("/api/orders", json={
        "customer_id": c["id"], "restaurant_id": r["id"],
        "items": [{"menu_item_id": mi["id"], "quantity": 1}],
    }, headers=customer_headers(c["id"]))
    order = resp.get_json()["data"]

    # Order is PLACED, try to accept with wrong restaurant
    resp = client.post(f"/api/orders/{order['id']}/accept",
                       headers=restaurant_headers("wrong-restaurant"))
    assert resp.status_code == 403


def test_state_before_uniqueness(client):
    """Step 6 fires before step 8."""
    s = setup_full_order(client)
    # Cancel the order first so it's not PLACED
    client.post(f"/api/orders/{s['order']['id']}/cancel",
                headers=customer_headers(s["customer"]["id"]))
    # Try to accept cancelled order
    resp = client.post(f"/api/orders/{s['order']['id']}/accept",
                       headers=restaurant_headers(s["restaurant"]["id"]))
    assert resp.status_code == 409
    assert resp.get_json()["data"]["error_id"] == "ERR_INVALID_STATE"


def test_menu_item_fk_before_domain_check(client):
    """Step 4: Menu item FK not found fires before restaurant unavailable check."""
    r = create_restaurant(client)
    approve_restaurant(client, r["id"])
    c = create_customer(client)

    resp = client.post("/api/orders", json={
        "customer_id": c["id"], "restaurant_id": r["id"],
        "items": [{"menu_item_id": "nonexistent-item", "quantity": 1}],
    }, headers=customer_headers(c["id"]))
    assert resp.status_code == 404
    assert resp.get_json()["data"]["error_id"] == "ERR_NOT_FOUND"


def test_restaurant_unavailable_before_order_invalid(client):
    """Step 7: Restaurant check fires before shape-of-input check."""
    r = create_restaurant(client)
    # Don't approve - restaurant is PENDING_APPROVAL
    mi = create_menu_item(client, r["id"], price_cents=50)  # Below minimum
    c = create_customer(client)

    resp = client.post("/api/orders", json={
        "customer_id": c["id"], "restaurant_id": r["id"],
        "items": [{"menu_item_id": mi["id"], "quantity": 1}],
    }, headers=customer_headers(c["id"]))
    assert resp.status_code == 422
    assert resp.get_json()["data"]["error_id"] == "ERR_RESTAURANT_UNAVAILABLE"


def test_version_conflict_on_restaurant_update(client):
    """OCC check (step 12) fires when version mismatches."""
    r = create_restaurant(client)
    # First update succeeds
    resp = client.patch(f"/api/restaurants/{r['id']}", json={
        "address": "New1", "version": 1,
    }, headers=restaurant_headers(r["id"]))
    assert resp.status_code == 200

    # Second update with stale version fails
    resp = client.patch(f"/api/restaurants/{r['id']}", json={
        "address": "New2", "version": 1,
    }, headers=restaurant_headers(r["id"]))
    assert resp.status_code == 409
    assert resp.get_json()["data"]["error_id"] == "ERR_VERSION_CONFLICT"


def test_occ_optional(client):
    """When version is omitted, OCC is skipped."""
    r = create_restaurant(client)
    resp1 = client.patch(f"/api/restaurants/{r['id']}", json={
        "address": "New1",
    }, headers=restaurant_headers(r["id"]))
    assert resp1.status_code == 200

    resp2 = client.patch(f"/api/restaurants/{r['id']}", json={
        "address": "New2",
    }, headers=restaurant_headers(r["id"]))
    assert resp2.status_code == 200
    assert resp2.get_json()["data"]["version"] == 3


def test_related_return_unresolved_blocks_wo_resolve(client):
    """Step 13: Cross-entity gating fires on work order resolve."""
    from tests.test_returns import deliver_order
    s = setup_full_order(client)
    deliver_order(client, s)

    resp = client.post(f"/api/orders/{s['order']['id']}/returns", json={
        "reason": "OTHER", "requested_refund_cents": 500,
    }, headers=customer_headers(s["customer"]["id"]))
    return_id = resp.get_json()["data"]["id"]

    # Create work order linked to the return
    resp = client.post("/api/work-orders", json={
        "opened_by_role": "CUSTOMER", "opened_by_id": s["customer"]["id"],
        "category": "OTHER", "related_return_id": return_id,
    }, headers=customer_headers(s["customer"]["id"]))
    wo_id = resp.get_json()["data"]["id"]

    client.post(f"/api/work-orders/{wo_id}/assign", headers=cs_headers())

    # Should fail because return is still REQUESTED
    resp = client.post(f"/api/work-orders/{wo_id}/resolve", json={
        "resolution_notes": "Done",
    }, headers=cs_headers())
    assert resp.status_code == 422
    assert resp.get_json()["data"]["error_id"] == "ERR_RELATED_RETURN_UNRESOLVED"

    # Now approve the return
    client.post(f"/api/returns/{return_id}/approve", json={
        "approved_refund_cents": 500,
    }, headers=cs_headers())

    # Now resolve should work
    resp = client.post(f"/api/work-orders/{wo_id}/resolve", json={
        "resolution_notes": "Done",
    }, headers=cs_headers())
    assert resp.status_code == 200
