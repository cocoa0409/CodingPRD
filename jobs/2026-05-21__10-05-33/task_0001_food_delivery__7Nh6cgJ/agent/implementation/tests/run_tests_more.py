"""More self-tests — covering boundary cases and remaining PRD rules."""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from tests.harness import TestClient, TestRunner

NYC = (40.7128, -74.0060)
NEAR_NYC = (40.7129, -74.0061)
FAR_NYC = (40.7228, -74.0060)
VERY_FAR_NYC = (41.0000, -73.5000)  # ~62km away — high fee bands

CLIENT = TestClient()
R = TestRunner()


# --- helpers (same as run_tests_extra) ---
def register_active_restaurant(name="R", coords=NYC, commission_override=None):
    s, b = CLIENT.request("POST", "/api/restaurants", role="PlatformAdmin", user_id="admin",
                          body={"name": name, "address": "1 a", "lat": coords[0], "lng": coords[1],
                                "commission_rate_override": commission_override})
    rid = b["data"]["id"]
    CLIENT.request("POST", f"/api/restaurants/{rid}/approve",
                   role="PlatformAdmin", user_id="admin")
    return b["data"]


def register_customer(phone="555", coords=NEAR_NYC):
    s, b = CLIENT.request("POST", "/api/customers", role="PlatformAdmin", user_id="admin",
                          body={"name": "C", "phone": phone, "address": "x",
                                "lat": coords[0], "lng": coords[1]})
    return b["data"]


def register_rider(phone="r"):
    s, b = CLIENT.request("POST", "/api/riders", role="PlatformAdmin", user_id="admin",
                          body={"name": "R", "phone": phone})
    return b["data"]


def online(rider):
    CLIENT.request("POST", f"/api/riders/{rider['id']}/go-online",
                   role="Rider", user_id=rider["id"])


def add_menu(rid, price=2000, name="X"):
    s, b = CLIENT.request("POST", f"/api/restaurants/{rid}/menu-items",
                          role="Restaurant", user_id=rid,
                          body={"name": name, "price_cents": price})
    return b["data"]


def place_order(cid, rid, items):
    s, b = CLIENT.request("POST", "/api/orders", role="Customer", user_id=cid,
                          body={"customer_id": cid, "restaurant_id": rid, "items": items})
    return b["data"]


def advance(s):
    CLIENT.request("POST", "/api/_clock/advance", role="PlatformAdmin", user_id="admin",
                   body={"seconds": s})


def full_deliver(customer, restaurant, rider, price=2000, qty=1, late_seconds=0):
    m = add_menu(restaurant["id"], price=price)
    o = place_order(customer["id"], restaurant["id"], [{"menu_item_id": m["id"], "quantity": qty}])
    CLIENT.request("POST", f"/api/orders/{o['id']}/accept",
                   role="Restaurant", user_id=restaurant["id"])
    CLIENT.request("POST", f"/api/orders/{o['id']}/start-preparing",
                   role="Restaurant", user_id=restaurant["id"])
    from store import STORE
    aid = next(a["id"] for a in STORE.assignments.values()
                if a["order_id"] == o["id"] and a["status"] == "OFFERED")
    CLIENT.request("POST", f"/api/assignments/{aid}/accept", role="Rider", user_id=rider["id"])
    CLIENT.request("POST", f"/api/orders/{o['id']}/ready",
                   role="Restaurant", user_id=restaurant["id"])
    CLIENT.request("POST", f"/api/assignments/{aid}/pickup", role="Rider", user_id=rider["id"])
    if late_seconds:
        advance(45 * 60 + late_seconds)
    CLIENT.request("POST", f"/api/assignments/{aid}/deliver", role="Rider", user_id=rider["id"])
    return o, aid


# === Late delivery boundaries ===
def t_late_exactly_1():
    CLIENT.reset()
    r = register_active_restaurant(); c = register_customer(); rd = register_rider(); online(rd)
    o, aid = full_deliver(c, r, rd, late_seconds=60)  # 1 min late
    from store import STORE
    fines = [f for f in STORE.fines.values() if f["reason"] == "LATE_DELIVERY"]
    assert len(fines) == 1 and fines[0]["amount_cents"] == 200


def t_late_exactly_10():
    CLIENT.reset()
    r = register_active_restaurant(); c = register_customer(); rd = register_rider(); online(rd)
    o, aid = full_deliver(c, r, rd, late_seconds=10 * 60)
    from store import STORE
    fines = [f for f in STORE.fines.values() if f["reason"] == "LATE_DELIVERY"]
    assert len(fines) == 1 and fines[0]["amount_cents"] == 200, fines[0]


