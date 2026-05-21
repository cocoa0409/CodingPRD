"""Delivery cascade: late fine, commission reconciliation, settlement, wallet, route group."""
from .client import Client
from .fixtures import setup_basics, register_rider, place_order


def _drive_to_pickup(c, ids):
    rider = register_rider(c)
    _, body = place_order(c, ids)
    oid = body["data"]["id"]
    c.post(f"/api/orders/{oid}/accept", role="Restaurant", user_id=ids["rid"])
    c.post(f"/api/orders/{oid}/start-preparing", role="Restaurant", user_id=ids["rid"])
    from app.server import store
    aid = next(a["id"] for a in store.assignments.values() if a["order_id"] == oid and a["status"] == "OFFERED")
    c.post(f"/api/assignments/{aid}/accept", role="Rider", user_id=rider)
    c.post(f"/api/orders/{oid}/ready", role="Restaurant", user_id=ids["rid"])
    c.post(f"/api/assignments/{aid}/pickup", role="Rider", user_id=rider)
    return rider, oid, aid


def run(suite):
    def on_time_delivery_cascade():
        c, ids = setup_basics()
        rider, oid, aid = _drive_to_pickup(c, ids)
        # Deliver immediately (well before 45 min) -> minutes_late=0
        s, body = c.post(f"/api/assignments/{aid}/deliver", role="Rider", user_id=rider)
        assert s == 200
        # Order
        s, o_body = c.get(f"/api/orders/{oid}", role="PlatformAdmin", user_id="op")
        o = o_body["data"]
        assert o["status"] == "DELIVERED"
        assert o["payment_status"] == "CAPTURED"
        assert o["minutes_late"] == 0
        assert o["actual_delivery_time"] is not None
        # Final fee == solo fee for a single-leg delivery
        assert o["final_delivery_fee_cents"] is not None
        assert o["final_commission_cents"] is not None
        # Restaurant settlement = subtotal - final_commission
        s, r_body = c.get(f"/api/restaurants/{ids['rid']}", role="PlatformAdmin", user_id="op")
        assert r_body["data"]["pending_settlement_cents"] == o["subtotal_cents"] - o["final_commission_cents"]
        # Rider wallet credited
        s, r2 = c.get(f"/api/riders/{rider}", role="Rider", user_id=rider)
        assert r2["data"]["wallet_balance_cents"] == o["final_delivery_fee_cents"]
        # Rider returned to AVAILABLE (no other assignments)
        assert r2["data"]["status"] == "AVAILABLE"

    def commission_uses_override_at_delivery():
        c, ids = setup_basics(rate_override=0.10)
        rider, oid, aid = _drive_to_pickup(c, ids)
        c.post(f"/api/assignments/{aid}/deliver", role="Rider", user_id=rider)
        s, o = c.get(f"/api/orders/{oid}", role="PlatformAdmin", user_id="op")
        # subtotal 500c -> override 0.10 -> 50c
        assert o["data"]["final_commission_cents"] == 50

    def late_delivery_creates_fine():
        c, ids = setup_basics()
        rider, oid, aid = _drive_to_pickup(c, ids)
        # Advance clock past promised time by 50 minutes (45-min promise + 5 min lateness)
        c.post("/api/_clock/advance", {"seconds": 50 * 60},
               role="PlatformAdmin", user_id="op")
        s, _ = c.post(f"/api/assignments/{aid}/deliver", role="Rider", user_id=rider)
        assert s == 200
        s, o = c.get(f"/api/orders/{oid}", role="PlatformAdmin", user_id="op")
        assert o["data"]["minutes_late"] == 5
        # Fine of 200c
        s, fines = c.get("/api/fines", role="Rider", user_id=rider)
        late_fines = [f for f in fines["data"] if f["reason"] == "LATE_DELIVERY"]
        assert len(late_fines) == 1
        assert late_fines[0]["amount_cents"] == 200
        # Wallet: +final_fee then -200
        s, r = c.get(f"/api/riders/{rider}", role="Rider", user_id=rider)
        assert r["data"]["wallet_balance_cents"] == o["data"]["final_delivery_fee_cents"] - 200

    def very_late_delivery_uses_clawback_cap():
        c, ids = setup_basics()
        rider, oid, aid = _drive_to_pickup(c, ids)
        # Advance > 30 min late: 45 min promise + 31 min late = 76 min
        c.post("/api/_clock/advance", {"seconds": 76 * 60},
               role="PlatformAdmin", user_id="op")
        c.post(f"/api/assignments/{aid}/deliver", role="Rider", user_id=rider)
        s, fines = c.get("/api/fines", role="Rider", user_id=rider)
        late_fines = [f for f in fines["data"] if f["reason"] == "LATE_DELIVERY"]
        assert len(late_fines) == 1
        # fee for ~1.5km distance => 300 + 2*120 = 540 (no peak) -> capped at 540, plus 500
        # Since exact fee depends on the configured coordinates, just check the formula structure:
        s, o = c.get(f"/api/orders/{oid}", role="PlatformAdmin", user_id="op")
        fee = o["data"]["final_delivery_fee_cents"]
        expected = min(fee, 1500) + 500
        assert late_fines[0]["amount_cents"] == expected

    def deliver_requires_picked_up_status():
        c, ids = setup_basics()
        rider = register_rider(c)
        _, body = place_order(c, ids)
        oid = body["data"]["id"]
        c.post(f"/api/orders/{oid}/accept", role="Restaurant", user_id=ids["rid"])
        c.post(f"/api/orders/{oid}/start-preparing", role="Restaurant", user_id=ids["rid"])
        from app.server import store
        aid = next(a["id"] for a in store.assignments.values()
                   if a["order_id"] == oid and a["status"] == "OFFERED")
        c.post(f"/api/assignments/{aid}/accept", role="Rider", user_id=rider)
        # Skip pickup -> deliver should ERR_INVALID_STATE
        s, _ = c.post(f"/api/assignments/{aid}/deliver", role="Rider", user_id=rider)
        assert s == 409

    def merge_discount_applied_on_grouped_delivery():
        """A delivery whose assignment belongs to a RouteGroup with >=2 legs gets the 25% discount."""
        c, ids = setup_basics()
        # Second restaurant at the same coords -> merge eligible.
        _, r2 = c.post("/api/restaurants",
                       {"name": "R2", "address": "addr2", "lat": 10.0, "lng": 10.0},
                       role="PlatformAdmin", user_id="op")
        rid2 = r2["data"]["id"]
        c.post(f"/api/restaurants/{rid2}/approve", role="PlatformAdmin", user_id="op")
        _, mi2 = c.post(f"/api/restaurants/{rid2}/menu-items",
                        {"name": "fries", "price_cents": 300},
                        role="PlatformAdmin", user_id="op")
        rider = register_rider(c, phone="r-merge-deliver")
        # Order 1
        _, b1 = place_order(c, ids)
        oid1 = b1["data"]["id"]
        c.post(f"/api/orders/{oid1}/accept", role="Restaurant", user_id=ids["rid"])
        c.post(f"/api/orders/{oid1}/start-preparing", role="Restaurant", user_id=ids["rid"])
        from app.server import store
        aid1 = next(a["id"] for a in store.assignments.values()
                    if a["order_id"] == oid1 and a["status"] == "OFFERED")
        c.post(f"/api/assignments/{aid1}/accept", role="Rider", user_id=rider)
        # Order 2 — concurrent merge-eligible leg.
        _, b2 = c.post("/api/orders", {
            "customer_id": ids["cid"], "restaurant_id": rid2,
            "items": [{"menu_item_id": mi2["data"]["id"], "quantity": 1}],
        }, role="Customer", user_id=ids["cid"])
        oid2 = b2["data"]["id"]
        c.post(f"/api/orders/{oid2}/accept", role="Restaurant", user_id=rid2)
        c.post(f"/api/orders/{oid2}/start-preparing", role="Restaurant", user_id=rid2)
        aid2 = next(a["id"] for a in store.assignments.values()
                    if a["order_id"] == oid2 and a["status"] == "OFFERED")
        c.post(f"/api/assignments/{aid2}/accept", role="Rider", user_id=rider)
        # Drive both to PICKED_UP.
        for oid_, aid_, restaurant_id in ((oid1, aid1, ids["rid"]), (oid2, aid2, rid2)):
            c.post(f"/api/orders/{oid_}/ready", role="Restaurant", user_id=restaurant_id)
            c.post(f"/api/assignments/{aid_}/pickup", role="Rider", user_id=rider)
        # Deliver both
        c.post(f"/api/assignments/{aid1}/deliver", role="Rider", user_id=rider)
        c.post(f"/api/assignments/{aid2}/deliver", role="Rider", user_id=rider)
        # Verify both received merge discount.
        from app.formulas import delivery_fee_solo, merge_discount
        s, o1 = c.get(f"/api/orders/{oid1}", role="PlatformAdmin", user_id="op")
        s, o2 = c.get(f"/api/orders/{oid2}", role="PlatformAdmin", user_id="op")
        for o in (o1["data"], o2["data"]):
            solo = delivery_fee_solo(o["distance_km"], o["is_peak"])
            assert o["final_delivery_fee_cents"] == solo - merge_discount(solo)
        # Route group transitioned to COMPLETED once both legs delivered.
        groups = [g for g in store.route_groups.values() if g["rider_id"] == rider]
        assert len(groups) == 1
        assert groups[0]["status"] == "COMPLETED"

    suite.case("on-time delivery cascade: settlement + wallet + AVAILABLE", on_time_delivery_cascade)
    suite.case("commission override applied at delivery", commission_uses_override_at_delivery)
    suite.case("late delivery -> LATE_DELIVERY fine + wallet net effect", late_delivery_creates_fine)
    suite.case(">30min late uses min(fee, 1500) + 500 clawback", very_late_delivery_uses_clawback_cap)
    suite.case("deliver requires PICKED_UP", deliver_requires_picked_up_status)
    suite.case("merged delivery: 25% discount on both legs + group COMPLETED",
               merge_discount_applied_on_grouped_delivery)
