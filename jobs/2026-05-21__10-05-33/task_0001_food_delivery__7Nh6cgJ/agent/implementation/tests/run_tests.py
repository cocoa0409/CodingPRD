"""Comprehensive self-tests for the food delivery API."""

from __future__ import annotations

import os
import sys

# Ensure the implementation root is on sys.path
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from tests.harness import TestClient, TestRunner

# Fixed coordinates for two restaurants and a customer.
NYC = (40.7128, -74.0060)
NEAR_NYC = (40.7129, -74.0061)  # ~0.014 km away
FAR_NYC = (40.7228, -74.0060)  # ~1.11 km away

CLIENT = TestClient()


# ---------- helpers ----------

def admin_h():
    return {"role": "PlatformAdmin", "user_id": "admin-1"}


def cs_h(uid="cs-1"):
    return {"role": "CustomerService", "user_id": uid}


def register_active_restaurant(name="Restaurant A", coords=NYC, commission_override=None):
    s, b = CLIENT.request("POST", "/api/restaurants", role="PlatformAdmin", user_id="admin-1",
                          body={"name": name, "address": "1 Main St",
                                "lat": coords[0], "lng": coords[1],
                                "commission_rate_override": commission_override})
    assert s == 201, f"restaurant create failed: {s} {b}"
    rid = b["data"]["id"]
    s, b = CLIENT.request("POST", f"/api/restaurants/{rid}/approve",
                          role="PlatformAdmin", user_id="admin-1")
    assert s == 200, f"approve failed: {s} {b}"
    return b["data"]


def register_customer(phone="555-1234", coords=NEAR_NYC):
    s, b = CLIENT.request("POST", "/api/customers", role="PlatformAdmin", user_id="admin-1",
                          body={"name": "Alice", "phone": phone, "address": "2 Side St",
                                "lat": coords[0], "lng": coords[1]})
    assert s == 201, f"customer create failed: {s} {b}"
    return b["data"]


def register_rider(phone="r-555"):
    s, b = CLIENT.request("POST", "/api/riders", role="PlatformAdmin", user_id="admin-1",
                          body={"name": "Bob", "phone": phone})
    assert s == 201, f"rider create failed: {s} {b}"
    return b["data"]


def online_rider(rid):
    s, _ = CLIENT.request("POST", f"/api/riders/{rid}/go-online", role="Rider", user_id=rid)
    assert s == 200


def add_menu(restaurant_id, name="Burger", price_cents=1200, owner_id=None):
    uid = owner_id or restaurant_id
    s, b = CLIENT.request("POST", f"/api/restaurants/{restaurant_id}/menu-items",
                          role="Restaurant", user_id=uid,
                          body={"name": name, "price_cents": price_cents})
    assert s == 201, f"menu create failed: {s} {b}"
    return b["data"]


def place_order(customer_id, restaurant_id, items):
    s, b = CLIENT.request("POST", "/api/orders", role="Customer", user_id=customer_id,
                          body={"customer_id": customer_id,
                                "restaurant_id": restaurant_id,
                                "items": items})
    assert s == 201, f"order place failed: {s} {b}"
    return b["data"]


def advance(seconds):
    CLIENT.request("POST", "/api/_clock/advance", role="PlatformAdmin", user_id="admin-1",
                   body={"seconds": seconds})


# ---------- tests ----------

R = TestRunner()


def t_health():
    s, b = CLIENT.request("GET", "/")
    assert s == 200
    assert b["data"]["status"] == "ok"


# Auth & RBAC
def t_auth_missing_headers():
    CLIENT.reset()
    s, b = CLIENT.request("GET", "/api/restaurants")
    assert s == 401 and b["data"]["error_id"] == "ERR_AUTH_REQUIRED", b


def t_auth_invalid_role():
    CLIENT.reset()
    s, b = CLIENT.request("GET", "/api/restaurants", role="Admin", user_id="x")
    assert s == 401 and b["data"]["error_id"] == "ERR_AUTH_REQUIRED", b


def t_auth_forbidden_role():
    CLIENT.reset()
    s, b = CLIENT.request("POST", "/api/restaurants", role="Customer", user_id="x",
                          body={"name": "X", "address": "a", "lat": 0, "lng": 0})
    assert s == 403 and b["data"]["error_id"] == "ERR_FORBIDDEN", b