def t_late_exactly_11():
    CLIENT.reset()
    r = register_active_restaurant(); c = register_customer(); rd = register_rider(); online(rd)
    o, aid = full_deliver(c, r, rd, late_seconds=11 * 60)
    from store import STORE
    fines = [f for f in STORE.fines.values() if f["reason"] == "LATE_DELIVERY"]
    # tier 2: 500 + 50*(11-10) = 550
    assert fines[0]["amount_cents"] == 550


def t_late_exactly_30():
    CLIENT.reset()
    r = register_active_restaurant(); c = register_customer(); rd = register_rider(); online(rd)
    o, aid = full_deliver(c, r, rd, late_seconds=30 * 60)
    from store import STORE
    fines = [f for f in STORE.fines.values() if f["reason"] == "LATE_DELIVERY"]
    # tier 2 cap: 500 + 50*20 = 1500
    assert fines[0]["amount_cents"] == 1500, fines[0]


def t_late_exactly_31():
    CLIENT.reset()
    r = register_active_restaurant(); c = register_customer(); rd = register_rider(); online(rd)
    o, aid = full_deliver(c, r, rd, late_seconds=31 * 60)
    from store import STORE
    fines = [f for f in STORE.fines.values() if f["reason"] == "LATE_DELIVERY"]
    # tier 3: min(final_fee, 1500) + 500 = min(300/500, 1500) + 500
    assert fines[0]["amount_cents"] in (300 + 500, 500 + 500)


def t_late_fee_above_1500_cap():
    """For a long-distance order with final_delivery_fee_cents > 1500, the clawback caps at 1500."""
    CLIENT.reset()
    # 0.7228, -74.006 vs 41.0, -73.5 → far ~ many km. Let's compute: lat diff 0.27..., lng diff 0.5+
    # Use VERY_FAR_NYC as customer
    r = register_active_restaurant(coords=NYC)
    c = register_customer(coords=VERY_FAR_NYC)
    rd = register_rider(); online(rd)
    o, aid = full_deliver(c, r, rd, late_seconds=31 * 60)
    from store import STORE
    fines = [f for f in STORE.fines.values() if f["reason"] == "LATE_DELIVERY"]
    # The final delivery fee for ~62km is large; clawback caps at 1500.
    # fine = 1500 + 500 = 2000
    assert fines[0]["amount_cents"] == 2000, (fines[0], STORE.orders[o["id"]]["final_delivery_fee_cents"])


# === Commission tier boundary ===
def t_commission_at_50000_boundary():
    from pricing import tiered_commission_cents
    # subtotal exactly 50000: 20000*.15 + 30000*.18 = 3000 + 5400 = 8400
    assert tiered_commission_cents(50_000) == 8400
    # subtotal 50001: 20000*.15 + 30000*.18 + 1*.22 = 3000 + 5400 + 0.22 → round half-up to 8404
    # Wait: 0.22 rounds to 0 (half-up). So result is 8400. Let me reconsider.
    # 0.22 → round half-up to integer = 0 (since 0.22 < 0.5)
    # So total = 8400.22 → 8400
    assert tiered_commission_cents(50_001) == 8400


def t_commission_half_up_rounding():
    from pricing import tiered_commission_cents
    # find a subtotal whose tiered total ends in .5: e.g., subtotal 100 → 100*.15 = 15. No fraction.
    # try 13 cents: 13*.15 = 1.95 → 2 (half-up)
    # Wait we need subtotal >= 100. Try 103: 103*.15 = 15.45 → 15
    # try 107: 16.05 → 16 (since .05 < .5, hmm round-half-up at .05 makes 16 only when .05 is treated as >= .5 — no .05 < .5 → 16)
    # Half-up: 16.05 → 16 (because .05 rounds down? no — .05 is less than .5, rounds down)
    # Wait the half-up rule applies to the .5 boundary. So 16.05 → 16 (because .05 < .5), 16.5 → 17.
    # Just verify: subtotal 110, 110*.15 = 16.5 → 17 (half-up)
    assert tiered_commission_cents(110) == 17


