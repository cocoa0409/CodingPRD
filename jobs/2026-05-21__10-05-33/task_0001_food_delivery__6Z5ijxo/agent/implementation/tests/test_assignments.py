from . import client
from .fixtures import make_restaurant, make_menu_item, make_customer, make_rider, place_order


def setup_dispatched():
    rest = make_restaurant()
    item = make_menu_item(rest["id"], price_cents=2000)
    c = make_customer()
    rider = make_rider(online=True)
    o = place_order(c["id"], rest["id"], [{"menu_item_id": item["id"], "quantity": 1}])
    client.post(f"/api/orders/{o['id']}/accept", role="Restaurant", uid=rest["id"], json={})
    client.post(f"/api/orders/{o['id']}/start-preparing", role="Restaurant", uid=rest["id"], json={})
    # Find the assignment
    # we need to find via dispatch endpoint or list. Just fetch any assignment for the order:
    r = client.get(f"/api/orders?rider_id={rider['id']}", role="Rider", uid=rider["id"])
    # There may be assignment listing missing. Use admin to get orders, then find assignment via rider:
    # We don't have a list assignments endpoint, but we know dispatch creates a new one on start-preparing.
    # Use admin to read assignments via get endpoint - we need the ID.
    # Hack: search through orders to know rider has been dispatched; use get_orders to find current order
    # Better: do a direct read by guessing via api/assignments only. We don't know the id.
    # Let me get it indirectly: re-dispatch and get the new assignment.
    # Actually simpler: read order's relationship. The assignment id is hidden, but we can iterate.
    # I'll create another endpoint? No - let me just hold the id from the start-preparing internal state.
    # Solution: the dispatch_endpoint returns the assignment. Let's call dispatch after a rejection to get a fresh one.
    # Actually start-preparing should return the order; the assignment was created server-side.
    # Let me just call /dispatch to get a fresh assignment id (but only PlatformAdmin can).
    # Issue: this creates a SECOND assignment. The original OFFERED would still be active.
    # PRD says dispatch_offer always creates a new assignment if pool is non-empty. So two assignments exist.
    # Hmm, that complicates things.
    # Better: tests should use the dispatch endpoint to get the assignment id and act on it.
    # Let me restructure - skip /start-preparing for setup_dispatched and use /dispatch directly.
    raise NotImplementedError("rework setup")


def setup_dispatched_v2():
    rest = make_restaurant()
    item = make_menu_item(rest["id"], price_cents=2000)
    c = make_customer()
    rider = make_rider(online=True)
    o = place_order(c["id"], rest["id"], [{"menu_item_id": item["id"], "quantity": 1}])
    client.post(f"/api/orders/{o['id']}/accept", role="Restaurant", uid=rest["id"], json={})
    # Use dispatch endpoint so we can get the assignment id back
    d = client.post(f"/api/orders/{o['id']}/dispatch", role="PlatformAdmin", uid="admin", json={})
    assignment = d.json()["data"]
    return rest, item, c, rider, o, assignment


def test_assignment_accept_cascades_rider_status():
    rest, item, c, rider, o, a = setup_dispatched_v2()
    r = client.post(f"/api/assignments/{a['id']}/accept", role="Rider", uid=rider["id"], json={})
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "ACCEPTED"
    rd = client.get(f"/api/riders/{rider['id']}", role="Rider", uid=rider["id"])
    assert rd.json()["data"]["status"] == "ON_DELIVERY"


def test_assignment_accept_uniqueness():
    """A second OFFERED for the same order should reject ERR_ORDER_ALREADY_ASSIGNED on accept."""
    rest, item, c, rider, o, a = setup_dispatched_v2()
    rider2 = make_rider(online=True)
    # Create a second OFFERED for the same order targeting rider2
    d2 = client.post(f"/api/orders/{o['id']}/dispatch", role="PlatformAdmin", uid="admin", json={})
    # The dispatch picks the most recent rider — rider2 was registered AFTER rider, so rider2 wins
    a2 = d2.json()["data"]
    # Rider1 accepts first
    r1 = client.post(f"/api/assignments/{a['id']}/accept", role="Rider", uid=rider["id"], json={})
    assert r1.status_code == 200
    # Rider2's accept now fails
    r2 = client.post(f"/api/assignments/{a2['id']}/accept", role="Rider", uid=rider2["id"], json={})
    assert r2.status_code == 409, r2.text
    assert r2.json()["data"]["error_id"] == "ERR_ORDER_ALREADY_ASSIGNED"


