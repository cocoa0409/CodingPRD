"""Tests for §3.9 returns and refunds."""

from datetime import timedelta

from tests.harness import (
    test, fresh_client, jget, jpost, body_of,
    assert_eq, assert_err,
    admin_headers, cs_headers, cust_headers, rest_headers, rider_headers,
)


def _deliver_order(c, price_cents=5000, credit_cents=0, trust_score=1.0):
    """Build a full delivered order. Returns (rid, cid, rrid, order_id)."""
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
                             "address": "A", "lat": 0.0, "lng": 0.0},
                       headers=admin_headers()))["data"]["id"]
    import state
    if credit_cents:
        state.STORE.customers[cid]["credit_balance_cents"] = credit_cents
    state.STORE.customers[cid]["trust_score"] = trust_score
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
    jpost(c, f"/api/assignments/{a['id']}/deliver",
          headers=rider_headers(rrid))
    return rid, cid, rrid, order["id"]


# ---------------------------------------------------------------------------
# Open
# ---------------------------------------------------------------------------

@test("return open: delivered order, valid -> 201 REQUESTED, order REFUND_REQUESTED")
def t_open_valid():
    c = fresh_client()
    rid, cid, rrid, oid = _deliver_order(c, price_cents=5000)
    resp = jpost(c, f"/api/orders/{oid}/returns",
                 body={"reason": "QUALITY_ISSUE",
                       "requested_refund_cents": 1000},
                 headers=cust_headers(cid))
    assert_eq(resp.status_code, 201, "201 created")
    ret = body_of(resp)["data"]
    assert_eq(ret["status"], "REQUESTED", "status")
    assert_eq(ret["reason"], "QUALITY_ISSUE", "reason")
    order = body_of(jget(c, f"/api/orders/{oid}",
                         headers=admin_headers()))["data"]
    assert_eq(order["status"], "REFUND_REQUESTED", "order cascade")


@test("return open: not delivered -> ERR_INVALID_STATE")
def t_open_not_delivered():
    c = fresh_client()
    # Build a PLACED order and try to open a return on it
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
    order = body_of(jpost(c, "/api/orders",
                          body={"customer_id": cid, "restaurant_id": rid,
                                "items": [{"menu_item_id": mid,
                                           "quantity": 1}]},
                          headers=cust_headers(cid)))["data"]
    resp = jpost(c, f"/api/orders/{order['id']}/returns",
                 body={"reason": "QUALITY_ISSUE",
                       "requested_refund_cents": 100},
                 headers=cust_headers(cid))
    assert_err(resp, 409, "ERR_INVALID_STATE")


@test("return open: outside 24h -> ERR_RETURN_WINDOW_EXPIRED")
def t_open_window_expired():
    c = fresh_client()
    rid, cid, rrid, oid = _deliver_order(c)
    # Backdate actual_delivery_time to 25 hours ago
    import state
    state.STORE.orders[oid]["actual_delivery_time"] = \
        state.now() - timedelta(hours=25)
    resp = jpost(c, f"/api/orders/{oid}/returns",
                 body={"reason": "OTHER",
                       "requested_refund_cents": 100},
                 headers=cust_headers(cid))
    assert_err(resp, 422, "ERR_RETURN_WINDOW_EXPIRED")


@test("return open: refund > subtotal -> ERR_REFUND_AMOUNT_INVALID")
def t_open_amount_above_subtotal():
    c = fresh_client()
    rid, cid, rrid, oid = _deliver_order(c, price_cents=5000)
    resp = jpost(c, f"/api/orders/{oid}/returns",
                 body={"reason": "OTHER",
                       "requested_refund_cents": 5001},
                 headers=cust_headers(cid))
    assert_err(resp, 422, "ERR_REFUND_AMOUNT_INVALID")


@test("return open: refund < 1 -> ERR_REFUND_AMOUNT_INVALID")
def t_open_amount_zero():
    c = fresh_client()
    rid, cid, rrid, oid = _deliver_order(c)
    resp = jpost(c, f"/api/orders/{oid}/returns",
                 body={"reason": "OTHER", "requested_refund_cents": 0},
                 headers=cust_headers(cid))
    assert_err(resp, 422, "ERR_REFUND_AMOUNT_INVALID")