# === Trust score boundary ===
def t_trust_score_exact_0_5_no_abusive_fine():
    CLIENT.reset()
    r = register_active_restaurant(); c = register_customer(); rd = register_rider(); online(rd)
    from store import STORE
    STORE.customers[c["id"]]["trust_score"] = 0.5  # exactly 0.5: NOT strictly less than
    o, aid = full_deliver(c, r, rd, price=2000)
    s, b = CLIENT.request("POST", f"/api/orders/{o['id']}/returns",
                          role="Customer", user_id=c["id"],
                          body={"reason": "QUALITY_ISSUE", "requested_refund_cents": 500})
    rid = b["data"]["id"]
    CLIENT.request("POST", f"/api/returns/{rid}/approve",
                   role="CustomerService", user_id="cs-1",
                   body={"approved_refund_cents": 500})
    s, fb = CLIENT.request("GET", f"/api/fines?subject_type=CUSTOMER&subject_id={c['id']}",
                           role="PlatformAdmin", user_id="admin")
    assert len(fb["data"]) == 0


def t_abusive_only_on_quality_issue():
    CLIENT.reset()
    r = register_active_restaurant(); c = register_customer(); rd = register_rider(); online(rd)
    from store import STORE
    STORE.customers[c["id"]]["trust_score"] = 0.3
    o, aid = full_deliver(c, r, rd, price=2000)
    s, b = CLIENT.request("POST", f"/api/orders/{o['id']}/returns",
                          role="Customer", user_id=c["id"],
                          body={"reason": "WRONG_ITEM", "requested_refund_cents": 500})
    rid = b["data"]["id"]
    CLIENT.request("POST", f"/api/returns/{rid}/approve",
                   role="CustomerService", user_id="cs-1",
                   body={"approved_refund_cents": 500})
    s, fb = CLIENT.request("GET", f"/api/fines?subject_type=CUSTOMER&subject_id={c['id']}",
                           role="PlatformAdmin", user_id="admin")
    assert len(fb["data"]) == 0


# === Restaurant settlement decrement on approved return ===
def t_restaurant_settlement_decrement_on_return():
    CLIENT.reset()
    r = register_active_restaurant(); c = register_customer(); rd = register_rider(); online(rd)
    o, aid = full_deliver(c, r, rd, price=2000)
    # After delivery, restaurant has 2000 - 300 = 1700 pending.
    s, rest = CLIENT.request("GET", f"/api/restaurants/{r['id']}",
                             role="PlatformAdmin", user_id="admin")
    assert rest["data"]["pending_settlement_cents"] == 1700
    s, b = CLIENT.request("POST", f"/api/orders/{o['id']}/returns",
                          role="Customer", user_id=c["id"],
                          body={"reason": "OTHER", "requested_refund_cents": 500})
    rid = b["data"]["id"]
    CLIENT.request("POST", f"/api/returns/{rid}/approve",
                   role="CustomerService", user_id="cs-1",
                   body={"approved_refund_cents": 500})
    s, rest = CLIENT.request("GET", f"/api/restaurants/{r['id']}",
                             role="PlatformAdmin", user_id="admin")
    assert rest["data"]["pending_settlement_cents"] == 1700 - 500


# === Fine waive variations ===
def t_late_delivery_fine_waive_credits_back():
    CLIENT.reset()
    r = register_active_restaurant(); c = register_customer(); rd = register_rider(); online(rd)
    o, aid = full_deliver(c, r, rd, price=2000, late_seconds=5 * 60)
    from store import STORE
    fine = next(f for f in STORE.fines.values() if f["reason"] == "LATE_DELIVERY")
    s, rb = CLIENT.request("GET", f"/api/riders/{rd['id']}", role="PlatformAdmin", user_id="admin")
    wallet_before = rb["data"]["wallet_balance_cents"]
    s, _ = CLIENT.request("POST", f"/api/fines/{fine['id']}/waive",
                          role="PlatformAdmin", user_id="admin")
    s, rb2 = CLIENT.request("GET", f"/api/riders/{rd['id']}", role="PlatformAdmin", user_id="admin")
    assert rb2["data"]["wallet_balance_cents"] == wallet_before + 200


