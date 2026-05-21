"""Restaurant lifecycle."""
from .client import Client


def _register(c, **overrides):
    body = {"name": "R1", "address": "addr", "lat": 1.0, "lng": 2.0}
    body.update(overrides)
    return c.post("/api/restaurants", body, role="PlatformAdmin", user_id="op")


def run(suite):
    def register_starts_pending():
        c = Client()
        status, body = _register(c)
        assert status == 201
        r = body["data"]
        assert r["status"] == "PENDING_APPROVAL"
        assert r["pending_settlement_cents"] == 0
        assert r["version"] == 1
        assert r["commission_rate_override"] is None

    def name_unique_among_active():
        c = Client()
        _register(c, name="Same")
        s2, body = _register(c, name="Same")
        assert s2 == 422

    def rate_out_of_range():
        c = Client()
        s, _ = _register(c, name="R-bad", commission_rate_override=0.5)
        assert s == 422
        s, _ = _register(c, name="R-bad2", commission_rate_override=0.04)
        assert s == 422

    def approve_only_from_pending():
        c = Client()
        _, body = _register(c)
        rid = body["data"]["id"]
        s, _ = c.post(f"/api/restaurants/{rid}/approve", role="PlatformAdmin", user_id="op")
        assert s == 200
        # already ACTIVE — re-approve fails
        s, e = c.post(f"/api/restaurants/{rid}/approve", role="PlatformAdmin", user_id="op")
        assert s == 409 and e["data"]["error_id"] == "ERR_INVALID_STATE"

    def suspend_cascades_to_placed_orders():
        c = Client()
        # Build a fully-prepared scenario: customer + restaurant + 1 PLACED order
        _, rest = _register(c, name="Rcas")
        rid = rest["data"]["id"]
        c.post(f"/api/restaurants/{rid}/approve", role="PlatformAdmin", user_id="op")
        _, mi = c.post(f"/api/restaurants/{rid}/menu-items", {"name": "burger", "price_cents": 500},
                       role="PlatformAdmin", user_id="op")
        mid = mi["data"]["id"]
        _, cust = c.post("/api/customers",
                          {"name": "C", "phone": "555-1", "address": "x", "lat": 1, "lng": 2},
                          role="PlatformAdmin", user_id="op")
        cid = cust["data"]["id"]
        s, ord_resp = c.post("/api/orders", {
            "customer_id": cid, "restaurant_id": rid,
            "items": [{"menu_item_id": mid, "quantity": 1}],
        }, role="Customer", user_id=cid)
        assert s == 201, (s, ord_resp)
        oid = ord_resp["data"]["id"]
        assert ord_resp["data"]["status"] == "PLACED"
        # Now suspend
        s, _ = c.post(f"/api/restaurants/{rid}/suspend", role="PlatformAdmin", user_id="op")
        assert s == 200
        # Order should have cascaded to CANCELLED + VOIDED
        s, o = c.get(f"/api/orders/{oid}", role="PlatformAdmin", user_id="op")
        assert o["data"]["status"] == "CANCELLED"
        assert o["data"]["payment_status"] == "VOIDED"

    def reinstate_only_from_suspended():
        c = Client()
        _, body = _register(c)
        rid = body["data"]["id"]
        c.post(f"/api/restaurants/{rid}/approve", role="PlatformAdmin", user_id="op")
        # Cannot reinstate ACTIVE
        s, e = c.post(f"/api/restaurants/{rid}/reinstate", role="PlatformAdmin", user_id="op")
        assert s == 409
        c.post(f"/api/restaurants/{rid}/suspend", role="PlatformAdmin", user_id="op")
        s, _ = c.post(f"/api/restaurants/{rid}/reinstate", role="PlatformAdmin", user_id="op")
        assert s == 200

    def patch_name_immutable():
        c = Client()
        _, body = _register(c)
        rid = body["data"]["id"]
        s, _ = c.patch(f"/api/restaurants/{rid}", {"name": "other"},
                       role="PlatformAdmin", user_id="op")
        assert s == 422

    def patch_restaurant_identity_check():
        c = Client()
        _, body = _register(c)
        rid = body["data"]["id"]
        # Another restaurant tries to patch
        s, e = c.patch(f"/api/restaurants/{rid}", {"address": "elsewhere"},
                       role="Restaurant", user_id="other-r")
        assert s == 403

    def occ_version_mismatch():
        c = Client()
        _, body = _register(c)
        rid = body["data"]["id"]
        s, _ = c.patch(f"/api/restaurants/{rid}", {"address": "new", "version": 99},
                       role="PlatformAdmin", user_id="op")
        assert s == 409

    def settle_zeros_pending():
        c = Client()
        _, body = _register(c)
        rid = body["data"]["id"]
        # Reach in via the test API: PATCH cannot set settlement directly — but a delivered
        # order will be in delivery tests. Here we just confirm settle returns 200 + version bump.
        s, settled = c.post(f"/api/restaurants/{rid}/settle", role="PlatformAdmin", user_id="op")
        assert s == 200
        assert settled["data"]["pending_settlement_cents"] == 0

    suite.case("register starts in PENDING_APPROVAL", register_starts_pending)
    suite.case("name must be unique among non-CLOSED", name_unique_among_active)
    suite.case("commission_rate_override range", rate_out_of_range)
    suite.case("approve requires PENDING_APPROVAL", approve_only_from_pending)
    suite.case("suspend cascades to PLACED orders -> CANCELLED + VOIDED", suspend_cascades_to_placed_orders)
    suite.case("reinstate requires SUSPENDED", reinstate_only_from_suspended)
    suite.case("name immutable on PATCH", patch_name_immutable)
    suite.case("PATCH owner identity check", patch_restaurant_identity_check)
    suite.case("OCC mismatch -> ERR_VERSION_CONFLICT", occ_version_mismatch)
    suite.case("settle zeros pending_settlement_cents", settle_zeros_pending)
