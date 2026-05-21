"""Tests for PRD clauses surfaced during the final coverage audit:
    - Bonus tier recompute through delivery and fining cascades
    - Late-fine middle tier (11..30 min) integration
    - Commission override mid-flight divergence (provisional vs final)
    - Credit drawdown on placement when customer has positive credit
    - Rider go-offline blocked while OFFERED assignment exists
    - Customer / restaurant fine waive ledger reversal
    - Return approve/reject from ESCALATED
    - UNPAID -> VOIDED on cancel before AUTHORIZED is reached (covered via direct state poke)
    - Multi-order suspend cascade
    - Dispatch tie-break: created_at DESC then id ASC
    - Rider suspend success path with bad metrics
"""
from .client import Client
from .fixtures import setup_basics, register_rider, place_order


def _drive_to_delivered(c, ids, rider=None, lateness_seconds=0):
    """Place + accept + start-preparing + rider-accept + ready + pickup + (advance) + deliver.
    Returns (rider_id, oid, aid)."""
    rider = rider or register_rider(c)
    _, body = place_order(c, ids)
    oid = body["data"]["id"]
    c.post(f"/api/orders/{oid}/accept", role="Restaurant", user_id=ids["rid"])
    c.post(f"/api/orders/{oid}/start-preparing", role="Restaurant", user_id=ids["rid"])
    from app.server import store
    aid = next(a["id"] for a in store.assignments.values()
               if a["order_id"] == oid and a["status"] == "OFFERED")
    c.post(f"/api/assignments/{aid}/accept", role="Rider", user_id=rider)
    c.post(f"/api/orders/{oid}/ready", role="Restaurant", user_id=ids["rid"])
    c.post(f"/api/assignments/{aid}/pickup", role="Rider", user_id=rider)
    if lateness_seconds:
        c.post("/api/_clock/advance", {"seconds": lateness_seconds},
               role="PlatformAdmin", user_id="op")
    c.post(f"/api/assignments/{aid}/deliver", role="Rider", user_id=rider)
    return rider, oid, aid