def t_abusive_fine_waive_restores_credit():
    CLIENT.reset()
    r = register_active_restaurant(); c = register_customer(); rd = register_rider(); online(rd)
    from store import STORE
    STORE.customers[c["id"]]["trust_score"] = 0.3
    o, aid = full_deliver(c, r, rd, price=2000)
    s, b = CLIENT.request("POST", f"/api/orders/{o['id']}/returns",
                          role="Customer", user_id=c["id"],
                          body={"reason": "QUALITY_ISSUE", "requested_refund_cents": 500})
    rid = b["data"]["id"]
    CLIENT.request("POST", f"/api/returns/{rid}/approve",
                   role="CustomerService", user_id="cs-1",
                   body={"approved_refund_cents": 500})
    # After approval: customer.credit = 500 (refund), then -500 (fine) = 0
    s, cb = CLIENT.request("GET", f"/api/customers/{c['id']}", role="PlatformAdmin", user_id="admin")
    assert cb["data"]["credit_balance_cents"] == 0
    fine = next(f for f in STORE.fines.values() if f["reason"] == "ABUSIVE_RETURN")
    CLIENT.request("POST", f"/api/fines/{fine['id']}/waive",
                   role="PlatformAdmin", user_id="admin")
    s, cb = CLIENT.request("GET", f"/api/customers/{c['id']}", role="PlatformAdmin", user_id="admin")
    assert cb["data"]["credit_balance_cents"] == 500


# === Return reopen state ===
def t_return_reopen_only_from_escalated():
    CLIENT.reset()
    r = register_active_restaurant(); c = register_customer(); rd = register_rider(); online(rd)
    o, aid = full_deliver(c, r, rd, price=2000)
    s, b = CLIENT.request("POST", f"/api/orders/{o['id']}/returns",
                          role="Customer", user_id=c["id"],
                          body={"reason": "OTHER", "requested_refund_cents": 100})
    rid = b["data"]["id"]
    # Currently REQUESTED — reopen should fail.
    s, _ = CLIENT.request("POST", f"/api/returns/{rid}/reopen",
                          role="CustomerService", user_id="cs-1")
    assert s == 409


# === WorkOrder ===
def t_wo_escalated_then_resolved():
    CLIENT.reset()
    c = register_customer()
    s, b = CLIENT.request("POST", "/api/work-orders", role="Customer", user_id=c["id"],
                          body={"category": "OTHER"})
    wid = b["data"]["id"]
    CLIENT.request("POST", f"/api/work-orders/{wid}/assign",
                   role="CustomerService", user_id="cs-1")
    CLIENT.request("POST", f"/api/work-orders/{wid}/escalate",
                   role="CustomerService", user_id="cs-1")
    s, b = CLIENT.request("POST", f"/api/work-orders/{wid}/resolve",
                          role="CustomerService", user_id="cs-1",
                          body={"resolution_notes": "fixed"})
    assert s == 200 and b["data"]["status"] == "RESOLVED"


def t_wo_resolve_blocked_when_return_requested():
    CLIENT.reset()
    r = register_active_restaurant(); c = register_customer(); rd = register_rider(); online(rd)
    o, aid = full_deliver(c, r, rd, price=2000)
    s, b = CLIENT.request("POST", f"/api/orders/{o['id']}/returns",
                          role="Customer", user_id=c["id"],
                          body={"reason": "OTHER", "requested_refund_cents": 100})
    rid = b["data"]["id"]
    # Open WO referring to this return without escalating.
    s, b = CLIENT.request("POST", "/api/work-orders", role="CustomerService", user_id="cs-1",
                          body={"category": "OTHER", "related_return_id": rid})
    wid = b["data"]["id"]
    CLIENT.request("POST", f"/api/work-orders/{wid}/assign",
                   role="CustomerService", user_id="cs-1")
    s, b = CLIENT.request("POST", f"/api/work-orders/{wid}/resolve",
                          role="CustomerService", user_id="cs-1",
                          body={"resolution_notes": "x"})
    assert s == 422 and b["data"]["error_id"] == "ERR_RELATED_RETURN_UNRESOLVED"


def t_wo_submit_info_opener_mismatch():
    CLIENT.reset()
    c1 = register_customer("p1")
    c2 = register_customer("p2")
    s, b = CLIENT.request("POST", "/api/work-orders", role="Customer", user_id=c1["id"],
                          body={"category": "OTHER"})
    wid = b["data"]["id"]
    CLIENT.request("POST", f"/api/work-orders/{wid}/assign",
                   role="CustomerService", user_id="cs-1")
    CLIENT.request("POST", f"/api/work-orders/{wid}/request-info",
                   role="CustomerService", user_id="cs-1")
    s, b = CLIENT.request("POST", f"/api/work-orders/{wid}/submit-info",
                          role="Customer", user_id=c2["id"])
    assert s == 403


