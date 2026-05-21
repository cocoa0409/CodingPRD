"""Route merging at 500m radius (§3.6, §3.7)."""
from __future__ import annotations

from ._factories import make_customer, make_menu_item, make_restaurant, make_rider, place_order
from ._harness import Client, expect_err, expect_ok, test


def _accept_dispatched(c, *, rest, mi, cust, rider, qty=1):
    """Walk an order from placement to ACCEPTED assignment for the given rider."""
    s, b = place_order(c, customer=cust, restaurant=rest,
                       items=[{"menu_item_id": mi["id"], "quantity": qty}])
    o = b["data"]
    c.post(f"/api/orders/{o['id']}/accept", role="Restaurant", user_id=rest["id"])
    c.post(f"/api/orders/{o['id']}/start-preparing", role="Restaurant", user_id=rest["id"])
    from app.store import store
    a = [x for x in store.assignments.values() if x["order_id"] == o["id"] and x["status"] == "OFFERED"][0]
    c.post(f"/api/assignments/{a['id']}/accept", role="Rider", user_id=rider["id"])
    return o, a


@test("two accepted nearby orders create a RouteGroup with both")
def t():
    c = Client()
    rider = make_rider(c, online=True)
    # Two restaurants at same coord (within 500m)
    r1 = make_restaurant(c, name="R1", lat=0.0, lng=0.0)
    r2 = make_restaurant(c, name="R2", lat=0.001, lng=0.001)  # ~140m away
    mi1 = make_menu_item(c, r1["id"], price_cents=1000)
    mi2 = make_menu_item(c, r2["id"], price_cents=1000)
    cust1 = make_customer(c, phone="P1", lat=0.0, lng=0.0)
    cust2 = make_customer(c, phone="P2", lat=0.0, lng=0.0)
    # First order: rider accepts -> ON_DELIVERY but no group yet (one assignment only)
    o1, a1 = _accept_dispatched(c, rest=r1, mi=mi1, cust=cust1, rider=rider)
    # Second order: rider accepts -> route merge triggers, group created with both
    o2, a2 = _accept_dispatched(c, rest=r2, mi=mi2, cust=cust2, rider=rider)
    from app.store import store
    a1f = store.assignments[a1["id"]]
    a2f = store.assignments[a2["id"]]
    assert a1f["route_group_id"] is not None
    assert a1f["route_group_id"] == a2f["route_group_id"]
    grp = store.route_groups[a1f["route_group_id"]]
    assert grp["status"] == "ACTIVE"
    assert grp["rider_id"] == rider["id"]
    assert set(grp["assignment_ids"]) == {a1["id"], a2["id"]}


@test("two orders >500m apart do NOT merge")
def t():
    c = Client()
    rider = make_rider(c, online=True)
    r1 = make_restaurant(c, name="R1", lat=0.0, lng=0.0)
    r2 = make_restaurant(c, name="R2", lat=0.01, lng=0.0)  # ~1.1 km
    mi1 = make_menu_item(c, r1["id"], price_cents=1000)
    mi2 = make_menu_item(c, r2["id"], price_cents=1000)
    cust1 = make_customer(c, phone="P1", lat=0.0, lng=0.0)
    cust2 = make_customer(c, phone="P2", lat=0.0, lng=0.0)
    o1, a1 = _accept_dispatched(c, rest=r1, mi=mi1, cust=cust1, rider=rider)
    # For the second order, dispatch goes to next rider; create another to ensure dispatch can find one
    # Actually since rider is ON_DELIVERY but NOT merge-eligible (>500m), dispatch should still pick rider if no other.
    o2, a2 = _accept_dispatched(c, rest=r2, mi=mi2, cust=cust2, rider=rider)
    from app.store import store
    a1f = store.assignments[a1["id"]]
    a2f = store.assignments[a2["id"]]
    # Neither is in a RouteGroup
    assert a1f["route_group_id"] is None
    assert a2f["route_group_id"] is None


@test("merged delivery applies 25% discount on final fee")
def t():
    c = Client()
    rider = make_rider(c, online=True)
    r1 = make_restaurant(c, name="R1", lat=0.0, lng=0.0)
    r2 = make_restaurant(c, name="R2", lat=0.001, lng=0.001)
    mi1 = make_menu_item(c, r1["id"], price_cents=1000)
    mi2 = make_menu_item(c, r2["id"], price_cents=1000)
    cust1 = make_customer(c, phone="P1", lat=0.0, lng=0.0)
    cust2 = make_customer(c, phone="P2", lat=0.0, lng=0.0)
    o1, a1 = _accept_dispatched(c, rest=r1, mi=mi1, cust=cust1, rider=rider)
    o2, a2 = _accept_dispatched(c, rest=r2, mi=mi2, cust=cust2, rider=rider)
    # Mark both restaurants ready, pick up both, then deliver
    c.post(f"/api/orders/{o1['id']}/ready", role="Restaurant", user_id=r1["id"])
    c.post(f"/api/orders/{o2['id']}/ready", role="Restaurant", user_id=r2["id"])
    c.post(f"/api/assignments/{a1['id']}/pickup", role="Rider", user_id=rider["id"])
    c.post(f"/api/assignments/{a2['id']}/pickup", role="Rider", user_id=rider["id"])
    s, b = c.post(f"/api/assignments/{a1['id']}/deliver", role="Rider", user_id=rider["id"])
    assert s == 200, b
    # solo fee at 0 km, off-peak = 300; merge discount floor(0.25*300) = 75 -> final = 225
    from app.store import store
    o1f = store.orders[o1["id"]]
    a1f = store.assignments[a1["id"]]
    assert o1f["final_delivery_fee_cents"] == 225, o1f
    assert a1f["final_delivery_fee_cents"] == 225