def t_restaurant_lifecycle():
    CLIENT.reset()
    # register pending
    s, b = CLIENT.request("POST", "/api/restaurants", role="PlatformAdmin", user_id="admin",
                          body={"name": "R1", "address": "a", "lat": 1.0, "lng": 2.0})
    assert s == 201 and b["data"]["status"] == "PENDING_APPROVAL"
    rid = b["data"]["id"]
    # approve
    s, b = CLIENT.request("POST", f"/api/restaurants/{rid}/approve",
                          role="PlatformAdmin", user_id="admin")
    assert s == 200 and b["data"]["status"] == "ACTIVE"
    # suspend
    s, b = CLIENT.request("POST", f"/api/restaurants/{rid}/suspend",
                          role="PlatformAdmin", user_id="admin")
    assert s == 200 and b["data"]["status"] == "SUSPENDED"
    # reinstate
    s, b = CLIENT.request("POST", f"/api/restaurants/{rid}/reinstate",
                          role="PlatformAdmin", user_id="admin")
    assert s == 200 and b["data"]["status"] == "ACTIVE"


def t_restaurant_suspend_invalid_state():
    CLIENT.reset()
    r = register_active_restaurant()
    s, _ = CLIENT.request("POST", f"/api/restaurants/{r['id']}/approve",
                          role="PlatformAdmin", user_id="admin")
    assert s == 409  # already ACTIVE
    s, _ = CLIENT.request("POST", f"/api/restaurants/{r['id']}/reinstate",
                          role="PlatformAdmin", user_id="admin")
    assert s == 409


def t_restaurant_commission_override_range():
    CLIENT.reset()
    s, b = CLIENT.request("POST", "/api/restaurants", role="PlatformAdmin", user_id="admin",
                          body={"name": "R2", "address": "a", "lat": 0, "lng": 0,
                                "commission_rate_override": 0.04})
    assert s == 422 and b["data"]["error_id"] == "ERR_VALIDATION"
    s, b = CLIENT.request("POST", "/api/restaurants", role="PlatformAdmin", user_id="admin",
                          body={"name": "R2", "address": "a", "lat": 0, "lng": 0,
                                "commission_rate_override": 0.36})
    assert s == 422 and b["data"]["error_id"] == "ERR_VALIDATION"
    s, b = CLIENT.request("POST", "/api/restaurants", role="PlatformAdmin", user_id="admin",
                          body={"name": "R2", "address": "a", "lat": 0, "lng": 0,
                                "commission_rate_override": 0.10})
    assert s == 201


def t_restaurant_name_immutable():
    CLIENT.reset()
    r = register_active_restaurant()
    s, b = CLIENT.request("PATCH", f"/api/restaurants/{r['id']}",
                          role="PlatformAdmin", user_id="admin",
                          body={"name": "renamed"})
    assert s == 422 and b["data"]["error_id"] == "ERR_VALIDATION"


def t_restaurant_patch_occ():
    CLIENT.reset()
    r = register_active_restaurant()
    s, _ = CLIENT.request("PATCH", f"/api/restaurants/{r['id']}",
                          role="PlatformAdmin", user_id="admin",
                          body={"address": "new", "version": 99})
    assert s == 409
    s, b = CLIENT.request("PATCH", f"/api/restaurants/{r['id']}",
                          role="PlatformAdmin", user_id="admin",
                          body={"address": "new", "version": r["version"]})
    assert s == 200 and b["data"]["version"] == r["version"] + 1


def t_restaurant_suspend_cancels_placed():
    CLIENT.reset()
    r = register_active_restaurant()
    c = register_customer()
    m = add_menu(r["id"])
    o = place_order(c["id"], r["id"], [{"menu_item_id": m["id"], "quantity": 1}])
    # Suspend the restaurant — order should be cancelled.
    s, _ = CLIENT.request("POST", f"/api/restaurants/{r['id']}/suspend",
                          role="PlatformAdmin", user_id="admin")
    assert s == 200
    s, b = CLIENT.request("GET", f"/api/orders/{o['id']}",
                          role="PlatformAdmin", user_id="admin")
    assert b["data"]["status"] == "CANCELLED"
    assert b["data"]["payment_status"] == "VOIDED"


def t_menu_item_crud():
    CLIENT.reset()
    r = register_active_restaurant()
    s, b = CLIENT.request("POST", f"/api/restaurants/{r['id']}/menu-items",
                          role="Restaurant", user_id=r["id"],
                          body={"name": "Pizza", "price_cents": 500})
    assert s == 201
    m = b["data"]
    assert m["is_listed"] is True
    s, b = CLIENT.request("PATCH", f"/api/menu-items/{m['id']}",
                          role="Restaurant", user_id=r["id"],
                          body={"is_listed": False, "version": m["version"]})
    assert s == 200 and b["data"]["is_listed"] is False
    # Price range
    s, b = CLIENT.request("POST", f"/api/restaurants/{r['id']}/menu-items",
                          role="Restaurant", user_id=r["id"],
                          body={"name": "X", "price_cents": 0})
    assert s == 422
    s, b = CLIENT.request("POST", f"/api/restaurants/{r['id']}/menu-items",
                          role="Restaurant", user_id=r["id"],
                          body={"name": "X", "price_cents": 1_000_001})
    assert s == 422