# === Solo delivery no merge discount ===
def t_solo_delivery_no_discount():
    CLIENT.reset()
    r = register_active_restaurant(coords=NYC)
    c = register_customer(coords=FAR_NYC)
    rd = register_rider(); online(rd)
    o, aid = full_deliver(c, r, rd, price=2000)
    s, ob = CLIENT.request("GET", f"/api/orders/{o['id']}",
                           role="PlatformAdmin", user_id="admin")
    # distance: ~1.11 km → ceil(1.1) = 2 bands → 300 + 240 = 540 (off-peak) or 740 (peak)
    fee = ob["data"]["final_delivery_fee_cents"]
    assert fee in (540, 740), fee
    # No route_group_id should be set for solo
    s, ab = CLIENT.request("GET", f"/api/assignments/{aid}",
                           role="PlatformAdmin", user_id="admin")
    assert ab["data"]["route_group_id"] is None


# === Route merge: full flow with 2 close orders ===
def t_route_merge_two_orders():
    CLIENT.reset()
    # Two restaurants near each other
    r1 = register_active_restaurant(name="R1", coords=(40.7128, -74.0060))
    r2 = register_active_restaurant(name="R2", coords=(40.7130, -74.0062))  # ~24m away
    c1 = register_customer("p1", coords=(40.7200, -74.0100))
    c2 = register_customer("p2", coords=(40.7210, -74.0110))
    rd = register_rider(); online(rd)
    m1 = add_menu(r1["id"], name="A", price=2000)
    m2 = add_menu(r2["id"], name="B", price=2000)

    o1 = place_order(c1["id"], r1["id"], [{"menu_item_id": m1["id"], "quantity": 1}])
    CLIENT.request("POST", f"/api/orders/{o1['id']}/accept", role="Restaurant", user_id=r1["id"])
    CLIENT.request("POST", f"/api/orders/{o1['id']}/start-preparing",
                   role="Restaurant", user_id=r1["id"])
    from store import STORE
    aid1 = next(a["id"] for a in STORE.assignments.values() if a["order_id"] == o1["id"])
    CLIENT.request("POST", f"/api/assignments/{aid1}/accept", role="Rider", user_id=rd["id"])

    # Now rider is ON_DELIVERY. Place a second order for r2 (within 500m of r1).
    o2 = place_order(c2["id"], r2["id"], [{"menu_item_id": m2["id"], "quantity": 1}])
    CLIENT.request("POST", f"/api/orders/{o2['id']}/accept", role="Restaurant", user_id=r2["id"])
    CLIENT.request("POST", f"/api/orders/{o2['id']}/start-preparing",
                   role="Restaurant", user_id=r2["id"])
    # Rider should be candidate (the only one)
    aid2 = next(a["id"] for a in STORE.assignments.values() if a["order_id"] == o2["id"])
    CLIENT.request("POST", f"/api/assignments/{aid2}/accept", role="Rider", user_id=rd["id"])
    # After accept, route group should exist with both assignments.
    a2 = STORE.assignments[aid2]
    assert a2["route_group_id"] is not None
    group = STORE.route_groups[a2["route_group_id"]]
    assert len(group["assignment_ids"]) == 2

    # Ready + pickup + deliver both.
    CLIENT.request("POST", f"/api/orders/{o1['id']}/ready", role="Restaurant", user_id=r1["id"])
    CLIENT.request("POST", f"/api/assignments/{aid1}/pickup", role="Rider", user_id=rd["id"])
    CLIENT.request("POST", f"/api/orders/{o2['id']}/ready", role="Restaurant", user_id=r2["id"])
    CLIENT.request("POST", f"/api/assignments/{aid2}/pickup", role="Rider", user_id=rd["id"])
    CLIENT.request("POST", f"/api/assignments/{aid1}/deliver", role="Rider", user_id=rd["id"])
    # After first delivery, rider still ON_DELIVERY
    s, rb = CLIENT.request("GET", f"/api/riders/{rd['id']}", role="PlatformAdmin", user_id="admin")
    assert rb["data"]["status"] == "ON_DELIVERY"
    # Verify merged fee: solo fee for o1 distance ~ 0.95km → 2 bands → 540; discount = floor(540*0.25) = 135
    s, ob1 = CLIENT.request("GET", f"/api/orders/{o1['id']}", role="PlatformAdmin", user_id="admin")
    solo = ob1["data"]["final_delivery_fee_cents"] + 135  # may vary if peak; pick safe approach
    # Just verify discount applies: assignment.final_delivery_fee_cents < solo.
    s, ab1 = CLIENT.request("GET", f"/api/assignments/{aid1}", role="PlatformAdmin", user_id="admin")
    from pricing import solo_delivery_fee_cents
    expected_solo = solo_delivery_fee_cents(STORE.orders[o1["id"]]["distance_km"],
                                              STORE.orders[o1["id"]]["is_peak"])
    expected_discount = int(expected_solo * 0.25)  # floor
    assert ab1["data"]["final_delivery_fee_cents"] == expected_solo - expected_discount

    CLIENT.request("POST", f"/api/assignments/{aid2}/deliver", role="Rider", user_id=rd["id"])
    # Now route group COMPLETED, rider AVAILABLE.
    s, rb = CLIENT.request("GET", f"/api/riders/{rd['id']}", role="PlatformAdmin", user_id="admin")
    assert rb["data"]["status"] == "AVAILABLE"
    assert STORE.route_groups[group["id"]]["status"] == "COMPLETED"


