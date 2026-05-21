"""Tests for §3.10 work orders and §3.11 fines + waive."""

from tests.harness import (
    test, fresh_client, jget, jpost, body_of,
    assert_eq, assert_err,
    admin_headers, cs_headers, cust_headers, rest_headers, rider_headers,
)


def _make_rider_with_fine(c, amount_cents=200):
    """Deliver an order late so a LATE_DELIVERY fine is issued."""
    from datetime import timedelta
    import state

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
    a = [aa for aa in state.STORE.assignments.values()
         if aa["order_id"] == order["id"]][0]
    jpost(c, f"/api/assignments/{a['id']}/accept",
          headers=rider_headers(rrid))
    jpost(c, f"/api/orders/{order['id']}/ready", headers=rest_headers(rid))
    jpost(c, f"/api/assignments/{a['id']}/pickup",
          headers=rider_headers(rrid))
    # Backdate promised time so 5 minutes late -> 200c
    state.STORE.orders[order["id"]]["promised_delivery_time"] = \
        state.now() - timedelta(minutes=5)
    jpost(c, f"/api/assignments/{a['id']}/deliver",
          headers=rider_headers(rrid))
    fine = [f for f in state.STORE.fines.values()
            if f["subject_id"] == rrid][0]
    return rrid, cid, fine


# ---------------------------------------------------------------------------
# Fines: read, list, scoping
# ---------------------------------------------------------------------------

@test("fines: rider reads own fine -> 200")
def t_rider_reads_own():
    c = fresh_client()
    rrid, cid, fine = _make_rider_with_fine(c)
    resp = jget(c, f"/api/fines/{fine['id']}", headers=rider_headers(rrid))
    assert_eq(resp.status_code, 200, "ok")
    assert_eq(body_of(resp)["data"]["id"], fine["id"], "same fine")


@test("fines: rider cannot read another rider's fine -> 403")
def t_rider_other_forbidden():
    c = fresh_client()
    rrid, cid, fine = _make_rider_with_fine(c)
    # Register another rider
    rrid2 = body_of(jpost(c, "/api/riders",
                         body={"name": "X", "phone": "+222"},
                         headers=admin_headers()))["data"]["id"]
    resp = jget(c, f"/api/fines/{fine['id']}", headers=rider_headers(rrid2))
    assert_err(resp, 403, "ERR_FORBIDDEN")


@test("fines: list scoped to caller for subject roles")
def t_list_scoped():
    c = fresh_client()
    rrid, cid, fine = _make_rider_with_fine(c)
    resp = jget(c, "/api/fines", headers=rider_headers(rrid))
    body = body_of(resp)
    assert_eq(resp.status_code, 200, "ok")
    assert_eq(body["data"][0]["subject_id"], rrid, "scoped")


@test("fines: list filter by subject_id mismatch -> 403 for rider")
def t_list_mismatched_filter():
    c = fresh_client()
    rrid, cid, fine = _make_rider_with_fine(c)
    resp = jget(c, "/api/fines?subject_id=other-id",
                headers=rider_headers(rrid))
    assert_err(resp, 403, "ERR_FORBIDDEN")


@test("fines: PlatformAdmin can filter any subject")
def t_admin_list_any():
    c = fresh_client()
    rrid, cid, fine = _make_rider_with_fine(c)
    resp = jget(c, f"/api/fines?subject_id={rrid}",
                headers=admin_headers())
    assert_eq(body_of(resp)["data"][0]["id"], fine["id"], "found")


# ---------------------------------------------------------------------------
# Fines: waive
# ---------------------------------------------------------------------------

@test("fines waive: PENDING fine -> WAIVED + wallet credit reversed")
def t_waive_pending():
    c = fresh_client()
    rrid, cid, fine = _make_rider_with_fine(c)
    rider_before = body_of(jget(c, f"/api/riders/{rrid}",
                                headers=rider_headers(rrid)))["data"]
    resp = jpost(c, f"/api/fines/{fine['id']}/waive", headers=cs_headers())
    assert_eq(body_of(resp)["data"]["settlement_status"], "WAIVED", "waived")
    rider_after = body_of(jget(c, f"/api/riders/{rrid}",
                               headers=rider_headers(rrid)))["data"]
    assert_eq(rider_after["wallet_balance_cents"]
              - rider_before["wallet_balance_cents"],
              fine["amount_cents"], "wallet restored")