def t_rider_lifecycle():
    CLIENT.reset()
    rider = register_rider()
    assert rider["status"] == "OFFLINE"
    s, b = CLIENT.request("POST", f"/api/riders/{rider['id']}/go-online",
                          role="Rider", user_id=rider["id"])
    assert s == 200 and b["data"]["status"] == "AVAILABLE"
    s, b = CLIENT.request("POST", f"/api/riders/{rider['id']}/go-offline",
                          role="Rider", user_id=rider["id"])
    assert s == 200 and b["data"]["status"] == "OFFLINE"


def t_rider_go_online_forbidden():
    CLIENT.reset()
    r1 = register_rider("p1")
    r2 = register_rider("p2")
    s, _ = CLIENT.request("POST", f"/api/riders/{r1['id']}/go-online",
                          role="Rider", user_id=r2["id"])
    assert s == 403


def t_rider_suspend_threshold():
    CLIENT.reset()
    r = register_rider()
    online_rider(r["id"])
    # Default metrics are 1.0 — must fail suspend
    s, b = CLIENT.request("POST", f"/api/riders/{r['id']}/suspend",
                          role="PlatformAdmin", user_id="admin")
    assert s == 422 and b["data"]["error_id"] == "ERR_SUSPEND_CRITERIA_NOT_MET"


def t_customer_read_only_self():
    CLIENT.reset()
    c1 = register_customer("p1")
    c2 = register_customer("p2")
    s, _ = CLIENT.request("GET", f"/api/customers/{c1['id']}",
                          role="Customer", user_id=c2["id"])
    assert s == 403
    s, _ = CLIENT.request("GET", f"/api/customers/{c1['id']}",
                          role="Customer", user_id=c1["id"])
    assert s == 200


def t_order_placement_subtotal_min():
    CLIENT.reset()
    r = register_active_restaurant()
    c = register_customer()
    m = add_menu(r["id"], price_cents=50)
    s, b = CLIENT.request("POST", "/api/orders", role="Customer", user_id=c["id"],
                          body={"customer_id": c["id"], "restaurant_id": r["id"],
                                "items": [{"menu_item_id": m["id"], "quantity": 1}]})
    assert s == 422 and b["data"]["error_id"] == "ERR_ORDER_INVALID"


def t_order_placement_empty_items():
    CLIENT.reset()
    r = register_active_restaurant()
    c = register_customer()
    s, b = CLIENT.request("POST", "/api/orders", role="Customer", user_id=c["id"],
                          body={"customer_id": c["id"], "restaurant_id": r["id"],
                                "items": []})
    assert s == 422 and b["data"]["error_id"] == "ERR_ORDER_INVALID"


def t_order_placement_restaurant_not_active():
    CLIENT.reset()
    s, b = CLIENT.request("POST", "/api/restaurants", role="PlatformAdmin", user_id="admin",
                          body={"name": "R", "address": "a", "lat": 0, "lng": 0})
    rid = b["data"]["id"]
    c = register_customer()
    m = add_menu(rid)
    s, b = CLIENT.request("POST", "/api/orders", role="Customer", user_id=c["id"],
                          body={"customer_id": c["id"], "restaurant_id": rid,
                                "items": [{"menu_item_id": m["id"], "quantity": 1}]})
    assert s == 422 and b["data"]["error_id"] == "ERR_RESTAURANT_UNAVAILABLE"


def t_order_placement_unlisted_item():
    CLIENT.reset()
    r = register_active_restaurant()
    c = register_customer()
    m = add_menu(r["id"])
    CLIENT.request("PATCH", f"/api/menu-items/{m['id']}", role="Restaurant", user_id=r["id"],
                   body={"is_listed": False})
    s, b = CLIENT.request("POST", "/api/orders", role="Customer", user_id=c["id"],
                          body={"customer_id": c["id"], "restaurant_id": r["id"],
                                "items": [{"menu_item_id": m["id"], "quantity": 1}]})
    assert s == 422 and b["data"]["error_id"] == "ERR_RESTAURANT_UNAVAILABLE"


def t_order_placement_subtotal_and_authorized():
    CLIENT.reset()
    r = register_active_restaurant()
    c = register_customer()
    m = add_menu(r["id"], price_cents=1200)
    o = place_order(c["id"], r["id"], [{"menu_item_id": m["id"], "quantity": 2}])
    assert o["subtotal_cents"] == 2400
    assert o["payment_status"] == "AUTHORIZED"
    assert o["provisional_commission_cents"] == 360  # 15% of 2400