# === Priority pipeline ===
def t_priority_fk_body_not_found():
    """Priority 4: unknown customer_id in body returns NOT_FOUND."""
    CLIENT.reset()
    r = register_active_restaurant()
    s, b = CLIENT.request("POST", "/api/orders", role="Customer", user_id="unknown",
                          body={"customer_id": "unknown", "restaurant_id": r["id"],
                                "items": [{"menu_item_id": "x", "quantity": 1}]})
    assert s == 404


def t_priority_restaurant_unavailable_before_state():
    """Priority 7 (RESTAURANT_UNAVAILABLE) fires before priority 6 (state) — but only when state passes."""
    CLIENT.reset()
    # Have an active restaurant that gets suspended → its order becomes CANCELLED.
    # Then try to accept again — order is CANCELLED, restaurant is SUSPENDED. State fail first.
    r = register_active_restaurant()
    c = register_customer()
    m = add_menu(r["id"])
    o = place_order(c["id"], r["id"], [{"menu_item_id": m["id"], "quantity": 1}])
    CLIENT.request("POST", f"/api/restaurants/{r['id']}/suspend",
                   role="PlatformAdmin", user_id="admin")
    # Now order is CANCELLED. Restaurant SUSPENDED. Accept should fail state (priority 6) first.
    s, b = CLIENT.request("POST", f"/api/orders/{o['id']}/accept",
                          role="Restaurant", user_id=r["id"])
    assert s == 409 and b["data"]["error_id"] == "ERR_INVALID_STATE"


def t_occ_only_when_version_supplied():
    CLIENT.reset()
    r = register_active_restaurant()
    # No version supplied → no OCC check
    s, _ = CLIENT.request("PATCH", f"/api/restaurants/{r['id']}",
                          role="PlatformAdmin", user_id="admin",
                          body={"address": "new"})
    assert s == 200
    # Wrong version supplied → 409
    s, b = CLIENT.request("PATCH", f"/api/restaurants/{r['id']}",
                          role="PlatformAdmin", user_id="admin",
                          body={"address": "newer", "version": 999})
    assert s == 409 and b["data"]["error_id"] == "ERR_VERSION_CONFLICT"


# === Concurrent races ===
def t_two_returns_race_first_wins():
    CLIENT.reset()
    r = register_active_restaurant(); c = register_customer(); rd = register_rider(); online(rd)
    o, aid = full_deliver(c, r, rd, price=2000)
    s, b = CLIENT.request("POST", f"/api/orders/{o['id']}/returns",
                          role="Customer", user_id=c["id"],
                          body={"reason": "OTHER", "requested_refund_cents": 100})
    rid = b["data"]["id"]
    # First approve.
    s, _ = CLIENT.request("POST", f"/api/returns/{rid}/approve",
                          role="CustomerService", user_id="cs-1",
                          body={"approved_refund_cents": 100})
    assert s == 200
    # Second approve attempt — return is now APPROVED, not REQUESTED/ESCALATED → ERR_INVALID_STATE
    s, b = CLIENT.request("POST", f"/api/returns/{rid}/approve",
                          role="CustomerService", user_id="cs-2",
                          body={"approved_refund_cents": 100})
    assert s == 409 and b["data"]["error_id"] == "ERR_INVALID_STATE"


