"""Work orders: open, assign, request/submit info, resolve (related-return gate), close."""
from .client import Client
from .fixtures import setup_basics, register_rider, place_order


def run(suite):
    def open_by_customer():
        c, ids = setup_basics()
        s, body = c.post("/api/work-orders",
                         {"category": "OTHER"},
                         role="Customer", user_id=ids["cid"])
        assert s == 201
        w = body["data"]
        assert w["opened_by_role"] == "CUSTOMER"
        assert w["opened_by_id"] == ids["cid"]
        assert w["status"] == "OPEN"

    def assign_under_review():
        c, ids = setup_basics()
        _, body = c.post("/api/work-orders", {"category": "OTHER"},
                          role="Customer", user_id=ids["cid"])
        wid = body["data"]["id"]
        s, body = c.post(f"/api/work-orders/{wid}/assign",
                         role="CustomerService", user_id="cs-1")
        assert s == 200
        assert body["data"]["status"] == "UNDER_REVIEW"
        assert body["data"]["assigned_cs_user_id"] == "cs-1"

    def request_and_submit_info_cycle():
        c, ids = setup_basics()
        _, body = c.post("/api/work-orders", {"category": "OTHER"},
                          role="Customer", user_id=ids["cid"])
        wid = body["data"]["id"]
        c.post(f"/api/work-orders/{wid}/assign", role="CustomerService", user_id="cs-1")
        s, _ = c.post(f"/api/work-orders/{wid}/request-info",
                      role="CustomerService", user_id="cs-1")
        assert s == 200
        # Wrong opener submitting -> ERR_FORBIDDEN
        s, _ = c.post(f"/api/work-orders/{wid}/submit-info",
                      role="Customer", user_id="other")
        assert s == 403
        # Right opener -> back to UNDER_REVIEW
        s, body = c.post(f"/api/work-orders/{wid}/submit-info",
                         role="Customer", user_id=ids["cid"])
        assert s == 200 and body["data"]["status"] == "UNDER_REVIEW"

    def resolve_blocked_by_open_related_return():
        c, ids = setup_basics()
        rider = register_rider(c)
        _, body = place_order(c, ids)
        oid = body["data"]["id"]
        # Drive to DELIVERED, open a return
        c.post(f"/api/orders/{oid}/accept", role="Restaurant", user_id=ids["rid"])
        c.post(f"/api/orders/{oid}/start-preparing", role="Restaurant", user_id=ids["rid"])
        from app.server import store
        aid = next(a["id"] for a in store.assignments.values() if a["order_id"] == oid)
        c.post(f"/api/assignments/{aid}/accept", role="Rider", user_id=rider)
        c.post(f"/api/orders/{oid}/ready", role="Restaurant", user_id=ids["rid"])
        c.post(f"/api/assignments/{aid}/pickup", role="Rider", user_id=rider)
        c.post(f"/api/assignments/{aid}/deliver", role="Rider", user_id=rider)
        _, body = c.post(f"/api/orders/{oid}/returns",
                          {"reason": "OTHER", "requested_refund_cents": 100},
                          role="Customer", user_id=ids["cid"])
        ret_id = body["data"]["id"]
        # Open a work order linked to the return
        _, body = c.post("/api/work-orders",
                          {"category": "OTHER", "related_return_id": ret_id},
                          role="CustomerService", user_id="cs-1")
        wid = body["data"]["id"]
        c.post(f"/api/work-orders/{wid}/assign", role="CustomerService", user_id="cs-1")
        # Resolve while return still REQUESTED -> ERR_RELATED_RETURN_UNRESOLVED
        s, e = c.post(f"/api/work-orders/{wid}/resolve",
                      {"resolution_notes": "done"},
                      role="CustomerService", user_id="cs-1")
        assert s == 422 and e["data"]["error_id"] == "ERR_RELATED_RETURN_UNRESOLVED"
        # Approve the return
        c.post(f"/api/returns/{ret_id}/approve",
               {"approved_refund_cents": 100},
               role="CustomerService", user_id="cs-1")
        # Now resolve succeeds
        s, body = c.post(f"/api/work-orders/{wid}/resolve",
                         {"resolution_notes": "done"},
                         role="CustomerService", user_id="cs-1")
        assert s == 200
        assert body["data"]["resolution_notes"] == "done"
        # Close
        s, body = c.post(f"/api/work-orders/{wid}/close",
                         role="CustomerService", user_id="cs-1")
        assert s == 200 and body["data"]["status"] == "CLOSED"

    def resolve_requires_assignment():
        c, ids = setup_basics()
        _, body = c.post("/api/work-orders", {"category": "OTHER"},
                          role="Customer", user_id=ids["cid"])
        wid = body["data"]["id"]
        # No assign — resolve must hit ERR_INVALID_STATE (status OPEN)
        s, e = c.post(f"/api/work-orders/{wid}/resolve",
                      {"resolution_notes": "x"},
                      role="CustomerService", user_id="cs-1")
        assert s == 409

    suite.case("open work order by customer", open_by_customer)
    suite.case("assign -> UNDER_REVIEW + assigned_cs_user_id", assign_under_review)
    suite.case("request-info / submit-info cycle (opener identity)", request_and_submit_info_cycle)
    suite.case("resolve blocked by open related return", resolve_blocked_by_open_related_return)
    suite.case("resolve requires UNDER_REVIEW/ESCALATED state", resolve_requires_assignment)