def t_commission_tiers():
    """Subtotal $250 (25000 cents): 20000*0.15 + 5000*0.18 = 3000 + 900 = 3900."""
    from pricing import tiered_commission_cents, flat_commission_cents
    assert tiered_commission_cents(25_000) == 3900
    # subtotal $600 (60000): 20000*.15 + 30000*.18 + 10000*.22 = 3000 + 5400 + 2200 = 10600
    assert tiered_commission_cents(60_000) == 10600
    # boundary 20000: 20000*.15 = 3000
    assert tiered_commission_cents(20_000) == 3000
    # flat override
    assert flat_commission_cents(10_000, 0.20) == 2000


def t_delivery_fee_formula():
    from pricing import solo_delivery_fee_cents
    # 2.0 km, off-peak → 300 + 2*120 = 540
    assert solo_delivery_fee_cents(2.0, False) == 540
    # 2.01 km → 3 bands: 300 + 360 = 660
    assert solo_delivery_fee_cents(2.01, False) == 660
    # peak: +200
    assert solo_delivery_fee_cents(2.0, True) == 740


def t_bonus_tier_boundaries():
    from bonus import compute_bonus_tier
    # exact 0.900 → PLATINUM (need on_time*0.6 + acc*0.3 + rating/5*0.1 = 0.900)
    # eg on_time=1.0, acc=1.0, rating=0.0 → 0.6+0.3+0 = 0.9
    assert compute_bonus_tier(1.0, 1.0, 0.0) == "PLATINUM"
    # 0.800 boundary: 0.8*0.6 + 1.0*0.3 + ... try on_time=0.8, acc=1.0, rating=5 →
    # 0.48 + 0.30 + 0.10 = 0.88 (GOLD). Try on_time=0.8, acc=1.0, rating=0 → 0.48+0.3+0 = 0.78 (SILVER)
    # Make exact 0.8: need sum=0.8. on_time=1.0, acc=0.5, rating=2.5 → 0.6+0.15+0.05 = 0.80 → GOLD
    assert compute_bonus_tier(1.0, 0.5, 2.5) == "GOLD"
    # 0.700: on_time=1.0, acc=1/3, rating=0 → 0.6+0.1+0 = 0.7 → SILVER
    assert compute_bonus_tier(1.0, 1.0 / 3.0, 0.0) == "SILVER"
    # below 0.7
    assert compute_bonus_tier(0.5, 0.5, 0.0) == "BRONZE"


def t_end_to_end_delivery():
    CLIENT.reset()
    r = register_active_restaurant(coords=NYC)
    c = register_customer(coords=NEAR_NYC)
    rider = register_rider()
    online_rider(rider["id"])
    m = add_menu(r["id"], price_cents=2000)
    o = place_order(c["id"], r["id"], [{"menu_item_id": m["id"], "quantity": 1}])
    # accept
    s, _ = CLIENT.request("POST", f"/api/orders/{o['id']}/accept",
                          role="Restaurant", user_id=r["id"])
    assert s == 200
    s, _ = CLIENT.request("POST", f"/api/orders/{o['id']}/start-preparing",
                          role="Restaurant", user_id=r["id"])
    assert s == 200
    # Find the assignment
    from store import STORE
    aid = next(a["id"] for a in STORE.assignments.values() if a["order_id"] == o["id"])
    s, _ = CLIENT.request("POST", f"/api/assignments/{aid}/accept",
                          role="Rider", user_id=rider["id"])
    assert s == 200
    s, _ = CLIENT.request("POST", f"/api/orders/{o['id']}/ready",
                          role="Restaurant", user_id=r["id"])
    assert s == 200
    s, _ = CLIENT.request("POST", f"/api/assignments/{aid}/pickup",
                          role="Rider", user_id=rider["id"])
    assert s == 200
    s, b = CLIENT.request("POST", f"/api/assignments/{aid}/deliver",
                          role="Rider", user_id=rider["id"])
    assert s == 200
    # Order should be DELIVERED + CAPTURED
    s, ob = CLIENT.request("GET", f"/api/orders/{o['id']}",
                           role="PlatformAdmin", user_id="admin")
    assert ob["data"]["status"] == "DELIVERED"
    assert ob["data"]["payment_status"] == "CAPTURED"
    assert ob["data"]["minutes_late"] == 0
    assert ob["data"]["final_commission_cents"] == 300  # 15% of 2000