@test("return open: duplicate while REQUESTED -> ERR_DUPLICATE_RETURN")
def t_open_duplicate():
    c = fresh_client()
    rid, cid, rrid, oid = _deliver_order(c)
    jpost(c, f"/api/orders/{oid}/returns",
          body={"reason": "OTHER", "requested_refund_cents": 100},
          headers=cust_headers(cid))
    resp = jpost(c, f"/api/orders/{oid}/returns",
                 body={"reason": "OTHER", "requested_refund_cents": 100},
                 headers=cust_headers(cid))
    assert_err(resp, 409, "ERR_DUPLICATE_RETURN")


@test("return open: bad reason -> ERR_VALIDATION")
def t_open_bad_reason():
    c = fresh_client()
    rid, cid, rrid, oid = _deliver_order(c)
    resp = jpost(c, f"/api/orders/{oid}/returns",
                 body={"reason": "BOGUS", "requested_refund_cents": 100},
                 headers=cust_headers(cid))
    assert_err(resp, 422, "ERR_VALIDATION")


# ---------------------------------------------------------------------------
# Approve
# ---------------------------------------------------------------------------

@test("return approve: cascades order REFUNDED, payment PARTIALLY_REFUNDED")
def t_approve_partial():
    c = fresh_client()
    rid, cid, rrid, oid = _deliver_order(c, price_cents=5000)
    rret = body_of(jpost(c, f"/api/orders/{oid}/returns",
                         body={"reason": "OTHER",
                               "requested_refund_cents": 1000},
                         headers=cust_headers(cid)))["data"]
    resp = jpost(c, f"/api/returns/{rret['id']}/approve",
                 body={"approved_refund_cents": 800},
                 headers=cs_headers())
    ret = body_of(resp)["data"]
    assert_eq(ret["status"], "APPROVED", "return approved")
    assert_eq(ret["approved_refund_cents"], 800, "amount")
    o = body_of(jget(c, f"/api/orders/{oid}",
                     headers=admin_headers()))["data"]
    assert_eq(o["status"], "REFUNDED", "order refunded")
    assert_eq(o["payment_status"], "PARTIALLY_REFUNDED", "partial")


@test("return approve: full subtotal -> payment FULLY_REFUNDED")
def t_approve_full():
    c = fresh_client()
    rid, cid, rrid, oid = _deliver_order(c, price_cents=5000)
    rret = body_of(jpost(c, f"/api/orders/{oid}/returns",
                         body={"reason": "OTHER",
                               "requested_refund_cents": 5000},
                         headers=cust_headers(cid)))["data"]
    jpost(c, f"/api/returns/{rret['id']}/approve",
          body={"approved_refund_cents": 5000}, headers=cs_headers())
    o = body_of(jget(c, f"/api/orders/{oid}",
                     headers=admin_headers()))["data"]
    assert_eq(o["payment_status"], "FULLY_REFUNDED", "fully")


@test("return approve: customer credit and restaurant settlement adjust")
def t_approve_ledger():
    c = fresh_client()
    rid, cid, rrid, oid = _deliver_order(c, price_cents=5000)
    # Settlement before approval = 5000 - 750 = 4250.
    rest_before = body_of(jget(c, f"/api/restaurants/{rid}",
                               headers=admin_headers()))["data"][
        "pending_settlement_cents"]
    cust_before = body_of(jget(c, f"/api/customers/{cid}",
                               headers=admin_headers()))["data"][
        "credit_balance_cents"]
    rret = body_of(jpost(c, f"/api/orders/{oid}/returns",
                         body={"reason": "OTHER",
                               "requested_refund_cents": 1500},
                         headers=cust_headers(cid)))["data"]
    jpost(c, f"/api/returns/{rret['id']}/approve",
          body={"approved_refund_cents": 1500}, headers=cs_headers())
    rest_after = body_of(jget(c, f"/api/restaurants/{rid}",
                              headers=admin_headers()))["data"][
        "pending_settlement_cents"]
    cust_after = body_of(jget(c, f"/api/customers/{cid}",
                              headers=admin_headers()))["data"][
        "credit_balance_cents"]
    assert_eq(rest_before - rest_after, 1500, "settlement decremented")
    assert_eq(cust_after - cust_before, 1500, "credit incremented")


@test("return approve: amount > requested -> ERR_REFUND_AMOUNT_INVALID")
def t_approve_above_requested():
    c = fresh_client()
    rid, cid, rrid, oid = _deliver_order(c)
    rret = body_of(jpost(c, f"/api/orders/{oid}/returns",
                         body={"reason": "OTHER",
                               "requested_refund_cents": 500},
                         headers=cust_headers(cid)))["data"]
    resp = jpost(c, f"/api/returns/{rret['id']}/approve",
                 body={"approved_refund_cents": 600}, headers=cs_headers())
    assert_err(resp, 422, "ERR_REFUND_AMOUNT_INVALID")