@test("fines waive: second waive -> ERR_INVALID_STATE")
def t_waive_twice():
    c = fresh_client()
    rrid, cid, fine = _make_rider_with_fine(c)
    jpost(c, f"/api/fines/{fine['id']}/waive", headers=cs_headers())
    resp = jpost(c, f"/api/fines/{fine['id']}/waive", headers=cs_headers())
    assert_err(resp, 409, "ERR_INVALID_STATE")


@test("fines waive: rider cannot waive own fine -> ERR_FORBIDDEN")
def t_rider_cannot_waive():
    c = fresh_client()
    rrid, cid, fine = _make_rider_with_fine(c)
    resp = jpost(c, f"/api/fines/{fine['id']}/waive",
                 headers=rider_headers(rrid))
    assert_err(resp, 403, "ERR_FORBIDDEN")


# ---------------------------------------------------------------------------
# Work orders: lifecycle
# ---------------------------------------------------------------------------

def _open_customer_world(c):
    cid = body_of(jpost(c, "/api/customers",
                       body={"name": "C", "phone": "+1",
                             "address": "A", "lat": 0.0, "lng": 0.0},
                       headers=admin_headers()))["data"]["id"]
    return cid


@test("workorder: customer opens -> OPEN, opened_by recorded")
def t_wo_open():
    c = fresh_client()
    cid = _open_customer_world(c)
    resp = jpost(c, "/api/work-orders",
                 body={"category": "FOOD_QUALITY"},
                 headers=cust_headers(cid))
    assert_eq(resp.status_code, 201, "created")
    w = body_of(resp)["data"]
    assert_eq(w["status"], "OPEN", "open")
    assert_eq(w["opened_by_role"], "CUSTOMER", "role")
    assert_eq(w["opened_by_id"], cid, "id")
    assert w["assigned_cs_user_id"] is None, "no assignee"


@test("workorder: bad category -> ERR_VALIDATION")
def t_wo_bad_category():
    c = fresh_client()
    cid = _open_customer_world(c)
    resp = jpost(c, "/api/work-orders",
                 body={"category": "BOGUS"},
                 headers=cust_headers(cid))
    assert_err(resp, 422, "ERR_VALIDATION")


@test("workorder: assign by CS -> UNDER_REVIEW + assigned_cs_user_id")
def t_wo_assign():
    c = fresh_client()
    cid = _open_customer_world(c)
    w = body_of(jpost(c, "/api/work-orders",
                      body={"category": "OTHER"},
                      headers=cust_headers(cid)))["data"]
    resp = jpost(c, f"/api/work-orders/{w['id']}/assign",
                 headers=cs_headers("cs7"))
    body = body_of(resp)["data"]
    assert_eq(body["status"], "UNDER_REVIEW", "under review")
    assert_eq(body["assigned_cs_user_id"], "cs7", "cs id")


@test("workorder: request-info then submit-info cycles state")
def t_wo_info_cycle():
    c = fresh_client()
    cid = _open_customer_world(c)
    w = body_of(jpost(c, "/api/work-orders",
                      body={"category": "OTHER"},
                      headers=cust_headers(cid)))["data"]
    jpost(c, f"/api/work-orders/{w['id']}/assign", headers=cs_headers())
    resp = jpost(c, f"/api/work-orders/{w['id']}/request-info",
                 headers=cs_headers())
    assert_eq(body_of(resp)["data"]["status"], "AWAITING_INFO", "awaiting")
    resp = jpost(c, f"/api/work-orders/{w['id']}/submit-info",
                 headers=cust_headers(cid))
    assert_eq(body_of(resp)["data"]["status"], "UNDER_REVIEW", "back")


@test("workorder: submit-info by non-opener -> 403")
def t_wo_submit_wrong_user():
    c = fresh_client()
    cid = _open_customer_world(c)
    other = body_of(jpost(c, "/api/customers",
                         body={"name": "X", "phone": "+999",
                               "address": "A", "lat": 0, "lng": 0},
                         headers=admin_headers()))["data"]["id"]
    w = body_of(jpost(c, "/api/work-orders",
                      body={"category": "OTHER"},
                      headers=cust_headers(cid)))["data"]
    jpost(c, f"/api/work-orders/{w['id']}/assign", headers=cs_headers())
    jpost(c, f"/api/work-orders/{w['id']}/request-info",
          headers=cs_headers())
    resp = jpost(c, f"/api/work-orders/{w['id']}/submit-info",
                 headers=cust_headers(other))
    assert_err(resp, 403, "ERR_FORBIDDEN")


