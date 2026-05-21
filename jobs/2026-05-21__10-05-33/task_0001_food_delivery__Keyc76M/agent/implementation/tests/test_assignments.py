"""Tests for §3.6 dispatch, accept/reject/pickup/cancel and §3.7 delivery."""

from tests.harness import (
    test, fresh_client, jget, jpost, body_of,
    assert_eq, assert_err, admin_headers, cust_headers, rest_headers, rider_headers,
)


def _bootstrap_world(c, rider_count=1):
    rid = body_of(jpost(c, "/api/restaurants",
                       body={"name": "R", "address": "A",
                             "lat": 0.0, "lng": 0.0},
                       headers=admin_headers()))["data"]["id"]
    jpost(c, f"/api/restaurants/{rid}/approve", headers=admin_headers())
    mid = body_of(jpost(c, f"/api/restaurants/{rid}/menu-items",
                       body={"name": "B", "price_cents": 5000},
                       headers=rest_headers(rid)))["data"]["id"]
    cid = body_of(jpost(c, "/api/customers",
                       body={"name": "C", "phone": "+1",
                             "address": "A", "lat": 0.0, "lng": 0.0},
                       headers=admin_headers()))["data"]["id"]
    rider_ids = []
    for i in range(rider_count):
        rrid = body_of(jpost(c, "/api/riders",
                            body={"name": f"R{i}", "phone": f"+{100+i}"},
                            headers=admin_headers()))["data"]["id"]
        jpost(c, f"/api/riders/{rrid}/go-online", headers=rider_headers(rrid))
        rider_ids.append(rrid)
    return rid, mid, cid, rider_ids


def _place_order(c, rid, mid, cid, qty=1):
    return body_of(jpost(c, "/api/orders",
                         body={"customer_id": cid, "restaurant_id": rid,
                               "items": [{"menu_item_id": mid, "quantity": qty}]},
                         headers=cust_headers(cid)))["data"]


def _advance_to_dispatch(c, rid, oid):
    jpost(c, f"/api/orders/{oid}/accept", headers=rest_headers(rid))
    jpost(c, f"/api/orders/{oid}/start-preparing", headers=rest_headers(rid))


def _find_offer(c, oid):
    """Return the most-recent OFFERED assignment for the given order."""
    import state
    cands = [
        a for a in state.STORE.assignments.values()
        if a["order_id"] == oid and a["status"] == "OFFERED"
    ]
    cands.sort(key=lambda a: a["offered_at"], reverse=True)
    return cands[0] if cands else None


@test("dispatch: start-preparing opens an OFFERED assignment")
def t_dispatch_opens_offer():
    c = fresh_client()
    rid, mid, cid, [r1] = _bootstrap_world(c, rider_count=1)
    order = _place_order(c, rid, mid, cid)
    _advance_to_dispatch(c, rid, order["id"])
    offer = _find_offer(c, order["id"])
    assert offer is not None, "offer created"
    assert_eq(offer["rider_id"], r1, "candidate rider id")


@test("accept: rider accepts and goes ON_DELIVERY")
def t_accept_basic():
    c = fresh_client()
    rid, mid, cid, [r1] = _bootstrap_world(c, rider_count=1)
    order = _place_order(c, rid, mid, cid)
    _advance_to_dispatch(c, rid, order["id"])
    offer = _find_offer(c, order["id"])
    resp = jpost(c, f"/api/assignments/{offer['id']}/accept",
                 headers=rider_headers(r1))
    assert_eq(body_of(resp)["data"]["status"], "ACCEPTED", "accepted")
    rider = body_of(jget(c, f"/api/riders/{r1}", headers=rider_headers(r1)))["data"]
    assert_eq(rider["status"], "ON_DELIVERY", "rider ON_DELIVERY")


@test("accept: second accept on duplicate offer -> ERR_ORDER_ALREADY_ASSIGNED")
def t_already_assigned():
    c = fresh_client()
    rid, mid, cid, [r1, r2] = _bootstrap_world(c, rider_count=2)
    order = _place_order(c, rid, mid, cid)
    _advance_to_dispatch(c, rid, order["id"])
    first = _find_offer(c, order["id"])
    # Create a second offer for the same order (admin-triggered).
    jpost(c, f"/api/orders/{order['id']}/dispatch", headers=admin_headers())
    # Accept the first.
    jpost(c, f"/api/assignments/{first['id']}/accept",
          headers=rider_headers(first["rider_id"]))
    # Try to accept the second.
    import state
    other_offers = [a for a in state.STORE.assignments.values()
                    if a["order_id"] == order["id"] and a["status"] == "OFFERED"]
    assert other_offers, "second OFFERED exists"
    second = other_offers[0]
    resp = jpost(c, f"/api/assignments/{second['id']}/accept",
                 headers=rider_headers(second["rider_id"]))
    assert_err(resp, 409, "ERR_ORDER_ALREADY_ASSIGNED")