@test("RouteGroup transitions ACTIVE -> COMPLETED when all assignments delivered")
def t():
    c = Client()
    rider = make_rider(c, online=True)
    r1 = make_restaurant(c, name="R1", lat=0.0, lng=0.0)
    r2 = make_restaurant(c, name="R2", lat=0.001, lng=0.001)
    mi1 = make_menu_item(c, r1["id"], price_cents=1000)
    mi2 = make_menu_item(c, r2["id"], price_cents=1000)
    cust1 = make_customer(c, phone="P1", lat=0.0, lng=0.0)
    cust2 = make_customer(c, phone="P2", lat=0.0, lng=0.0)
    o1, a1 = _accept_dispatched(c, rest=r1, mi=mi1, cust=cust1, rider=rider)
    o2, a2 = _accept_dispatched(c, rest=r2, mi=mi2, cust=cust2, rider=rider)
    c.post(f"/api/orders/{o1['id']}/ready", role="Restaurant", user_id=r1["id"])
    c.post(f"/api/orders/{o2['id']}/ready", role="Restaurant", user_id=r2["id"])
    c.post(f"/api/assignments/{a1['id']}/pickup", role="Rider", user_id=rider["id"])
    c.post(f"/api/assignments/{a2['id']}/pickup", role="Rider", user_id=rider["id"])
    c.post(f"/api/assignments/{a1['id']}/deliver", role="Rider", user_id=rider["id"])
    from app.store import store
    grp_id = store.assignments[a1["id"]]["route_group_id"]
    # After first delivery, group still ACTIVE
    assert store.route_groups[grp_id]["status"] == "ACTIVE"
    # Rider stays ON_DELIVERY
    assert store.riders[rider["id"]]["status"] == "ON_DELIVERY"
    c.post(f"/api/assignments/{a2['id']}/deliver", role="Rider", user_id=rider["id"])
    # Now group COMPLETED, rider AVAILABLE
    assert store.route_groups[grp_id]["status"] == "COMPLETED"
    assert store.riders[rider["id"]]["status"] == "AVAILABLE"


@test("dispatch tier 1 prefers ON_DELIVERY rider with merge-eligible group over AVAILABLE rider")
def t():
    c = Client()
    # We need a busy rider with an existing RouteGroup (≥2 ACCEPTED assignments at same location)
    # then place a third order to verify tier-0 preference over a fresh AVAILABLE rider.
    r_busy = make_rider(c, phone="RA", online=True)
    rest1 = make_restaurant(c, name="A", lat=0.0, lng=0.0)
    rest2 = make_restaurant(c, name="B", lat=0.001, lng=0.001)
    rest3 = make_restaurant(c, name="C", lat=0.001, lng=0.001)
    mi1 = make_menu_item(c, rest1["id"], price_cents=1000)
    mi2 = make_menu_item(c, rest2["id"], price_cents=1000)
    mi3 = make_menu_item(c, rest3["id"], price_cents=1000)
    cust1 = make_customer(c, phone="P1", lat=0.0, lng=0.0)
    cust2 = make_customer(c, phone="P2", lat=0.0, lng=0.0)
    cust3 = make_customer(c, phone="P3", lat=0.0, lng=0.0)
    # First two: r_busy accepts both -> RouteGroup forms on second acceptance
    _accept_dispatched(c, rest=rest1, mi=mi1, cust=cust1, rider=r_busy)
    _accept_dispatched(c, rest=rest2, mi=mi2, cust=cust2, rider=r_busy)
    # Now add a freshly-online AVAILABLE rider
    r_avail = make_rider(c, phone="RB", online=True)
    # Third order at same location: dispatch must prefer r_busy (tier 0) over r_avail (tier 1)
    s, b = place_order(c, customer=cust3, restaurant=rest3,
                       items=[{"menu_item_id": mi3["id"], "quantity": 1}])
    o3 = b["data"]
    c.post(f"/api/orders/{o3['id']}/accept", role="Restaurant", user_id=rest3["id"])
    c.post(f"/api/orders/{o3['id']}/start-preparing", role="Restaurant", user_id=rest3["id"])
    from app.store import store
    offer = [x for x in store.assignments.values() if x["order_id"] == o3["id"] and x["status"] == "OFFERED"][0]
    assert offer["rider_id"] == r_busy["id"], \
        f"expected tier-0 r_busy={r_busy['id']}, got {offer['rider_id']} (r_avail={r_avail['id']})"