@test("return approve: ABUSIVE_RETURN fine when trust<0.5 and reason=QUALITY_ISSUE")
def t_approve_abusive():
    c = fresh_client()
    rid, cid, rrid, oid = _deliver_order(
        c, price_cents=5000, credit_cents=10000, trust_score=0.3,
    )
    cust_before = body_of(jget(c, f"/api/customers/{cid}",
                               headers=admin_headers()))["data"][
        "credit_balance_cents"]
    rret = body_of(jpost(c, f"/api/orders/{oid}/returns",
                         body={"reason": "QUALITY_ISSUE",
                               "requested_refund_cents": 2000},
                         headers=cust_headers(cid)))["data"]
    jpost(c, f"/api/returns/{rret['id']}/approve",
          body={"approved_refund_cents": 2000}, headers=cs_headers())
    # Customer received 2000 credit then was fined 2000 -> net 0 change.
    cust_after = body_of(jget(c, f"/api/customers/{cid}",
                              headers=admin_headers()))["data"][
        "credit_balance_cents"]
    assert_eq(cust_after - cust_before, 0,
              "credit refunded then fined → net zero")
    import state
    cust_fines = [f for f in state.STORE.fines.values()
                  if f["subject_id"] == cid]
    assert_eq(len(cust_fines), 1, "fine created")
    assert_eq(cust_fines[0]["reason"], "ABUSIVE_RETURN", "reason")
    assert_eq(cust_fines[0]["amount_cents"], 2000, "amount = approved")


@test("return approve: no fine when reason != QUALITY_ISSUE even if trust low")
def t_approve_no_fine_other_reason():
    c = fresh_client()
    rid, cid, rrid, oid = _deliver_order(
        c, price_cents=5000, trust_score=0.2,
    )
    rret = body_of(jpost(c, f"/api/orders/{oid}/returns",
                         body={"reason": "WRONG_ITEM",
                               "requested_refund_cents": 1000},
                         headers=cust_headers(cid)))["data"]
    jpost(c, f"/api/returns/{rret['id']}/approve",
          body={"approved_refund_cents": 1000}, headers=cs_headers())
    import state
    cust_fines = [f for f in state.STORE.fines.values()
                  if f["subject_id"] == cid]
    assert_eq(len(cust_fines), 0, "no fine, wrong reason")


@test("return approve: no fine when trust >= 0.5")
def t_approve_no_fine_trust_high():
    c = fresh_client()
    rid, cid, rrid, oid = _deliver_order(
        c, price_cents=5000, trust_score=0.5,
    )
    rret = body_of(jpost(c, f"/api/orders/{oid}/returns",
                         body={"reason": "QUALITY_ISSUE",
                               "requested_refund_cents": 1000},
                         headers=cust_headers(cid)))["data"]
    jpost(c, f"/api/returns/{rret['id']}/approve",
          body={"approved_refund_cents": 1000}, headers=cs_headers())
    import state
    cust_fines = [f for f in state.STORE.fines.values()
                  if f["subject_id"] == cid]
    assert_eq(len(cust_fines), 0, "no fine — trust exactly 0.5")


# ---------------------------------------------------------------------------
# Reject
# ---------------------------------------------------------------------------

@test("return reject: order reverts REFUND_REQUESTED -> DELIVERED")
def t_reject_revert():
    c = fresh_client()
    rid, cid, rrid, oid = _deliver_order(c)
    rret = body_of(jpost(c, f"/api/orders/{oid}/returns",
                         body={"reason": "OTHER",
                               "requested_refund_cents": 500},
                         headers=cust_headers(cid)))["data"]
    resp = jpost(c, f"/api/returns/{rret['id']}/reject",
                 headers=cs_headers())
    assert_eq(body_of(resp)["data"]["status"], "REJECTED", "rejected")
    o = body_of(jget(c, f"/api/orders/{oid}",
                     headers=admin_headers()))["data"]
    assert_eq(o["status"], "DELIVERED", "back to DELIVERED")