@test("workorder: resolve -> RESOLVED, then close -> CLOSED")
def t_wo_resolve_close():
    c = fresh_client()
    cid = _open_customer_world(c)
    w = body_of(jpost(c, "/api/work-orders",
                      body={"category": "OTHER"},
                      headers=cust_headers(cid)))["data"]
    jpost(c, f"/api/work-orders/{w['id']}/assign", headers=cs_headers())
    resp = jpost(c, f"/api/work-orders/{w['id']}/resolve",
                 body={"resolution_notes": "All good."},
                 headers=cs_headers())
    body = body_of(resp)["data"]
    assert_eq(body["status"], "RESOLVED", "resolved")
    assert_eq(body["resolution_notes"], "All good.", "notes")
    resp = jpost(c, f"/api/work-orders/{w['id']}/close",
                 headers=cs_headers())
    assert_eq(body_of(resp)["data"]["status"], "CLOSED", "closed")


@test("workorder: escalate UNDER_REVIEW -> ESCALATED, then resolve allowed")
def t_wo_escalate_then_resolve():
    c = fresh_client()
    cid = _open_customer_world(c)
    w = body_of(jpost(c, "/api/work-orders",
                      body={"category": "OTHER"},
                      headers=cust_headers(cid)))["data"]
    jpost(c, f"/api/work-orders/{w['id']}/assign", headers=cs_headers())
    resp = jpost(c, f"/api/work-orders/{w['id']}/escalate",
                 headers=cs_headers())
    assert_eq(body_of(resp)["data"]["status"], "ESCALATED", "escalated")
    resp = jpost(c, f"/api/work-orders/{w['id']}/resolve",
                 body={"resolution_notes": "Resolved by supervisor."},
                 headers=cs_headers())
    assert_eq(body_of(resp)["data"]["status"], "RESOLVED", "resolved")


@test("workorder: resolve without assignment -> ERR_INVALID_STATE")
def t_wo_resolve_without_assignment():
    c = fresh_client()
    cid = _open_customer_world(c)
    w = body_of(jpost(c, "/api/work-orders",
                      body={"category": "OTHER"},
                      headers=cust_headers(cid)))["data"]
    # Skip assign; go straight to resolve
    resp = jpost(c, f"/api/work-orders/{w['id']}/resolve",
                 body={"resolution_notes": "x"}, headers=cs_headers())
    assert_err(resp, 409, "ERR_INVALID_STATE")


@test("workorder: resolve with REQUESTED related_return -> ERR_RELATED_RETURN_UNRESOLVED")
def t_wo_related_return_blocks_resolve():
    """Open a work order linked to an unresolved return; resolution is gated."""
    c = fresh_client()
    # Build a delivered order
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
    # Open return
    ret = body_of(jpost(c, f"/api/orders/{order['id']}/returns",
                        body={"reason": "OTHER",
                              "requested_refund_cents": 500},
                        headers=cust_headers(cid)))["data"]
    # Open a work order linked to that return
    w = body_of(jpost(c, "/api/work-orders",
                      body={"category": "OTHER",
                            "related_return_id": ret["id"]},
                      headers=cust_headers(cid)))["data"]
    jpost(c, f"/api/work-orders/{w['id']}/assign", headers=cs_headers())
    resp = jpost(c, f"/api/work-orders/{w['id']}/resolve",
                 body={"resolution_notes": "x"}, headers=cs_headers())
    assert_err(resp, 422, "ERR_RELATED_RETURN_UNRESOLVED")
    # After return is resolved (rejected), the WO can be resolved.
    jpost(c, f"/api/returns/{ret['id']}/reject", headers=cs_headers())
    resp = jpost(c, f"/api/work-orders/{w['id']}/resolve",
                 body={"resolution_notes": "now ok"}, headers=cs_headers())
    assert_eq(body_of(resp)["data"]["status"], "RESOLVED",
              "resolves once return rejected")
