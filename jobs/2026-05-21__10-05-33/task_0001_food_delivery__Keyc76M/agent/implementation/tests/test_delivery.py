"""Tests for §3.7 delivery cascade: fees, commission, payment, settlement,
wallet, late fines, bonus tier, route-group completion, rider state."""

from tests.harness import (
    test, fresh_client, jget, jpost, jpatch, body_of,
    assert_eq, admin_headers, cust_headers, rest_headers, rider_headers,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_world(c, customer_lat=0.0, customer_lng=0.0,
                price_cents=5000, credit_cents=0):
    """Create a restaurant, menu item, customer (optionally with credit),
    and an online rider. Restaurant sits at (0,0)."""
    rid = body_of(jpost(c, "/api/restaurants",
                       body={"name": "R", "address": "A",
                             "lat": 0.0, "lng": 0.0},
                       headers=admin_headers()))["data"]["id"]
    jpost(c, f"/api/restaurants/{rid}/approve", headers=admin_headers())
    mid = body_of(jpost(c, f"/api/restaurants/{rid}/menu-items",
                       body={"name": "B", "price_cents": price_cents},
                       headers=rest_headers(rid)))["data"]["id"]
    cid = body_of(jpost(c, "/api/customers",
                       body={"name": "C", "phone": "+1",
                             "address": "A",
                             "lat": customer_lat, "lng": customer_lng},
                       headers=admin_headers()))["data"]["id"]
    if credit_cents:
        import state
        state.STORE.customers[cid]["credit_balance_cents"] = credit_cents
    rrid = body_of(jpost(c, "/api/riders",
                        body={"name": "R", "phone": "+9"},
                        headers=admin_headers()))["data"]["id"]
    jpost(c, f"/api/riders/{rrid}/go-online", headers=rider_headers(rrid))
    return rid, mid, cid, rrid


def _place(c, rid, mid, cid, qty=1):
    return body_of(jpost(c, "/api/orders",
                         body={"customer_id": cid, "restaurant_id": rid,
                               "items": [{"menu_item_id": mid,
                                          "quantity": qty}]},
                         headers=cust_headers(cid)))["data"]


def _find_offer(c, oid):
    import state
    cands = [a for a in state.STORE.assignments.values()
             if a["order_id"] == oid and a["status"] == "OFFERED"]
    cands.sort(key=lambda a: a["offered_at"], reverse=True)
    return cands[0] if cands else None


def _drive_to_picked_up(c, rid, mid, cid, rrid):
    order = _place(c, rid, mid, cid)
    jpost(c, f"/api/orders/{order['id']}/accept", headers=rest_headers(rid))
    jpost(c, f"/api/orders/{order['id']}/start-preparing",
          headers=rest_headers(rid))
    off = _find_offer(c, order["id"])
    jpost(c, f"/api/assignments/{off['id']}/accept",
          headers=rider_headers(rrid))
    jpost(c, f"/api/orders/{order['id']}/ready", headers=rest_headers(rid))
    jpost(c, f"/api/assignments/{off['id']}/pickup",
          headers=rider_headers(rrid))
    return order, off


# ---------------------------------------------------------------------------
# Payment & order state transitions
# ---------------------------------------------------------------------------

@test("deliver: order status -> DELIVERED, payment_status -> CAPTURED")
def t_delivered_capture():
    c = fresh_client()
    rid, mid, cid, rrid = _make_world(c)
    order, off = _drive_to_picked_up(c, rid, mid, cid, rrid)
    jpost(c, f"/api/assignments/{off['id']}/deliver",
          headers=rider_headers(rrid))
    o = body_of(jget(c, f"/api/orders/{order['id']}",
                     headers=admin_headers()))["data"]
    assert_eq(o["status"], "DELIVERED", "order DELIVERED")
    assert_eq(o["payment_status"], "CAPTURED", "payment CAPTURED")
    assert o["actual_delivery_time"] is not None, "actual time set"


@test("deliver: assignment status -> DELIVERED with delivered_at")
def t_assignment_delivered():
    c = fresh_client()
    rid, mid, cid, rrid = _make_world(c)
    order, off = _drive_to_picked_up(c, rid, mid, cid, rrid)
    a = body_of(jpost(c, f"/api/assignments/{off['id']}/deliver",
                      headers=rider_headers(rrid)))["data"]
    assert_eq(a["status"], "DELIVERED", "assignment DELIVERED")
    assert a["delivered_at"] is not None, "delivered_at set"


# ---------------------------------------------------------------------------
# Fee, commission, settlement, wallet
# ---------------------------------------------------------------------------

@test("deliver: final_delivery_fee mirrored on assignment + order (solo)")
def t_fee_mirrored():
    c = fresh_client()
    rid, mid, cid, rrid = _make_world(c)
    order, off = _drive_to_picked_up(c, rid, mid, cid, rrid)
    a = body_of(jpost(c, f"/api/assignments/{off['id']}/deliver",
                      headers=rider_headers(rrid)))["data"]
    o = body_of(jget(c, f"/api/orders/{order['id']}",
                     headers=admin_headers()))["data"]
    assert a["final_delivery_fee_cents"] is not None, "set on assignment"
    assert_eq(a["final_delivery_fee_cents"], o["final_delivery_fee_cents"],
              "fee mirrored")
    # Same-coords solo fee: 300 (+200 peak).
    assert a["final_delivery_fee_cents"] in (300, 500), "off-peak or peak"


@test("deliver: restaurant settlement increments by subtotal - commission")
def t_settlement_increment():
    c = fresh_client()
    rid, mid, cid, rrid = _make_world(c, price_cents=5000)
    # subtotal = 5000 → tier1: 750
    order, off = _drive_to_picked_up(c, rid, mid, cid, rrid)
    before = body_of(jget(c, f"/api/restaurants/{rid}",
                          headers=admin_headers()))["data"][
        "pending_settlement_cents"]
    jpost(c, f"/api/assignments/{off['id']}/deliver",
          headers=rider_headers(rrid))
    after = body_of(jget(c, f"/api/restaurants/{rid}",
                         headers=admin_headers()))["data"][
        "pending_settlement_cents"]
    assert_eq(after - before, 5000 - 750, "delta = subtotal - commission")


@test("deliver: rider wallet credited by final_delivery_fee")
def t_wallet_credit():
    c = fresh_client()
    rid, mid, cid, rrid = _make_world(c)
    order, off = _drive_to_picked_up(c, rid, mid, cid, rrid)
    a = body_of(jpost(c, f"/api/assignments/{off['id']}/deliver",
                      headers=rider_headers(rrid)))["data"]
    rider = body_of(jget(c, f"/api/riders/{rrid}",
                         headers=rider_headers(rrid)))["data"]
    assert_eq(rider["wallet_balance_cents"], a["final_delivery_fee_cents"],
              "wallet = fee")


@test("deliver: tiered commission used when no override")
def t_tiered_commission():
    c = fresh_client()
    # subtotal = 30000 → tier1 20000*0.15 + tier2 10000*0.18 = 3000 + 1800 = 4800
    rid, mid, cid, rrid = _make_world(c, price_cents=30000)
    order, off = _drive_to_picked_up(c, rid, mid, cid, rrid)
    jpost(c, f"/api/assignments/{off['id']}/deliver",
          headers=rider_headers(rrid))
    o = body_of(jget(c, f"/api/orders/{order['id']}",
                     headers=admin_headers()))["data"]
    assert_eq(o["final_commission_cents"], 4800, "tiered commission")


@test("deliver: override commission applied at delivery (not provisional)")
def t_override_at_delivery():
    """A mid-flight commission-rate change updates the FINAL commission."""
    c = fresh_client()
    rid, mid, cid, rrid = _make_world(c, price_cents=10000)
    order, off = _drive_to_picked_up(c, rid, mid, cid, rrid)
    # Provisional commission was tiered (10000*0.15 = 1500). Now apply
    # a 10% override mid-flight by mutating the restaurant directly (the
    # PRD allows admin override via /restaurants/{id} commission patch).
    import state
    state.STORE.restaurants[rid]["commission_rate_override"] = 0.10
    jpost(c, f"/api/assignments/{off['id']}/deliver",
          headers=rider_headers(rrid))
    o = body_of(jget(c, f"/api/orders/{order['id']}",
                     headers=admin_headers()))["data"]
    assert_eq(o["final_commission_cents"], 1000, "uses current override")
    assert_eq(o["provisional_commission_cents"], 1500, "provisional unchanged")


# ---------------------------------------------------------------------------
# Customer credit drawdown
# ---------------------------------------------------------------------------

@test("deliver: credit not drawn during AUTHORIZED")
def t_credit_not_drawn_at_authorize():
    c = fresh_client()
    rid, mid, cid, rrid = _make_world(c, credit_cents=10000)
    order = _place(c, rid, mid, cid)
    cust = body_of(jget(c, f"/api/customers/{cid}",
                        headers=admin_headers()))["data"]
    assert_eq(cust["credit_balance_cents"], 10000, "credit untouched at AUTH")
    assert_eq(order["payment_status"], "AUTHORIZED", "still AUTHORIZED")


@test("deliver: credit drawn down at CAPTURE up to customer_total")
def t_credit_drawn_at_capture():
    c = fresh_client()
    # subtotal=5000; fee=300 (off-peak) or 500 (peak) → total ∈ {5300,5500}.
    rid, mid, cid, rrid = _make_world(c, credit_cents=10000)
    order, off = _drive_to_picked_up(c, rid, mid, cid, rrid)
    jpost(c, f"/api/assignments/{off['id']}/deliver",
          headers=rider_headers(rrid))
    o = body_of(jget(c, f"/api/orders/{order['id']}",
                     headers=admin_headers()))["data"]
    total = o["subtotal_cents"] + o["final_delivery_fee_cents"]
    cust = body_of(jget(c, f"/api/customers/{cid}",
                        headers=admin_headers()))["data"]
    assert_eq(cust["credit_balance_cents"], 10000 - total,
              "credit reduced by total")


@test("deliver: credit drawn is capped at customer total (no negative)")
def t_credit_cap_at_total():
    c = fresh_client()
    rid, mid, cid, rrid = _make_world(c, price_cents=1000, credit_cents=50000)
    order, off = _drive_to_picked_up(c, rid, mid, cid, rrid)
    jpost(c, f"/api/assignments/{off['id']}/deliver",
          headers=rider_headers(rrid))
    o = body_of(jget(c, f"/api/orders/{order['id']}",
                     headers=admin_headers()))["data"]
    total = o["subtotal_cents"] + o["final_delivery_fee_cents"]
    cust = body_of(jget(c, f"/api/customers/{cid}",
                        headers=admin_headers()))["data"]
    assert_eq(cust["credit_balance_cents"], 50000 - total, "cap honored")
    assert cust["credit_balance_cents"] >= 0, "credit never negative"


# ---------------------------------------------------------------------------
# Late fine tiers
# ---------------------------------------------------------------------------

def _set_promised_minutes_ago(order_id, mins_late):
    """Backdate promised_delivery_time so the cascade computes minutes_late."""
    import state
    from datetime import timedelta
    o = state.STORE.orders[order_id]
    o["promised_delivery_time"] = state.now() - timedelta(minutes=mins_late)


@test("late fine: 5 min late -> 200c fine, deducted from wallet")
def t_late_tier1():
    c = fresh_client()
    rid, mid, cid, rrid = _make_world(c)
    order, off = _drive_to_picked_up(c, rid, mid, cid, rrid)
    _set_promised_minutes_ago(order["id"], 5)
    jpost(c, f"/api/assignments/{off['id']}/deliver",
          headers=rider_headers(rrid))
    o = body_of(jget(c, f"/api/orders/{order['id']}",
                     headers=admin_headers()))["data"]
    rider = body_of(jget(c, f"/api/riders/{rrid}",
                         headers=rider_headers(rrid)))["data"]
    fee = o["final_delivery_fee_cents"]
    assert_eq(o["minutes_late"], 5, "5 minutes late")
    assert_eq(rider["wallet_balance_cents"], fee - 200,
              "wallet = fee - 200 fine")
    import state
    fines = [f for f in state.STORE.fines.values()
             if f["subject_id"] == rrid]
    assert_eq(len(fines), 1, "one fine")
    assert_eq(fines[0]["amount_cents"], 200, "tier-1 amount")
    assert_eq(fines[0]["reason"], "LATE_DELIVERY", "reason")


@test("late fine: 20 min late -> 500 + 50*(20-10) = 1000c")
def t_late_tier2():
    c = fresh_client()
    rid, mid, cid, rrid = _make_world(c)
    order, off = _drive_to_picked_up(c, rid, mid, cid, rrid)
    _set_promised_minutes_ago(order["id"], 20)
    jpost(c, f"/api/assignments/{off['id']}/deliver",
          headers=rider_headers(rrid))
    rider = body_of(jget(c, f"/api/riders/{rrid}",
                         headers=rider_headers(rrid)))["data"]
    o = body_of(jget(c, f"/api/orders/{order['id']}",
                     headers=admin_headers()))["data"]
    fee = o["final_delivery_fee_cents"]
    assert_eq(rider["wallet_balance_cents"], fee - 1000,
              "wallet = fee - 1000 fine")
    import state
    fine = list(state.STORE.fines.values())[0]
    assert_eq(fine["amount_cents"], 1000, "tier-2 amount")


@test("late fine: 45 min late -> min(fee,1500) + 500")
def t_late_tier3():
    c = fresh_client()
    rid, mid, cid, rrid = _make_world(c)
    order, off = _drive_to_picked_up(c, rid, mid, cid, rrid)
    _set_promised_minutes_ago(order["id"], 45)
    jpost(c, f"/api/assignments/{off['id']}/deliver",
          headers=rider_headers(rrid))
    o = body_of(jget(c, f"/api/orders/{order['id']}",
                     headers=admin_headers()))["data"]
    fee = o["final_delivery_fee_cents"]
    expected = min(fee, 1500) + 500
    rider = body_of(jget(c, f"/api/riders/{rrid}",
                         headers=rider_headers(rrid)))["data"]
    assert_eq(rider["wallet_balance_cents"], fee - expected,
              "tier-3 amount")
    import state
    fine = list(state.STORE.fines.values())[0]
    assert_eq(fine["amount_cents"], expected, "tier-3 amount")
    assert_eq(o["minutes_late"], 45, "minutes late")


@test("late fine: on-time delivery issues no fine")
def t_no_fine_on_time():
    c = fresh_client()
    rid, mid, cid, rrid = _make_world(c)
    order, off = _drive_to_picked_up(c, rid, mid, cid, rrid)
    jpost(c, f"/api/assignments/{off['id']}/deliver",
          headers=rider_headers(rrid))
    o = body_of(jget(c, f"/api/orders/{order['id']}",
                     headers=admin_headers()))["data"]
    assert_eq(o["minutes_late"], 0, "no minutes late")
    import state
    fines = [f for f in state.STORE.fines.values()
             if f["subject_id"] == rrid]
    assert_eq(len(fines), 0, "no fines")


# ---------------------------------------------------------------------------
# Bonus tier & on-time recompute
# ---------------------------------------------------------------------------

@test("rider state: returns to AVAILABLE after sole delivery")
def t_rider_available_after_delivery():
    c = fresh_client()
    rid, mid, cid, rrid = _make_world(c)
    order, off = _drive_to_picked_up(c, rid, mid, cid, rrid)
    jpost(c, f"/api/assignments/{off['id']}/deliver",
          headers=rider_headers(rrid))
    rider = body_of(jget(c, f"/api/riders/{rrid}",
                         headers=rider_headers(rrid)))["data"]
    assert_eq(rider["status"], "AVAILABLE", "back to AVAILABLE")


@test("bonus_tier: late delivery + small fine still keeps tier set")
def t_bonus_tier_set_post_delivery():
    """Single delivery doesn't move the rolling on_time_rate (needs 10),
    but bonus_tier must still be recomputed and present after delivery."""
    c = fresh_client()
    rid, mid, cid, rrid = _make_world(c)
    order, off = _drive_to_picked_up(c, rid, mid, cid, rrid)
    _set_promised_minutes_ago(order["id"], 5)
    jpost(c, f"/api/assignments/{off['id']}/deliver",
          headers=rider_headers(rrid))
    rider = body_of(jget(c, f"/api/riders/{rrid}",
                         headers=rider_headers(rrid)))["data"]
    assert rider["bonus_tier"] in ("BRONZE", "SILVER", "GOLD", "PLATINUM"), \
        "tier present"
    # on_time_rate stays 1.0 because we need ≥10 deliveries to start rolling.
    assert_eq(rider["on_time_rate"], 1.0, "fewer than 10 deliveries → 1.0")


# ---------------------------------------------------------------------------
# Route-group completion on merged deliveries
# ---------------------------------------------------------------------------

def _setup_merge_pair(c):
    """Two restaurants ~55m apart, one customer ~5km away, one rider."""
    deg = 5.0 / 111.0
    r1 = body_of(jpost(c, "/api/restaurants",
                      body={"name": "A", "address": "x",
                            "lat": 0.0, "lng": 0.0},
                      headers=admin_headers()))["data"]["id"]
    jpost(c, f"/api/restaurants/{r1}/approve", headers=admin_headers())
    r2 = body_of(jpost(c, "/api/restaurants",
                      body={"name": "B", "address": "y",
                            "lat": 0.0005, "lng": 0.0},
                      headers=admin_headers()))["data"]["id"]
    jpost(c, f"/api/restaurants/{r2}/approve", headers=admin_headers())
    m1 = body_of(jpost(c, f"/api/restaurants/{r1}/menu-items",
                      body={"name": "I", "price_cents": 1500},
                      headers=rest_headers(r1)))["data"]["id"]
    m2 = body_of(jpost(c, f"/api/restaurants/{r2}/menu-items",
                      body={"name": "I", "price_cents": 1500},
                      headers=rest_headers(r2)))["data"]["id"]
    cid = body_of(jpost(c, "/api/customers",
                       body={"name": "C", "phone": "+1",
                             "address": "z", "lat": deg, "lng": 0.0},
                       headers=admin_headers()))["data"]["id"]
    rrid = body_of(jpost(c, "/api/riders",
                        body={"name": "R", "phone": "+9"},
                        headers=admin_headers()))["data"]["id"]
    jpost(c, f"/api/riders/{rrid}/go-online", headers=rider_headers(rrid))
    return r1, r2, m1, m2, cid, rrid


@test("route group: status flips to COMPLETED when all deliveries are done")
def t_route_group_completion():
    c = fresh_client()
    r1, r2, m1, m2, cid, rrid = _setup_merge_pair(c)
    o1 = _place(c, r1, m1, cid)
    jpost(c, f"/api/orders/{o1['id']}/accept", headers=rest_headers(r1))
    jpost(c, f"/api/orders/{o1['id']}/start-preparing",
          headers=rest_headers(r1))
    off1 = _find_offer(c, o1["id"])
    jpost(c, f"/api/assignments/{off1['id']}/accept",
          headers=rider_headers(rrid))
    o2 = _place(c, r2, m2, cid)
    jpost(c, f"/api/orders/{o2['id']}/accept", headers=rest_headers(r2))
    jpost(c, f"/api/orders/{o2['id']}/start-preparing",
          headers=rest_headers(r2))
    off2 = _find_offer(c, o2["id"])
    jpost(c, f"/api/assignments/{off2['id']}/accept",
          headers=rider_headers(rrid))

    jpost(c, f"/api/orders/{o1['id']}/ready", headers=rest_headers(r1))
    jpost(c, f"/api/orders/{o2['id']}/ready", headers=rest_headers(r2))
    jpost(c, f"/api/assignments/{off1['id']}/pickup",
          headers=rider_headers(rrid))
    jpost(c, f"/api/assignments/{off2['id']}/pickup",
          headers=rider_headers(rrid))

    # Deliver only the first — group should still be ACTIVE.
    jpost(c, f"/api/assignments/{off1['id']}/deliver",
          headers=rider_headers(rrid))
    import state
    a1 = state.STORE.assignments[off1["id"]]
    rg = state.STORE.route_groups[a1["route_group_id"]]
    assert_eq(rg["status"], "ACTIVE", "still active after first delivery")

    # Deliver the second — group completes.
    jpost(c, f"/api/assignments/{off2['id']}/deliver",
          headers=rider_headers(rrid))
    rg = state.STORE.route_groups[a1["route_group_id"]]
    assert_eq(rg["status"], "COMPLETED", "completed after final delivery")


@test("rider state: stays ON_DELIVERY while a partner delivery is open")
def t_rider_stays_on_delivery_in_group():
    c = fresh_client()
    r1, r2, m1, m2, cid, rrid = _setup_merge_pair(c)
    o1 = _place(c, r1, m1, cid)
    jpost(c, f"/api/orders/{o1['id']}/accept", headers=rest_headers(r1))
    jpost(c, f"/api/orders/{o1['id']}/start-preparing",
          headers=rest_headers(r1))
    off1 = _find_offer(c, o1["id"])
    jpost(c, f"/api/assignments/{off1['id']}/accept",
          headers=rider_headers(rrid))
    o2 = _place(c, r2, m2, cid)
    jpost(c, f"/api/orders/{o2['id']}/accept", headers=rest_headers(r2))
    jpost(c, f"/api/orders/{o2['id']}/start-preparing",
          headers=rest_headers(r2))
    off2 = _find_offer(c, o2["id"])
    jpost(c, f"/api/assignments/{off2['id']}/accept",
          headers=rider_headers(rrid))

    jpost(c, f"/api/orders/{o1['id']}/ready", headers=rest_headers(r1))
    jpost(c, f"/api/orders/{o2['id']}/ready", headers=rest_headers(r2))
    jpost(c, f"/api/assignments/{off1['id']}/pickup",
          headers=rider_headers(rrid))
    jpost(c, f"/api/assignments/{off2['id']}/pickup",
          headers=rider_headers(rrid))
    jpost(c, f"/api/assignments/{off1['id']}/deliver",
          headers=rider_headers(rrid))
    rider = body_of(jget(c, f"/api/riders/{rrid}",
                         headers=rider_headers(rrid)))["data"]
    assert_eq(rider["status"], "ON_DELIVERY",
              "still on delivery (partner not done)")
    jpost(c, f"/api/assignments/{off2['id']}/deliver",
          headers=rider_headers(rrid))
    rider = body_of(jget(c, f"/api/riders/{rrid}",
                         headers=rider_headers(rrid)))["data"]
    assert_eq(rider["status"], "AVAILABLE",
              "available after final partner delivery")