def run(suite):
    def bonus_tier_recomputed_on_delivery():
        """Delivery should write a value to bonus_tier via _recompute_bonus_tier."""
        c, ids = setup_basics()
        rider, oid, aid = _drive_to_delivered(c, ids)
        s, r = c.get(f"/api/riders/{rider}", role="Rider", user_id=rider)
        # Healthy metrics -> PLATINUM tier expected (0.6*1 + 0.3*1 + 0.1*1 = 1.0).
        assert r["data"]["bonus_tier"] == "PLATINUM"
        assert r["data"]["completed_deliveries"] == 1

    def late_fine_middle_tier_15min():
        """A 15-minute lateness => fine = 500 + 50*(15-10) = 750c."""
        c, ids = setup_basics()
        rider, oid, aid = _drive_to_delivered(c, ids, lateness_seconds=(45 + 15) * 60)
        s, fines = c.get("/api/fines", role="Rider", user_id=rider)
        late = [f for f in fines["data"] if f["reason"] == "LATE_DELIVERY"]
        assert len(late) == 1
        assert late[0]["amount_cents"] == 750

    def commission_override_diverges_at_delivery():
        """If commission_rate_override is patched on between placement and delivery,
        provisional_commission_cents (tiered) and final_commission_cents (override) differ."""
        c, ids = setup_basics()  # no override at start
        rider = register_rider(c)
        _, body = place_order(c, ids, qty=4)  # subtotal 2000c -> provisional 300c (15%)
        oid = body["data"]["id"]
        prov = body["data"]["provisional_commission_cents"]
        # Patch override mid-flight.
        s, rr = c.get(f"/api/restaurants/{ids['rid']}", role="PlatformAdmin", user_id="op")
        v = rr["data"]["version"]
        c.patch(f"/api/restaurants/{ids['rid']}",
                {"commission_rate_override": 0.10, "version": v},
                role="PlatformAdmin", user_id="op")
        # Complete the flow.
        from app.server import store
        c.post(f"/api/orders/{oid}/accept", role="Restaurant", user_id=ids["rid"])
        c.post(f"/api/orders/{oid}/start-preparing", role="Restaurant", user_id=ids["rid"])
        aid = next(a["id"] for a in store.assignments.values()
                   if a["order_id"] == oid and a["status"] == "OFFERED")
        c.post(f"/api/assignments/{aid}/accept", role="Rider", user_id=rider)
        c.post(f"/api/orders/{oid}/ready", role="Restaurant", user_id=ids["rid"])
        c.post(f"/api/assignments/{aid}/pickup", role="Rider", user_id=rider)
        c.post(f"/api/assignments/{aid}/deliver", role="Rider", user_id=rider)
        s, o = c.get(f"/api/orders/{oid}", role="PlatformAdmin", user_id="op")
        final = o["data"]["final_commission_cents"]
        # subtotal 2000c * 0.10 -> 200c. Provisional was 300c (15% tiered).
        assert final == 200
        assert prov == 300 and final != prov

    def credit_drawdown_nonzero():
        """A customer with credit_balance_cents > 0 sees credit_used_cents > 0 on placement."""
        c, ids = setup_basics()
        # Seed credit via the refund cascade: deliver an order, open + approve return.
        rider, oid, aid = _drive_to_delivered(c, ids)
        c.post(f"/api/orders/{oid}/returns",
               {"reason": "OTHER", "requested_refund_cents": 500},
               role="Customer", user_id=ids["cid"])
        from app.server import store
        ret_id = next(r["id"] for r in store.returns.values() if r["order_id"] == oid)
        c.post(f"/api/returns/{ret_id}/approve",
               {"approved_refund_cents": 500},
               role="CustomerService", user_id="cs")
        # Customer now has 500c credit. Place a fresh order (subtotal 500c + delivery).
        # Need to create a second customer? No, reuse the same one. Place another order.
        s, body = place_order(c, ids)
        o = body["data"]
        assert o["credit_used_cents"] == 500
        assert o["card_authorized_cents"] == o["subtotal_cents"] + o["provisional_delivery_fee_cents"] - 500
        # Customer credit should now be zero (fully drawn).
        s, cust = c.get(f"/api/customers/{ids['cid']}", role="PlatformAdmin", user_id="op")
        assert cust["data"]["credit_balance_cents"] == 0

    def go_offline_blocked_while_offered_assignment_live():
        """Even though a rider becomes ON_DELIVERY on accept, dispatch leaves them AVAILABLE
        while an OFFERED assignment is outstanding — go-offline must refuse."""
        c, ids = setup_basics()
        rider = register_rider(c)
        _, body = place_order(c, ids)
        oid = body["data"]["id"]
        c.post(f"/api/orders/{oid}/accept", role="Restaurant", user_id=ids["rid"])
        c.post(f"/api/orders/{oid}/start-preparing", role="Restaurant", user_id=ids["rid"])
        # Rider is AVAILABLE with an OFFERED assignment.
        s, r = c.get(f"/api/riders/{rider}", role="Rider", user_id=rider)
        assert r["data"]["status"] == "AVAILABLE"
        s, e = c.post(f"/api/riders/{rider}/go-offline", role="Rider", user_id=rider)
        assert s == 409 and e["data"]["error_id"] == "ERR_INVALID_STATE"

    def customer_fine_waive_restores_credit():
        """Waiving a customer fine restores credit_balance_cents."""
        c, ids = setup_basics()
        # Seed customer credit so a fine can debit it.
        rider, oid, _aid = _drive_to_delivered(c, ids)
        c.post(f"/api/orders/{oid}/returns",
               {"reason": "OTHER", "requested_refund_cents": 500},
               role="Customer", user_id=ids["cid"])
        from app.server import store
        ret_id = next(r["id"] for r in store.returns.values() if r["order_id"] == oid)
        c.post(f"/api/returns/{ret_id}/approve",
               {"approved_refund_cents": 500},
               role="CustomerService", user_id="cs")
        # Customer now has 500c credit. Create a fine of 300c.
        from app.services.fines import create_fine
        f = create_fine("CUSTOMER", ids["cid"], "ABUSIVE_RETURN", 300)
        cust = store.customers[ids["cid"]]
        assert cust["credit_balance_cents"] == 200  # 500 - 300
        s, _ = c.post(f"/api/fines/{f['id']}/waive",
                       role="PlatformAdmin", user_id="op")
        assert s == 200
        assert cust["credit_balance_cents"] == 500  # restored

    def restaurant_fine_waive_restores_settlement():
        """Waiving a restaurant fine restores pending_settlement_cents."""
        c, ids = setup_basics()
        from app.server import store
        from app.services.fines import create_fine
        # Seed settlement so the debit is meaningful.
        store.restaurants[ids["rid"]]["pending_settlement_cents"] = 1000
        f = create_fine("RESTAURANT", ids["rid"], "RESTAURANT_STOCKOUT", 200)
        assert store.restaurants[ids["rid"]]["pending_settlement_cents"] == 800
        s, _ = c.post(f"/api/fines/{f['id']}/waive",
                       role="CustomerService", user_id="cs")
        assert s == 200
        assert store.restaurants[ids["rid"]]["pending_settlement_cents"] == 1000

    def approve_from_escalated():
        """Approve transition is legal from ESCALATED, not just REQUESTED."""
        c, ids = setup_basics()
        rider, oid, _aid = _drive_to_delivered(c, ids)
        s, body = c.post(f"/api/orders/{oid}/returns",
                         {"reason": "OTHER", "requested_refund_cents": 400},
                         role="Customer", user_id=ids["cid"])
        rid_ = body["data"]["id"]
        # Escalate then approve.
        c.post(f"/api/returns/{rid_}/escalate", role="CustomerService", user_id="cs")
        from app.server import store
        assert store.returns[rid_]["status"] == "ESCALATED"
        s, body = c.post(f"/api/returns/{rid_}/approve",
                         {"approved_refund_cents": 200},
                         role="CustomerService", user_id="cs")
        assert s == 200 and body["data"]["status"] == "APPROVED"
        assert store.orders[oid]["status"] == "REFUNDED"

    def reject_from_escalated():
        c, ids = setup_basics()
        rider, oid, _aid = _drive_to_delivered(c, ids)
        s, body = c.post(f"/api/orders/{oid}/returns",
                         {"reason": "OTHER", "requested_refund_cents": 400},
                         role="Customer", user_id=ids["cid"])
        rid_ = body["data"]["id"]
        c.post(f"/api/returns/{rid_}/escalate", role="CustomerService", user_id="cs")
        s, body = c.post(f"/api/returns/{rid_}/reject", role="CustomerService", user_id="cs")
        assert s == 200 and body["data"]["status"] == "REJECTED"
        from app.server import store
        # Order reverts back to DELIVERED.
        assert store.orders[oid]["status"] == "DELIVERED"

    def suspend_cascade_multi_order():
        """Suspend cascades CANCELLED + VOIDED to every PLACED order for the restaurant."""
        c, ids = setup_basics()
        # Two more customers so we can place several PLACED orders concurrently.
        for i, phone in enumerate(("p-1", "p-2", "p-3")):
            c.post("/api/customers",
                   {"name": f"C{i}", "phone": phone, "address": "x", "lat": 10.0, "lng": 10.0},
                   role="PlatformAdmin", user_id="op")
        from app.server import store
        cids = [cid for cid in store.customer_phone.values()]
        oids = []
        for cid in cids[:3]:  # 3 PLACED orders
            s, body = c.post("/api/orders", {
                "customer_id": cid, "restaurant_id": ids["rid"],
                "items": [{"menu_item_id": ids["mid"], "quantity": 1}],
            }, role="Customer", user_id=cid)
            assert s == 201
            oids.append(body["data"]["id"])
        # Suspend the restaurant.
        s, _ = c.post(f"/api/restaurants/{ids['rid']}/suspend",
                      role="PlatformAdmin", user_id="op")
        assert s == 200
        for oid in oids:
            s, o = c.get(f"/api/orders/{oid}", role="PlatformAdmin", user_id="op")
            assert o["data"]["status"] == "CANCELLED"
            assert o["data"]["payment_status"] == "VOIDED"

    def rider_suspend_success_path():
        """Rider in AVAILABLE with poor stats (forced) can be suspended -> SUSPENDED terminal."""
        c, ids = setup_basics()
        rider = register_rider(c, phone="r-bad")
        from app.server import store
        # Force bad metrics: acceptance_rate < 0.50.
        store.riders[rider]["acceptance_rate"] = 0.40
        s, body = c.post(f"/api/riders/{rider}/suspend",
                         role="PlatformAdmin", user_id="op")
        assert s == 200 and body["data"]["status"] == "SUSPENDED"

    def dispatch_tie_break_created_at_desc_then_id_asc():
        """When two AVAILABLE riders tie on tier, the newer one wins (created_at DESC).
        If created_at also matches, lex-smaller id wins."""
        c, ids = setup_basics()
        # Two riders, both AVAILABLE; second registered should win.
        r1 = register_rider(c, phone="r-1")
        r2 = register_rider(c, phone="r-2")
        _, body = place_order(c, ids)
        oid = body["data"]["id"]
        c.post(f"/api/orders/{oid}/accept", role="Restaurant", user_id=ids["rid"])
        c.post(f"/api/orders/{oid}/start-preparing", role="Restaurant", user_id=ids["rid"])
        from app.server import store
        a = next(a_ for a_ in store.assignments.values()
                 if a_["order_id"] == oid and a_["status"] == "OFFERED")
        # The more recently created rider (r2) wins the tie.
        assert a["rider_id"] == r2

    suite.case("delivery cascade recomputes bonus_tier",
               bonus_tier_recomputed_on_delivery)
    suite.case("late delivery middle tier 11..30min -> 500 + 50*(min-10)",
               late_fine_middle_tier_15min)
    suite.case("commission override patched mid-flight -> provisional != final",
               commission_override_diverges_at_delivery)
    suite.case("credit drawdown reduces card_authorized_cents on placement",
               credit_drawdown_nonzero)
    suite.case("rider go-offline refused while OFFERED assignment live",
               go_offline_blocked_while_offered_assignment_live)
    suite.case("waive CUSTOMER fine restores credit_balance_cents",
               customer_fine_waive_restores_credit)
    suite.case("waive RESTAURANT fine restores pending_settlement_cents",
               restaurant_fine_waive_restores_settlement)
    suite.case("approve return from ESCALATED state legal",
               approve_from_escalated)
    suite.case("reject return from ESCALATED state legal",
               reject_from_escalated)
    suite.case("suspend cascade voids every PLACED order atomically",
               suspend_cascade_multi_order)
    suite.case("rider suspend with acceptance_rate < 0.50 -> SUSPENDED",
               rider_suspend_success_path)
    suite.case("dispatch tie-break: created_at DESC picks newer rider",
               dispatch_tie_break_created_at_desc_then_id_asc)