@test("reject: explicit reject creates a new offer (redispatch)")
def t_reject_redispatch():
    c = fresh_client()
    rid, mid, cid, [r1, r2] = _bootstrap_world(c, rider_count=2)
    order = _place_order(c, rid, mid, cid)
    _advance_to_dispatch(c, rid, order["id"])
    offer = _find_offer(c, order["id"])
    resp = jpost(c, f"/api/assignments/{offer['id']}/reject",
                 headers=rider_headers(offer["rider_id"]))
    assert_eq(body_of(resp)["data"]["status"], "REJECTED", "rejected")
    new_offer = _find_offer(c, order["id"])
    assert new_offer is not None, "redispatched offer exists"
    assert_eq(new_offer["status"], "OFFERED", "fresh offer")
    assert new_offer["id"] != offer["id"], "new offer id"


@test("pickup + deliver: full happy path with on-time arrival")
def t_pickup_and_deliver():
    c = fresh_client()
    rid, mid, cid, [r1] = _bootstrap_world(c, rider_count=1)
    order = _place_order(c, rid, mid, cid)
    _advance_to_dispatch(c, rid, order["id"])
    offer = _find_offer(c, order["id"])
    jpost(c, f"/api/assignments/{offer['id']}/accept", headers=rider_headers(r1))
    jpost(c, f"/api/orders/{order['id']}/ready", headers=rest_headers(rid))
    jpost(c, f"/api/assignments/{offer['id']}/pickup", headers=rider_headers(r1))
    resp = jpost(c, f"/api/assignments/{offer['id']}/deliver",
                 headers=rider_headers(r1))
    a = body_of(resp)["data"]
    assert_eq(a["status"], "DELIVERED", "delivered")
    o = body_of(jget(c, f"/api/orders/{order['id']}",
                     headers=admin_headers()))["data"]
    assert_eq(o["status"], "DELIVERED", "order delivered")
    assert_eq(o["payment_status"], "CAPTURED", "captured")
    # Same coords -> solo fee = 300; assume not peak in tests
    # final_delivery_fee_cents should equal solo fee
    assert o["final_delivery_fee_cents"] in (300, 500), \
        "fee 300 off-peak or 500 in-peak"
    # subtotal=5000 -> commission tier1 = 5000*0.15 = 750
    assert_eq(o["final_commission_cents"], 750, "final commission")
    # Restaurant got subtotal - commission
    r = body_of(jget(c, f"/api/restaurants/{rid}",
                     headers=admin_headers()))["data"]
    assert_eq(r["pending_settlement_cents"], 5000 - 750, "settlement")
    rider = body_of(jget(c, f"/api/riders/{r1}",
                         headers=rider_headers(r1)))["data"]
    assert rider["wallet_balance_cents"] == o["final_delivery_fee_cents"], \
        "wallet credited"


@test("cancel: rider abandons accepted -> RIDER_NO_SHOW fine 500c, redispatch")
def t_rider_cancel():
    c = fresh_client()
    rid, mid, cid, [r1, r2] = _bootstrap_world(c, rider_count=2)
    order = _place_order(c, rid, mid, cid)
    _advance_to_dispatch(c, rid, order["id"])
    offer = _find_offer(c, order["id"])
    candidate = offer["rider_id"]
    jpost(c, f"/api/assignments/{offer['id']}/accept",
          headers=rider_headers(candidate))
    resp = jpost(c, f"/api/assignments/{offer['id']}/cancel",
                 headers=rider_headers(candidate))
    a = body_of(resp)["data"]
    assert_eq(a["status"], "CANCELLED", "cancelled")
    rider = body_of(jget(c, f"/api/riders/{candidate}",
                         headers=rider_headers(candidate)))["data"]
    assert_eq(rider["wallet_balance_cents"], -500, "wallet -500")
    new_offer = _find_offer(c, order["id"])
    assert new_offer is not None, "redispatch happened"
    assert new_offer["id"] != offer["id"], "different assignment"


@test("rider: cannot go offline while ACCEPTED -> ERR_INVALID_STATE")
def t_rider_no_offline_during_delivery():
    c = fresh_client()
    rid, mid, cid, [r1] = _bootstrap_world(c, rider_count=1)
    order = _place_order(c, rid, mid, cid)
    _advance_to_dispatch(c, rid, order["id"])
    offer = _find_offer(c, order["id"])
    candidate = offer["rider_id"]
    jpost(c, f"/api/assignments/{offer['id']}/accept",
          headers=rider_headers(candidate))
    resp = jpost(c, f"/api/riders/{candidate}/go-offline",
                 headers=rider_headers(candidate))
    assert_err(resp, 409, "ERR_INVALID_STATE")