def t_late_delivery_fine():
    CLIENT.reset()
    r = register_active_restaurant(coords=NYC)
    c = register_customer(coords=NEAR_NYC)
    rider = register_rider()
    online_rider(rider["id"])
    m = add_menu(r["id"], price_cents=2000)
    o = place_order(c["id"], r["id"], [{"menu_item_id": m["id"], "quantity": 1}])
    CLIENT.request("POST", f"/api/orders/{o['id']}/accept",
                   role="Restaurant", user_id=r["id"])
    CLIENT.request("POST", f"/api/orders/{o['id']}/start-preparing",
                   role="Restaurant", user_id=r["id"])
    from store import STORE
    aid = next(a["id"] for a in STORE.assignments.values() if a["order_id"] == o["id"])
    CLIENT.request("POST", f"/api/assignments/{aid}/accept", role="Rider", user_id=rider["id"])
    CLIENT.request("POST", f"/api/orders/{o['id']}/ready",
                   role="Restaurant", user_id=r["id"])
    CLIENT.request("POST", f"/api/assignments/{aid}/pickup", role="Rider", user_id=rider["id"])
    # Advance past promised time by 65 minutes total (45 promised + 20 over)
    advance(45 * 60 + 20 * 60)
    CLIENT.request("POST", f"/api/assignments/{aid}/deliver", role="Rider", user_id=rider["id"])
    s, ob = CLIENT.request("GET", f"/api/orders/{o['id']}",
                           role="PlatformAdmin", user_id="admin")
    assert ob["data"]["minutes_late"] == 20, ob["data"]
    # Late fine: 11-30 min → 500 + 50*10 = 1000
    s, fb = CLIENT.request("GET", f"/api/fines?subject_type=RIDER&subject_id={rider['id']}",
                           role="PlatformAdmin", user_id="admin")
    late_fines = [f for f in fb["data"] if f["reason"] == "LATE_DELIVERY"]
    assert len(late_fines) == 1
    assert late_fines[0]["amount_cents"] == 1000


def t_return_window_and_refund():
    CLIENT.reset()
    r = register_active_restaurant(coords=NYC)
    c = register_customer(coords=NEAR_NYC)
    rider = register_rider()
    online_rider(rider["id"])
    m = add_menu(r["id"], price_cents=2000)
    o = place_order(c["id"], r["id"], [{"menu_item_id": m["id"], "quantity": 1}])
    CLIENT.request("POST", f"/api/orders/{o['id']}/accept", role="Restaurant", user_id=r["id"])
    CLIENT.request("POST", f"/api/orders/{o['id']}/start-preparing",
                   role="Restaurant", user_id=r["id"])
    from store import STORE
    aid = next(a["id"] for a in STORE.assignments.values() if a["order_id"] == o["id"])
    CLIENT.request("POST", f"/api/assignments/{aid}/accept", role="Rider", user_id=rider["id"])
    CLIENT.request("POST", f"/api/orders/{o['id']}/ready", role="Restaurant", user_id=r["id"])
    CLIENT.request("POST", f"/api/assignments/{aid}/pickup", role="Rider", user_id=rider["id"])
    CLIENT.request("POST", f"/api/assignments/{aid}/deliver", role="Rider", user_id=rider["id"])

    # Open a return
    s, b = CLIENT.request("POST", f"/api/orders/{o['id']}/returns",
                          role="Customer", user_id=c["id"],
                          body={"reason": "QUALITY_ISSUE", "requested_refund_cents": 1000})
    assert s == 201, b
    return_id = b["data"]["id"]
    # Approve
    s, b = CLIENT.request("POST", f"/api/returns/{return_id}/approve",
                          role="CustomerService", user_id="cs-1",
                          body={"approved_refund_cents": 500})
    assert s == 200, b
    # Verify cascade
    s, ob = CLIENT.request("GET", f"/api/orders/{o['id']}",
                           role="PlatformAdmin", user_id="admin")
    assert ob["data"]["status"] == "REFUNDED"
    assert ob["data"]["payment_status"] == "PARTIALLY_REFUNDED"
    s, cb = CLIENT.request("GET", f"/api/customers/{c['id']}",
                           role="PlatformAdmin", user_id="admin")
    assert cb["data"]["credit_balance_cents"] == 500


def t_return_window_expired():
    CLIENT.reset()
    r = register_active_restaurant()
    c = register_customer()
    rider = register_rider()
    online_rider(rider["id"])
    m = add_menu(r["id"], price_cents=2000)
    o = place_order(c["id"], r["id"], [{"menu_item_id": m["id"], "quantity": 1}])
    CLIENT.request("POST", f"/api/orders/{o['id']}/accept", role="Restaurant", user_id=r["id"])
    CLIENT.request("POST", f"/api/orders/{o['id']}/start-preparing",
                   role="Restaurant", user_id=r["id"])
    from store import STORE
    aid = next(a["id"] for a in STORE.assignments.values() if a["order_id"] == o["id"])
    CLIENT.request("POST", f"/api/assignments/{aid}/accept", role="Rider", user_id=rider["id"])
    CLIENT.request("POST", f"/api/orders/{o['id']}/ready", role="Restaurant", user_id=r["id"])
    CLIENT.request("POST", f"/api/assignments/{aid}/pickup", role="Rider", user_id=rider["id"])
    CLIENT.request("POST", f"/api/assignments/{aid}/deliver", role="Rider", user_id=rider["id"])
    advance(25 * 3600)  # 25 hours
    s, b = CLIENT.request("POST", f"/api/orders/{o['id']}/returns",
                          role="Customer", user_id=c["id"],
                          body={"reason": "OTHER", "requested_refund_cents": 100})
    assert s == 422 and b["data"]["error_id"] == "ERR_RETURN_WINDOW_EXPIRED"