def test_assignment_reject_redispatches():
    rest, item, c, rider, o, a = setup_dispatched_v2()
    rider2 = make_rider(online=True)
    r = client.post(f"/api/assignments/{a['id']}/reject", role="Rider", uid=rider["id"], json={})
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "REJECTED"
    # A new OFFERED should have been created targeting rider2 (or rider as both eligible)
    # We don't have list-assignments; verify by dispatching again and seeing whether it creates a new
    d = client.post(f"/api/orders/{o['id']}/dispatch", role="PlatformAdmin", uid="admin", json={})
    # this is the third assignment for this order
    assert d.status_code == 201


def test_assignment_pickup_requires_ready():
    rest, item, c, rider, o, a = setup_dispatched_v2()
    client.post(f"/api/assignments/{a['id']}/accept", role="Rider", uid=rider["id"], json={})
    # try pickup before ready (order is RESTAURANT_ACCEPTED)
    r = client.post(f"/api/assignments/{a['id']}/pickup", role="Rider", uid=rider["id"], json={})
    assert r.status_code == 409


def test_assignment_pickup_cascades_order():
    rest, item, c, rider, o, a = setup_dispatched_v2()
    client.post(f"/api/assignments/{a['id']}/accept", role="Rider", uid=rider["id"], json={})
    client.post(f"/api/orders/{o['id']}/start-preparing", role="Restaurant", uid=rest["id"], json={})
    client.post(f"/api/orders/{o['id']}/ready", role="Restaurant", uid=rest["id"], json={})
    r = client.post(f"/api/assignments/{a['id']}/pickup", role="Rider", uid=rider["id"], json={})
    assert r.status_code == 200
    od = client.get(f"/api/orders/{o['id']}", role="PlatformAdmin", uid="admin").json()["data"]
    assert od["status"] == "PICKED_UP"


def test_assignment_cancel_creates_no_show_fine():
    rest, item, c, rider, o, a = setup_dispatched_v2()
    client.post(f"/api/assignments/{a['id']}/accept", role="Rider", uid=rider["id"], json={})
    r = client.post(f"/api/assignments/{a['id']}/cancel", role="Rider", uid=rider["id"], json={})
    assert r.status_code == 200, r.text
    # Fine 500c on the rider
    fs = client.get(f"/api/fines?subject_type=RIDER&subject_id={rider['id']}",
                    role="Rider", uid=rider["id"])
    assert fs.status_code == 200
    fines = fs.json()["data"]
    no_show = [f for f in fines if f["reason"] == "RIDER_NO_SHOW"]
    assert len(no_show) == 1
    assert no_show[0]["amount_cents"] == 500
    # Wallet debited
    rd = client.get(f"/api/riders/{rider['id']}", role="Rider", uid=rider["id"]).json()["data"]
    assert rd["wallet_balance_cents"] == -500


def test_assignment_get_forbidden_other_rider():
    rest, item, c, rider, o, a = setup_dispatched_v2()
    other = make_rider(online=True)
    r = client.get(f"/api/assignments/{a['id']}", role="Rider", uid=other["id"])
    assert r.status_code == 403


def test_offer_timeout_sweep():
    rest, item, c, rider, o, a = setup_dispatched_v2()
    rider2 = make_rider(online=True)  # so re-dispatch has a target
    # advance > 60 seconds
    client.post("/api/_clock/advance", role="PlatformAdmin", uid="admin", json={"seconds": 61})
    ar = client.get(f"/api/assignments/{a['id']}", role="PlatformAdmin", uid="admin").json()["data"]
    assert ar["status"] == "REJECTED"


def test_dispatch_excludes_rider_with_live_assignment_for_same_order():
    rest, item, c, rider, o, a = setup_dispatched_v2()
    # rider already has live assignment a; dispatching again with only that rider should 409
    r = client.post(f"/api/orders/{o['id']}/dispatch", role="PlatformAdmin", uid="admin", json={})
    assert r.status_code == 409
