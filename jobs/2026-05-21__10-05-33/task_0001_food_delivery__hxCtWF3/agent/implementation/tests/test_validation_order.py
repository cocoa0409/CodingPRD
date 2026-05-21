"""Validation pipeline ordering (§2.6).

Priority:
 1. Auth headers
 2. Role-to-endpoint authorization
 3. Path-parameter existence (left-to-right)
 4. Body foreign-key existence
 5. Entity-identity match
 6. State-machine precondition
 7. Domain-specific safety checks (RESTAURANT_UNAVAILABLE, SUSPEND_CRITERIA_NOT_MET)
 8. Uniqueness invariants
 9. Temporal windows
10. Fiscal amount range
11. Body shape (ERR_VALIDATION / ERR_ORDER_INVALID)
12. OCC
13. Cross-entity gating (RELATED_RETURN_UNRESOLVED)
"""
from .client import Client
from .fixtures import setup_basics, register_rider, place_order


def run(suite):
    def auth_before_anything():
        # POST orders without headers — should yield ERR_AUTH_REQUIRED even though body is bogus.
        c = Client()
        s, body = c.post("/api/orders", {"items": "bogus"})
        assert s == 401 and body["data"]["error_id"] == "ERR_AUTH_REQUIRED"

    def role_before_path_existence():
        # Customer tries POST /api/restaurants — even though body is missing, RBAC fires first
        c = Client()
        s, body = c.post("/api/restaurants", {}, role="Customer", user_id="x")
        assert s == 403 and body["data"]["error_id"] == "ERR_FORBIDDEN"

    def path_left_to_right():
        # Unknown restaurant id in /api/restaurants/<rid>/menu-items
        c = Client()
        s, body = c.get("/api/restaurants/bogus/menu-items",
                        role="PlatformAdmin", user_id="op")
        assert s == 404 and body["data"]["error_id"] == "ERR_NOT_FOUND"

    def body_fk_existence():
        c, ids = setup_basics()
        # menu_item_id valid but customer_id bogus
        s, body = c.post("/api/orders", {
            "customer_id": "bogus", "restaurant_id": ids["rid"],
            "items": [{"menu_item_id": ids["mid"], "quantity": 1}],
        }, role="Customer", user_id="bogus")
        # customer_id is checked before role-identity, per pipeline step 4
        assert s == 404

    def identity_before_state_precondition():
        # A non-owner tries to accept an order
        c, ids = setup_basics()
        register_rider(c)
        _, body = place_order(c, ids)
        oid = body["data"]["id"]
        s, body = c.post(f"/api/orders/{oid}/accept",
                         role="Restaurant", user_id="wrong-restaurant")
        assert s == 403

    def state_before_domain_safety():
        # cancelling a delivered order: state machine should fire before any domain check
        c, ids = setup_basics()
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
        # Now try to cancel a DELIVERED order
        s, body = c.post(f"/api/orders/{oid}/cancel",
                         role="Customer", user_id=ids["cid"])
        assert s == 409 and body["data"]["error_id"] == "ERR_INVALID_STATE"

    def occ_after_other_checks():
        # An invalid version is meaningless when role auth fails first.
        c = Client()
        s, body = c.patch("/api/restaurants/bogus", {"version": 1, "address": "a"},
                          role="Customer", user_id="x")
        # Customer not allowed to PATCH /api/restaurants/{id} -> ERR_FORBIDDEN before NOT_FOUND
        assert s == 403

    suite.case("auth fires before any body validation", auth_before_anything)
    suite.case("role auth before path existence", role_before_path_existence)
    suite.case("path id existence checked left-to-right", path_left_to_right)
    suite.case("body foreign-key existence before identity", body_fk_existence)
    suite.case("identity mismatch before state precondition", identity_before_state_precondition)
    suite.case("state precondition before domain check", state_before_domain_safety)
    suite.case("OCC only after other checks pass", occ_after_other_checks)