def t_duplicate_return():
    CLIENT.reset()
    r = register_active_restaurant()
    c = register_customer()
    rider = register_rider()
    online_rider(rider["id"])
    m = add_menu(r["id"], price_cents=2000)
    o = place_order(c["id"], r["id"], [{"menu_item_id": m["id"], "quantity": 1}])
    CLIENT.request("POST", f"/api/orders/{o['id']}/accept", role="Restaurant", user_id=r["id"])
    CLIENT.request("POST", f"/api/orders/{o['id']}/start-preparing",
                   role="Restaurant", user_id=r["id"])
    from store import STORE
    aid = next(a["id"] for a in STORE.assignments.values() if a["order_id"] == o["id"])
    CLIENT.request("POST", f"/api/assignments/{aid}/accept", role="Rider", user_id=rider["id"])
    CLIENT.request("POST", f"/api/orders/{o['id']}/ready", role="Restaurant", user_id=r["id"])
    CLIENT.request("POST", f"/api/assignments/{aid}/pickup", role="Rider", user_id=rider["id"])
    CLIENT.request("POST", f"/api/assignments/{aid}/deliver", role="Rider", user_id=rider["id"])
    s, _ = CLIENT.request("POST", f"/api/orders/{o['id']}/returns",
                          role="Customer", user_id=c["id"],
                          body={"reason": "OTHER", "requested_refund_cents": 100})
    assert s == 201
    s, b = CLIENT.request("POST", f"/api/orders/{o['id']}/returns",
                          role="Customer", user_id=c["id"],
                          body={"reason": "OTHER", "requested_refund_cents": 100})
    assert s == 409 and b["data"]["error_id"] == "ERR_DUPLICATE_RETURN"


def t_offer_timeout_sweep():
    CLIENT.reset()
    r = register_active_restaurant()
    c = register_customer()
    rider = register_rider()
    online_rider(rider["id"])
    m = add_menu(r["id"], price_cents=2000)
    o = place_order(c["id"], r["id"], [{"menu_item_id": m["id"], "quantity": 1}])
    CLIENT.request("POST", f"/api/orders/{o['id']}/accept", role="Restaurant", user_id=r["id"])
    CLIENT.request("POST", f"/api/orders/{o['id']}/start-preparing",
                   role="Restaurant", user_id=r["id"])
    from store import STORE
    a_before = [a for a in STORE.assignments.values() if a["order_id"] == o["id"]]
    assert len(a_before) == 1 and a_before[0]["status"] == "OFFERED"
    # Advance 61 seconds → sweep should reject
    advance(61)
    after = [a for a in STORE.assignments.values() if a["order_id"] == o["id"]]
    statuses = {a["status"] for a in after}
    # The original OFFERED assignment is now REJECTED, and a new OFFERED was created if there's a rider.
    assert "REJECTED" in statuses


def t_order_already_assigned():
    CLIENT.reset()
    r = register_active_restaurant()
    c = register_customer()
    r1 = register_rider("p1"); online_rider(r1["id"])
    r2 = register_rider("p2"); online_rider(r2["id"])
    m = add_menu(r["id"], price_cents=2000)
    o = place_order(c["id"], r["id"], [{"menu_item_id": m["id"], "quantity": 1}])
    CLIENT.request("POST", f"/api/orders/{o['id']}/accept", role="Restaurant", user_id=r["id"])
    CLIENT.request("POST", f"/api/orders/{o['id']}/start-preparing",
                   role="Restaurant", user_id=r["id"])
    # Manually create a 2nd dispatch
    s, _ = CLIENT.request("POST", f"/api/orders/{o['id']}/dispatch",
                          role="PlatformAdmin", user_id="admin")
    assert s == 201
    from store import STORE
    offers = [a for a in STORE.assignments.values()
              if a["order_id"] == o["id"] and a["status"] == "OFFERED"]
    assert len(offers) == 2
    # Have the first rider accept.
    a1 = offers[0]
    s, _ = CLIENT.request("POST", f"/api/assignments/{a1['id']}/accept",
                          role="Rider", user_id=a1["rider_id"])
    assert s == 200
    # Second rider tries to accept → ERR_ORDER_ALREADY_ASSIGNED
    a2 = offers[1]
    s, b = CLIENT.request("POST", f"/api/assignments/{a2['id']}/accept",
                          role="Rider", user_id=a2["rider_id"])
    assert s == 409 and b["data"]["error_id"] == "ERR_ORDER_ALREADY_ASSIGNED"


