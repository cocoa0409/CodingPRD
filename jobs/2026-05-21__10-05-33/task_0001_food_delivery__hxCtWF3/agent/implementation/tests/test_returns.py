"""Returns: open, approve, reject, escalate, reopen, abusive-return fine."""
from .client import Client
from .fixtures import setup_basics, register_rider, place_order


def _to_delivered(c, ids):
    rider = register_rider(c)
    _, body = place_order(c, ids)
    oid = body["data"]["id"]
    c.post(f"/api/orders/{oid}/accept", role="Restaurant", user_id=ids["rid"])
    c.post(f"/api/orders/{oid}/start-preparing", role="Restaurant", user_id=ids["rid"])
    from app.server import store
    aid = next(a["id"] for a in store.assignments.values() if a["order_id"] == oid)
    c.post(f"/api/assignments/{aid}/accept", role="Rider", user_id=rider)
    c.post(f"/api/orders/{oid}/ready", role="Restaurant", user_id=ids["rid"])
    c.post(f"/api/assignments/{aid}/pickup", role="Rider", user_id=rider)
    c.post(f"/api/assignments/{aid}/deliver", role="Rider", user_id=rider)
    return rider, oid


def run(suite):
    def open_and_approve_full_refund():
        c, ids = setup_basics()
        rider, oid = _to_delivered(c, ids)
        # Open return for full subtotal
        s, body = c.post(f"/api/orders/{oid}/returns",
                         {"reason": "WRONG_ITEM", "requested_refund_cents": 500},
                         role="Customer", user_id=ids["cid"])
        assert s == 201
        ret_id = body["data"]["id"]
        # Order should be REFUND_REQUESTED
        s, o = c.get(f"/api/orders/{oid}", role="PlatformAdmin", user_id="op")
        assert o["data"]["status"] == "REFUND_REQUESTED"
        # Approve for full subtotal
        s, body = c.post(f"/api/returns/{ret_id}/approve",
                         {"approved_refund_cents": 500},
                         role="CustomerService", user_id="cs-1")
        assert s == 200 and body["data"]["status"] == "APPROVED"
        assert body["data"]["reviewer_cs_user_id"] == "cs-1"
        s, o = c.get(f"/api/orders/{oid}", role="PlatformAdmin", user_id="op")
        assert o["data"]["status"] == "REFUNDED"
        assert o["data"]["payment_status"] == "FULLY_REFUNDED"
        # Customer credit credited
        s, cust = c.get(f"/api/customers/{ids['cid']}", role="PlatformAdmin", user_id="op")
        assert cust["data"]["credit_balance_cents"] == 500

    def partial_refund_partial_status():
        c, ids = setup_basics()
        rider, oid = _to_delivered(c, ids)
        _, body = c.post(f"/api/orders/{oid}/returns",
                         {"reason": "QUALITY_ISSUE", "requested_refund_cents": 300},
                         role="Customer", user_id=ids["cid"])
        ret_id = body["data"]["id"]
        s, body = c.post(f"/api/returns/{ret_id}/approve",
                         {"approved_refund_cents": 300},
                         role="CustomerService", user_id="cs-1")
        s, o = c.get(f"/api/orders/{oid}", role="PlatformAdmin", user_id="op")
        assert o["data"]["payment_status"] == "PARTIALLY_REFUNDED"

    def duplicate_return_rejected():
        c, ids = setup_basics()
        rider, oid = _to_delivered(c, ids)
        c.post(f"/api/orders/{oid}/returns",
               {"reason": "WRONG_ITEM", "requested_refund_cents": 100},
               role="Customer", user_id=ids["cid"])
        s, e = c.post(f"/api/orders/{oid}/returns",
                      {"reason": "WRONG_ITEM", "requested_refund_cents": 100},
                      role="Customer", user_id=ids["cid"])
        assert s == 409 and e["data"]["error_id"] == "ERR_DUPLICATE_RETURN"

    def return_window_expired():
        c, ids = setup_basics()
        rider, oid = _to_delivered(c, ids)
        # Advance >24h
        c.post("/api/_clock/advance", {"seconds": 25 * 3600},
               role="PlatformAdmin", user_id="op")
        s, e = c.post(f"/api/orders/{oid}/returns",
                      {"reason": "OTHER", "requested_refund_cents": 100},
                      role="Customer", user_id=ids["cid"])
        assert s == 422 and e["data"]["error_id"] == "ERR_RETURN_WINDOW_EXPIRED"

    def refund_amount_invalid():
        c, ids = setup_basics()
        rider, oid = _to_delivered(c, ids)
        s, e = c.post(f"/api/orders/{oid}/returns",
                      {"reason": "OTHER", "requested_refund_cents": 0},
                      role="Customer", user_id=ids["cid"])
        assert s == 422 and e["data"]["error_id"] == "ERR_REFUND_AMOUNT_INVALID"
        s, e = c.post(f"/api/orders/{oid}/returns",
                      {"reason": "OTHER", "requested_refund_cents": 10_000},  # > subtotal
                      role="Customer", user_id=ids["cid"])
        assert s == 422 and e["data"]["error_id"] == "ERR_REFUND_AMOUNT_INVALID"

    def approve_amount_over_requested_invalid():
        c, ids = setup_basics()
        rider, oid = _to_delivered(c, ids)
        _, body = c.post(f"/api/orders/{oid}/returns",
                         {"reason": "OTHER", "requested_refund_cents": 200},
                         role="Customer", user_id=ids["cid"])
        ret_id = body["data"]["id"]
        s, e = c.post(f"/api/returns/{ret_id}/approve",
                      {"approved_refund_cents": 300},  # > requested
                      role="CustomerService", user_id="cs-1")
        assert s == 422

    def reject_reverts_order_to_delivered():
        c, ids = setup_basics()
        rider, oid = _to_delivered(c, ids)
        _, body = c.post(f"/api/orders/{oid}/returns",
                         {"reason": "OTHER", "requested_refund_cents": 100},
                         role="Customer", user_id=ids["cid"])
        ret_id = body["data"]["id"]
        s, _ = c.post(f"/api/returns/{ret_id}/reject", role="CustomerService", user_id="cs-1")
        assert s == 200
        s, o = c.get(f"/api/orders/{oid}", role="PlatformAdmin", user_id="op")
        assert o["data"]["status"] == "DELIVERED"

    def escalate_opens_workorder_reopen_closes():
        c, ids = setup_basics()
        rider, oid = _to_delivered(c, ids)
        _, body = c.post(f"/api/orders/{oid}/returns",
                         {"reason": "OTHER", "requested_refund_cents": 100},
                         role="Customer", user_id=ids["cid"])
        ret_id = body["data"]["id"]
        s, body = c.post(f"/api/returns/{ret_id}/escalate", role="CustomerService", user_id="cs-1")
        assert s == 200 and body["data"]["status"] == "ESCALATED"
        # Linked work order must exist
        from app.server import store
        linked = [w for w in store.work_orders.values() if w["related_return_id"] == ret_id]
        assert len(linked) == 1 and linked[0]["status"] == "OPEN"
        # Reopen closes it
        s, _ = c.post(f"/api/returns/{ret_id}/reopen", role="CustomerService", user_id="cs-1")
        assert s == 200
        assert linked[0]["status"] == "CLOSED"

    def abusive_return_fines_low_trust_customer():
        c, ids = setup_basics()
        rider, oid = _to_delivered(c, ids)
        # Drop customer's trust below 0.5 directly via store (no public endpoint to manipulate trust)
        from app.server import store
        store.customers[ids["cid"]]["trust_score"] = 0.4
        _, body = c.post(f"/api/orders/{oid}/returns",
                         {"reason": "QUALITY_ISSUE", "requested_refund_cents": 200},
                         role="Customer", user_id=ids["cid"])
        ret_id = body["data"]["id"]
        c.post(f"/api/returns/{ret_id}/approve",
               {"approved_refund_cents": 200},
               role="CustomerService", user_id="cs-1")
        # Fine should exist
        abusive = [f for f in store.fines.values() if f["reason"] == "ABUSIVE_RETURN"]
        assert len(abusive) == 1
        assert abusive[0]["subject_type"] == "CUSTOMER"
        assert abusive[0]["amount_cents"] == 200

    suite.case("open + approve full refund -> FULLY_REFUNDED + credit", open_and_approve_full_refund)
    suite.case("partial approve -> PARTIALLY_REFUNDED", partial_refund_partial_status)
    suite.case("duplicate return -> ERR_DUPLICATE_RETURN", duplicate_return_rejected)
    suite.case("> 24h -> ERR_RETURN_WINDOW_EXPIRED", return_window_expired)
    suite.case("refund amount out of range -> ERR_REFUND_AMOUNT_INVALID", refund_amount_invalid)
    suite.case("approved > requested -> ERR_REFUND_AMOUNT_INVALID", approve_amount_over_requested_invalid)
    suite.case("reject reverts order REFUND_REQUESTED -> DELIVERED", reject_reverts_order_to_delivered)
    suite.case("escalate opens WorkOrder, reopen closes it", escalate_opens_workorder_reopen_closes)
    suite.case("ABUSIVE_RETURN fine when trust<0.5 + QUALITY_ISSUE", abusive_return_fines_low_trust_customer)
