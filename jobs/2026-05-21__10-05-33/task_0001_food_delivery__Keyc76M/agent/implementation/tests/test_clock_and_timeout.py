"""Tests for §3.6 60-second offer timeout sweep + clock advance."""

from tests.harness import (
    test, fresh_client, jget, jpost, body_of,
    assert_eq, assert_err,
    admin_headers, cust_headers, rest_headers, rider_headers,
)


def _world_with_offered(c, riders=2):
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
    for i in range(riders):
        rrid = body_of(jpost(c, "/api/riders",
                            body={"name": f"R{i}", "phone": f"+{100+i}"},
                            headers=admin_headers()))["data"]["id"]
        jpost(c, f"/api/riders/{rrid}/go-online",
              headers=rider_headers(rrid))
        rider_ids.append(rrid)
    order = body_of(jpost(c, "/api/orders",
                          body={"customer_id": cid, "restaurant_id": rid,
                                "items": [{"menu_item_id": mid,
                                           "quantity": 1}]},
                          headers=cust_headers(cid)))["data"]
    jpost(c, f"/api/orders/{order['id']}/accept", headers=rest_headers(rid))
    jpost(c, f"/api/orders/{order['id']}/start-preparing",
          headers=rest_headers(rid))
    return rid, order, rider_ids


@test("clock: advance returns updated offset")
def t_clock_basic():
    c = fresh_client()
    resp = jpost(c, "/api/_clock/advance", body={"seconds": 30},
                 headers=admin_headers())
    assert_eq(resp.status_code, 200, "ok")
    assert_eq(body_of(resp)["data"]["offset_seconds"], 30.0, "offset")


@test("clock: non-admin -> ERR_FORBIDDEN")
def t_clock_forbidden():
    c = fresh_client()
    cid = body_of(jpost(c, "/api/customers",
                       body={"name": "C", "phone": "+1",
                             "address": "A", "lat": 0, "lng": 0},
                       headers=admin_headers()))["data"]["id"]
    resp = jpost(c, "/api/_clock/advance", body={"seconds": 1},
                 headers=cust_headers(cid))
    assert_err(resp, 403, "ERR_FORBIDDEN")


@test("clock: missing seconds -> ERR_VALIDATION")
def t_clock_missing_seconds():
    c = fresh_client()
    resp = jpost(c, "/api/_clock/advance", body={},
                 headers=admin_headers())
    assert_err(resp, 422, "ERR_VALIDATION")


@test("clock: negative seconds -> ERR_VALIDATION")
def t_clock_negative():
    c = fresh_client()
    resp = jpost(c, "/api/_clock/advance", body={"seconds": -1},
                 headers=admin_headers())
    assert_err(resp, 422, "ERR_VALIDATION")


@test("offer timeout: advance 60s sweeps OFFERED to REJECTED + redispatch")
def t_offer_sweep_redispatch():
    c = fresh_client()
    rid, order, rids = _world_with_offered(c, riders=2)
    import state
    initial_offers = [
        a for a in state.STORE.assignments.values()
        if a["order_id"] == order["id"]
    ]
    assert_eq(len(initial_offers), 1, "single offer at start")
    first_id = initial_offers[0]["id"]
    first_rider = initial_offers[0]["rider_id"]

    jpost(c, "/api/_clock/advance", body={"seconds": 61},
          headers=admin_headers())

    first = state.STORE.assignments[first_id]
    assert_eq(first["status"], "REJECTED", "first offer rejected")
    fresh = [a for a in state.STORE.assignments.values()
             if a["order_id"] == order["id"] and a["status"] == "OFFERED"]
    assert_eq(len(fresh), 1, "fresh offer issued")
    assert fresh[0]["rider_id"] != first_rider, "different rider chosen"


@test("offer timeout: 59s elapsed -> not yet swept")
def t_offer_not_swept_under_60():
    c = fresh_client()
    rid, order, rids = _world_with_offered(c, riders=2)
    jpost(c, "/api/_clock/advance", body={"seconds": 59},
          headers=admin_headers())
    import state
    offered = [a for a in state.STORE.assignments.values()
               if a["order_id"] == order["id"] and a["status"] == "OFFERED"]
    assert_eq(len(offered), 1, "still pending")


@test("offer timeout: acceptance_rate drops after sweep")
def t_sweep_acceptance_rate():
    c = fresh_client()
    rid, order, rids = _world_with_offered(c, riders=2)
    import state
    offered = [a for a in state.STORE.assignments.values()
               if a["order_id"] == order["id"] and a["status"] == "OFFERED"]
    bumped_rider = offered[0]["rider_id"]
    jpost(c, "/api/_clock/advance", body={"seconds": 61},
          headers=admin_headers())
    r = state.STORE.riders[bumped_rider]
    assert r["acceptance_rate"] < 1.0, "rate dropped"


@test("offer timeout: 24h return window also driven by clock")
def t_return_window_after_advance():
    """After advancing >24h, an open-return attempt should fail with
    ERR_RETURN_WINDOW_EXPIRED."""
    c = fresh_client()
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
    rrid = body_of(jpost(c, "/api/riders",
                        body={"name": "R", "phone": "+9"},
                        headers=admin_headers()))["data"]["id"]
    jpost(c, f"/api/riders/{rrid}/go-online", headers=rider_headers(rrid))
    order = body_of(jpost(c, "/api/orders",
                          body={"customer_id": cid, "restaurant_id": rid,
                                "items": [{"menu_item_id": mid,
                                           "quantity": 1}]},
                          headers=cust_headers(cid)))["data"]
    jpost(c, f"/api/orders/{order['id']}/accept", headers=rest_headers(rid))
    jpost(c, f"/api/orders/{order['id']}/start-preparing",
          headers=rest_headers(rid))
    import state
    a = [aa for aa in state.STORE.assignments.values()
         if aa["order_id"] == order["id"]][0]
    jpost(c, f"/api/assignments/{a['id']}/accept",
          headers=rider_headers(rrid))
    jpost(c, f"/api/orders/{order['id']}/ready", headers=rest_headers(rid))
    jpost(c, f"/api/assignments/{a['id']}/pickup",
          headers=rider_headers(rrid))
    jpost(c, f"/api/assignments/{a['id']}/deliver",
          headers=rider_headers(rrid))
    # Advance 25h
    jpost(c, "/api/_clock/advance", body={"seconds": 25 * 3600},
          headers=admin_headers())
    resp = jpost(c, f"/api/orders/{order['id']}/returns",
                 body={"reason": "OTHER",
                       "requested_refund_cents": 100},
                 headers=cust_headers(cid))
    assert_err(resp, 422, "ERR_RETURN_WINDOW_EXPIRED")