def t_work_order_flow():
    CLIENT.reset()
    c = register_customer()
    s, b = CLIENT.request("POST", "/api/work-orders", role="Customer", user_id=c["id"],
                          body={"category": "FOOD_QUALITY"})
    assert s == 201
    wid = b["data"]["id"]
    s, b = CLIENT.request("POST", f"/api/work-orders/{wid}/assign",
                          role="CustomerService", user_id="cs-1")
    assert s == 200 and b["data"]["status"] == "UNDER_REVIEW"
    s, b = CLIENT.request("POST", f"/api/work-orders/{wid}/resolve",
                          role="CustomerService", user_id="cs-1",
                          body={"resolution_notes": "ok"})
    assert s == 200 and b["data"]["status"] == "RESOLVED"
    s, b = CLIENT.request("POST", f"/api/work-orders/{wid}/close",
                          role="CustomerService", user_id="cs-1")
    assert s == 200 and b["data"]["status"] == "CLOSED"


def t_wo_related_return_unresolved():
    CLIENT.reset()
    r = register_active_restaurant()
    c = register_customer()
    rider = register_rider(); online_rider(rider["id"])
    m = add_menu(r["id"], price_cents=2000)
    o = place_order(c["id"], r["id"], [{"menu_item_id": m["id"], "quantity": 1}])
    CLIENT.request("POST", f"/api/orders/{o['id']}/accept", role="Restaurant", user_id=r["id"])
    CLIENT.request("POST", f"/api/orders/{o['id']}/start-preparing",
                   role="Restaurant", user_id=r["id"])
    from store import STORE
    aid = next(a["id"] for a in STORE.assignments.values() if a["order_id"] == o["id"])
    CLIENT.request("POST", f"/api/assignments/{aid}/accept", role="Rider", user_id=rider["id"])
    CLIENT.request("POST", f"/api/orders/{o['id']}/ready", role="Restaurant", user_id=r["id"])
    CLIENT.request("POST", f"/api/assignments/{aid}/pickup", role="Rider", user_id=rider["id"])
    CLIENT.request("POST", f"/api/assignments/{aid}/deliver", role="Rider", user_id=rider["id"])
    s, b = CLIENT.request("POST", f"/api/orders/{o['id']}/returns",
                          role="Customer", user_id=c["id"],
                          body={"reason": "QUALITY_ISSUE", "requested_refund_cents": 100})
    rid = b["data"]["id"]
    # Escalate → creates WO
    CLIENT.request("POST", f"/api/returns/{rid}/escalate",
                   role="CustomerService", user_id="cs-1")
    wo = next(w for w in STORE.work_orders.values() if w.get("related_return_id") == rid)
    # Claim + try to resolve while related return is still ESCALATED
    CLIENT.request("POST", f"/api/work-orders/{wo['id']}/assign",
                   role="CustomerService", user_id="cs-1")
    s, b = CLIENT.request("POST", f"/api/work-orders/{wo['id']}/resolve",
                          role="CustomerService", user_id="cs-1",
                          body={"resolution_notes": "x"})
    assert s == 422 and b["data"]["error_id"] == "ERR_RELATED_RETURN_UNRESOLVED"


def t_fine_waive_credits_back():
    CLIENT.reset()
    r = register_active_restaurant()
    c = register_customer()
    rider = register_rider(); online_rider(rider["id"])
    m = add_menu(r["id"], price_cents=2000)
    o = place_order(c["id"], r["id"], [{"menu_item_id": m["id"], "quantity": 1}])
    CLIENT.request("POST", f"/api/orders/{o['id']}/accept", role="Restaurant", user_id=r["id"])
    CLIENT.request("POST", f"/api/orders/{o['id']}/start-preparing",
                   role="Restaurant", user_id=r["id"])
    from store import STORE
    aid = next(a["id"] for a in STORE.assignments.values() if a["order_id"] == o["id"])
    CLIENT.request("POST", f"/api/assignments/{aid}/accept", role="Rider", user_id=rider["id"])
    # cancel after accept → no-show fine $5
    s, _ = CLIENT.request("POST", f"/api/assignments/{aid}/cancel",
                          role="Rider", user_id=rider["id"])
    assert s == 200
    s, fb = CLIENT.request("GET", f"/api/fines?subject_type=RIDER&subject_id={rider['id']}",
                           role="PlatformAdmin", user_id="admin")
    assert len(fb["data"]) == 1
    fid = fb["data"][0]["id"]
    assert fb["data"][0]["amount_cents"] == 500
    s, rb = CLIENT.request("GET", f"/api/riders/{rider['id']}",
                           role="PlatformAdmin", user_id="admin")
    assert rb["data"]["wallet_balance_cents"] == -500
    s, _ = CLIENT.request("POST", f"/api/fines/{fid}/waive",
                          role="PlatformAdmin", user_id="admin")
    assert s == 200
    s, rb = CLIENT.request("GET", f"/api/riders/{rider['id']}",
                           role="PlatformAdmin", user_id="admin")
    assert rb["data"]["wallet_balance_cents"] == 0