@test("return reject: no ledger change on rejection")
def t_reject_no_ledger():
    c = fresh_client()
    rid, cid, rrid, oid = _deliver_order(c, price_cents=5000)
    cust_before = body_of(jget(c, f"/api/customers/{cid}",
                               headers=admin_headers()))["data"][
        "credit_balance_cents"]
    rest_before = body_of(jget(c, f"/api/restaurants/{rid}",
                               headers=admin_headers()))["data"][
        "pending_settlement_cents"]
    rret = body_of(jpost(c, f"/api/orders/{oid}/returns",
                         body={"reason": "OTHER",
                               "requested_refund_cents": 500},
                         headers=cust_headers(cid)))["data"]
    jpost(c, f"/api/returns/{rret['id']}/reject", headers=cs_headers())
    cust_after = body_of(jget(c, f"/api/customers/{cid}",
                              headers=admin_headers()))["data"][
        "credit_balance_cents"]
    rest_after = body_of(jget(c, f"/api/restaurants/{rid}",
                              headers=admin_headers()))["data"][
        "pending_settlement_cents"]
    assert_eq(cust_after, cust_before, "credit untouched")
    assert_eq(rest_after, rest_before, "settlement untouched")


# ---------------------------------------------------------------------------
# Escalate + reopen
# ---------------------------------------------------------------------------

@test("return escalate: opens linked WorkOrder")
def t_escalate_opens_wo():
    c = fresh_client()
    rid, cid, rrid, oid = _deliver_order(c)
    rret = body_of(jpost(c, f"/api/orders/{oid}/returns",
                         body={"reason": "OTHER",
                               "requested_refund_cents": 500},
                         headers=cust_headers(cid)))["data"]
    resp = jpost(c, f"/api/returns/{rret['id']}/escalate",
                 headers=cs_headers())
    assert_eq(body_of(resp)["data"]["status"], "ESCALATED", "escalated")
    import state
    linked = [w for w in state.STORE.work_orders.values()
              if w.get("related_return_id") == rret["id"]]
    assert_eq(len(linked), 1, "one work order linked")
    assert linked[0]["status"] in ("OPEN", "UNDER_REVIEW"), "open ticket"


@test("return reopen: ESCALATED -> REQUESTED, closes linked WorkOrder")
def t_reopen_closes_wo():
    c = fresh_client()
    rid, cid, rrid, oid = _deliver_order(c)
    rret = body_of(jpost(c, f"/api/orders/{oid}/returns",
                         body={"reason": "OTHER",
                               "requested_refund_cents": 500},
                         headers=cust_headers(cid)))["data"]
    jpost(c, f"/api/returns/{rret['id']}/escalate", headers=cs_headers())
    resp = jpost(c, f"/api/returns/{rret['id']}/reopen",
                 headers=cs_headers())
    assert_eq(body_of(resp)["data"]["status"], "REQUESTED", "reopened")
    import state
    linked = [w for w in state.STORE.work_orders.values()
              if w.get("related_return_id") == rret["id"]]
    assert_eq(linked[0]["status"], "CLOSED", "wo closed on reopen")


@test("return reopen: not legal from REQUESTED -> ERR_INVALID_STATE")
def t_reopen_from_requested_fails():
    c = fresh_client()
    rid, cid, rrid, oid = _deliver_order(c)
    rret = body_of(jpost(c, f"/api/orders/{oid}/returns",
                         body={"reason": "OTHER",
                               "requested_refund_cents": 500},
                         headers=cust_headers(cid)))["data"]
    resp = jpost(c, f"/api/returns/{rret['id']}/reopen",
                 headers=cs_headers())
    assert_err(resp, 409, "ERR_INVALID_STATE")


@test("return approve: also legal from ESCALATED")
def t_approve_from_escalated():
    c = fresh_client()
    rid, cid, rrid, oid = _deliver_order(c, price_cents=5000)
    rret = body_of(jpost(c, f"/api/orders/{oid}/returns",
                         body={"reason": "OTHER",
                               "requested_refund_cents": 800},
                         headers=cust_headers(cid)))["data"]
    jpost(c, f"/api/returns/{rret['id']}/escalate", headers=cs_headers())
    resp = jpost(c, f"/api/returns/{rret['id']}/approve",
                 body={"approved_refund_cents": 800}, headers=cs_headers())
    assert_eq(body_of(resp)["data"]["status"], "APPROVED", "approved")
    import state
    linked = [w for w in state.STORE.work_orders.values()
              if w.get("related_return_id") == rret["id"]]
    assert_eq(linked[0]["status"], "CLOSED", "wo closed on approve")