def t_restaurant_settle_audit_marker():
    """Two settle calls in a row — second one just zeros the (already zero) balance."""
    CLIENT.reset()
    r = register_active_restaurant()
    CLIENT.request("POST", f"/api/restaurants/{r['id']}/settle",
                   role="PlatformAdmin", user_id="admin")
    s, b = CLIENT.request("POST", f"/api/restaurants/{r['id']}/settle",
                          role="PlatformAdmin", user_id="admin")
    assert s == 200 and b["data"]["pending_settlement_cents"] == 0


# === RBAC ===
def t_rider_reads_only_own_record():
    CLIENT.reset()
    r1 = register_rider("p1")
    r2 = register_rider("p2")
    s, _ = CLIENT.request("GET", f"/api/riders/{r1['id']}",
                          role="Rider", user_id=r2["id"])
    assert s == 403
    s, _ = CLIENT.request("GET", f"/api/riders/{r1['id']}",
                          role="Rider", user_id=r1["id"])
    assert s == 200


def t_rider_reads_only_own_assignment():
    CLIENT.reset()
    r = register_active_restaurant(); c = register_customer()
    r1 = register_rider("p1"); online(r1)
    r2 = register_rider("p2"); online(r2)
    m = add_menu(r["id"])
    o = place_order(c["id"], r["id"], [{"menu_item_id": m["id"], "quantity": 1}])
    CLIENT.request("POST", f"/api/orders/{o['id']}/accept", role="Restaurant", user_id=r["id"])
    CLIENT.request("POST", f"/api/orders/{o['id']}/start-preparing",
                   role="Restaurant", user_id=r["id"])
    from store import STORE
    aid = next(a["id"] for a in STORE.assignments.values() if a["order_id"] == o["id"])
    owner = STORE.assignments[aid]["rider_id"]
    other = r1["id"] if owner == r2["id"] else r2["id"]
    s, _ = CLIENT.request("GET", f"/api/assignments/{aid}",
                          role="Rider", user_id=other)
    assert s == 403


# === Cancellation voids payment ===
def t_cancel_voids_payment():
    CLIENT.reset()
    r = register_active_restaurant()
    c = register_customer()
    m = add_menu(r["id"])
    o = place_order(c["id"], r["id"], [{"menu_item_id": m["id"], "quantity": 1}])
    assert o["payment_status"] == "AUTHORIZED"
    s, b = CLIENT.request("POST", f"/api/orders/{o['id']}/cancel",
                          role="Customer", user_id=c["id"])
    assert s == 200
    assert b["data"]["payment_status"] == "VOIDED"


# === Pagination edges ===
def t_pagination_limit_1():
    CLIENT.reset()
    for i in range(5):
        CLIENT.request("POST", "/api/restaurants", role="PlatformAdmin", user_id="admin",
                       body={"name": f"R{i}", "address": "a", "lat": 0, "lng": 0})
    s, b = CLIENT.request("GET", "/api/restaurants?limit=1&offset=2",
                          role="PlatformAdmin", user_id="admin")
    assert s == 200 and len(b["data"]) == 1
    assert b["meta"]["has_more"] is True


def t_pagination_offset_past_total():
    CLIENT.reset()
    CLIENT.request("POST", "/api/restaurants", role="PlatformAdmin", user_id="admin",
                   body={"name": "X", "address": "a", "lat": 0, "lng": 0})
    s, b = CLIENT.request("GET", "/api/restaurants?offset=100",
                          role="PlatformAdmin", user_id="admin")
    assert s == 200 and len(b["data"]) == 0
    assert b["meta"]["has_more"] is False


# === Pre-delivery fields are null ===
def t_pre_delivery_fields_null():
    CLIENT.reset()
    r = register_active_restaurant(); c = register_customer(); rd = register_rider(); online(rd)
    m = add_menu(r["id"])
    o = place_order(c["id"], r["id"], [{"menu_item_id": m["id"], "quantity": 1}])
    assert o["actual_delivery_time"] is None
    assert o["minutes_late"] is None
    assert o["final_delivery_fee_cents"] is None
    assert o["final_commission_cents"] is None


# === Clock sweep redispatch ===
def t_clock_sweep_creates_fresh_offer():
    CLIENT.reset()
    r = register_active_restaurant(); c = register_customer()
    r1 = register_rider("p1"); online(r1)
    r2 = register_rider("p2"); online(r2)
    m = add_menu(r["id"])
    o = place_order(c["id"], r["id"], [{"menu_item_id": m["id"], "quantity": 1}])
    CLIENT.request("POST", f"/api/orders/{o['id']}/accept", role="Restaurant", user_id=r["id"])
    CLIENT.request("POST", f"/api/orders/{o['id']}/start-preparing",
                   role="Restaurant", user_id=r["id"])
    from store import STORE
    pre_count = sum(1 for a in STORE.assignments.values() if a["order_id"] == o["id"])
    assert pre_count == 1
    # First rider was offered. Timeout sweep.
    advance(61)
    # Should have made a new OFFERED to the other rider.
    statuses = [a["status"] for a in STORE.assignments.values() if a["order_id"] == o["id"]]
    assert statuses.count("REJECTED") == 1
    assert "OFFERED" in statuses