def t_pagination_defaults():
    CLIENT.reset()
    for i in range(15):
        CLIENT.request("POST", "/api/restaurants", role="PlatformAdmin", user_id="admin",
                       body={"name": f"R{i}", "address": "a", "lat": 0, "lng": 0})
    s, b = CLIENT.request("GET", "/api/restaurants", role="PlatformAdmin", user_id="admin")
    assert s == 200
    assert b["meta"]["limit"] == 10
    assert b["meta"]["offset"] == 0
    assert b["meta"]["total_count"] == 15
    assert b["meta"]["has_more"] is True
    assert len(b["data"]) == 10


def t_pagination_invalid():
    CLIENT.reset()
    s, _ = CLIENT.request("GET", "/api/restaurants?limit=0", role="PlatformAdmin", user_id="admin")
    assert s == 422
    s, _ = CLIENT.request("GET", "/api/restaurants?limit=101", role="PlatformAdmin", user_id="admin")
    assert s == 422
    s, _ = CLIENT.request("GET", "/api/restaurants?offset=-1", role="PlatformAdmin", user_id="admin")
    assert s == 422


def t_not_found_left_to_right():
    CLIENT.reset()
    s, b = CLIENT.request("GET", "/api/restaurants/missing",
                          role="PlatformAdmin", user_id="admin")
    assert s == 404 and b["data"]["error_id"] == "ERR_NOT_FOUND"


def t_clock_advance_invalid():
    CLIENT.reset()
    s, b = CLIENT.request("POST", "/api/_clock/advance",
                          role="PlatformAdmin", user_id="admin",
                          body={"seconds": -1})
    assert s == 422


# Register all tests
TESTS = [
    ("health endpoint", t_health),
    ("auth missing headers", t_auth_missing_headers),
    ("auth invalid role", t_auth_invalid_role),
    ("auth forbidden role", t_auth_forbidden_role),
    ("restaurant lifecycle", t_restaurant_lifecycle),
    ("restaurant suspend invalid state", t_restaurant_suspend_invalid_state),
    ("restaurant commission override range", t_restaurant_commission_override_range),
    ("restaurant name immutable", t_restaurant_name_immutable),
    ("restaurant patch OCC", t_restaurant_patch_occ),
    ("restaurant suspend cancels PLACED", t_restaurant_suspend_cancels_placed),
    ("menu item CRUD + price range", t_menu_item_crud),
    ("rider lifecycle", t_rider_lifecycle),
    ("rider go-online forbidden", t_rider_go_online_forbidden),
    ("rider suspend threshold", t_rider_suspend_threshold),
    ("customer read only self", t_customer_read_only_self),
    ("order placement subtotal min", t_order_placement_subtotal_min),
    ("order placement empty items", t_order_placement_empty_items),
    ("order placement restaurant not active", t_order_placement_restaurant_not_active),
    ("order placement unlisted item", t_order_placement_unlisted_item),
    ("order placement derived fields", t_order_placement_subtotal_and_authorized),
    ("commission tier math", t_commission_tiers),
    ("delivery fee formula", t_delivery_fee_formula),
    ("bonus tier boundaries", t_bonus_tier_boundaries),
    ("end-to-end delivery", t_end_to_end_delivery),
    ("late delivery fine tier 2", t_late_delivery_fine),
    ("return window + refund cascade", t_return_window_and_refund),
    ("return window expired (24h)", t_return_window_expired),
    ("duplicate return", t_duplicate_return),
    ("offer timeout sweep", t_offer_timeout_sweep),
    ("ERR_ORDER_ALREADY_ASSIGNED", t_order_already_assigned),
    ("work order flow", t_work_order_flow),
    ("WO related return unresolved", t_wo_related_return_unresolved),
    ("fine waive reverses ledger", t_fine_waive_credits_back),
    ("pagination defaults", t_pagination_defaults),
    ("pagination invalid", t_pagination_invalid),
    ("ERR_NOT_FOUND left-to-right", t_not_found_left_to_right),
    ("clock advance invalid", t_clock_advance_invalid),
]

if __name__ == "__main__":
    for name, fn in TESTS:
        R.run(name, fn)
    ok = R.report()
    sys.exit(0 if ok else 1)