# === Order placement with credit drawdown semantic NOT REQUIRED to mutate credit ===
def t_credit_balance_unaffected_by_placement_and_cancel():
    CLIENT.reset()
    r = register_active_restaurant(); c = register_customer()
    # Manually set credit to nonzero
    from store import STORE
    STORE.customers[c["id"]]["credit_balance_cents"] = 1000
    m = add_menu(r["id"])
    o = place_order(c["id"], r["id"], [{"menu_item_id": m["id"], "quantity": 1}])
    s, cb = CLIENT.request("GET", f"/api/customers/{c['id']}",
                           role="PlatformAdmin", user_id="admin")
    # PRD §3.5 says credit_balance_cents is not affected on cancellation.
    # We don't decrement it on placement either — leave it alone unless PRD-specified mutations occur.
    s, _ = CLIENT.request("POST", f"/api/orders/{o['id']}/cancel",
                          role="Customer", user_id=c["id"])
    s, cb2 = CLIENT.request("GET", f"/api/customers/{c['id']}",
                            role="PlatformAdmin", user_id="admin")
    assert cb2["data"]["credit_balance_cents"] == 1000


TESTS = [
    ("late exactly 1 min fine 200", t_late_exactly_1),
    ("late exactly 10 min fine 200", t_late_exactly_10),
    ("late exactly 11 min fine 550", t_late_exactly_11),
    ("late exactly 30 min fine 1500", t_late_exactly_30),
    ("late exactly 31 min tier 3", t_late_exactly_31),
    ("late fee above 1500 caps at 1500", t_late_fee_above_1500_cap),
    ("commission tier 50000 boundary", t_commission_at_50000_boundary),
    ("commission half-up rounding", t_commission_half_up_rounding),
    ("trust score exactly 0.5 — no fine", t_trust_score_exact_0_5_no_abusive_fine),
    ("abusive fine only on QUALITY_ISSUE", t_abusive_only_on_quality_issue),
    ("restaurant pending settlement decrement on return", t_restaurant_settlement_decrement_on_return),
    ("LATE_DELIVERY fine waive credits rider back", t_late_delivery_fine_waive_credits_back),
    ("ABUSIVE_RETURN fine waive restores credit", t_abusive_fine_waive_restores_credit),
    ("return reopen only from ESCALATED", t_return_reopen_only_from_escalated),
    ("WO ESCALATED → RESOLVED", t_wo_escalated_then_resolved),
    ("WO resolve blocked when return REQUESTED", t_wo_resolve_blocked_when_return_requested),
    ("WO submit_info opener_id mismatch", t_wo_submit_info_opener_mismatch),
    ("solo delivery no discount", t_solo_delivery_no_discount),
    ("two-order route merge complete + AVAILABLE", t_route_merge_two_orders),
    ("priority — FK body not found", t_priority_fk_body_not_found),
    ("priority — state before domain on cancelled+suspended", t_priority_restaurant_unavailable_before_state),
    ("OCC only when version supplied", t_occ_only_when_version_supplied),
    ("second approve loser → INVALID_STATE", t_two_returns_race_first_wins),
    ("idempotent settle returns zero", t_restaurant_settle_audit_marker),
    ("rider reads only own record", t_rider_reads_only_own_record),
    ("rider reads only own assignment", t_rider_reads_only_own_assignment),
    ("cancellation voids payment", t_cancel_voids_payment),
    ("pagination limit=1", t_pagination_limit_1),
    ("pagination offset past total", t_pagination_offset_past_total),
    ("pre-delivery fields null", t_pre_delivery_fields_null),
    ("clock sweep creates fresh offer", t_clock_sweep_creates_fresh_offer),
    ("credit_balance unaffected by placement/cancel", t_credit_balance_unaffected_by_placement_and_cancel),
]

if __name__ == "__main__":
    for name, fn in TESTS:
        R.run(name, fn)
    ok = R.report()
    sys.exit(0 if ok else 1)
