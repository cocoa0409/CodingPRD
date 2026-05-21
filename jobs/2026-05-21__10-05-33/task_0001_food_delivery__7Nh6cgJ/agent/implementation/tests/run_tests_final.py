"""Final self-tests — covering remaining PRD branches (dispatch selection,
WO closure, override boundaries, fine query scopes, list filters, etc.)."""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from tests.harness import TestClient, TestRunner

NYC = (40.7128, -74.0060)
NEAR_NYC = (40.7129, -74.0061)

CLIENT = TestClient()
R = TestRunner()


def make_restaurant(name="R", coords=NYC, override=None):
    s, b = CLIENT.request("POST", "/api/restaurants", role="PlatformAdmin", user_id="admin",
                          body={"name": name, "address": "1 a", "lat": coords[0], "lng": coords[1],
                                "commission_rate_override": override})
    rid = b["data"]["id"]
    CLIENT.request("POST", f"/api/restaurants/{rid}/approve",
                   role="PlatformAdmin", user_id="admin")
    return b["data"]


def make_customer(phone="555", coords=NEAR_NYC):
    s, b = CLIENT.request("POST", "/api/customers", role="PlatformAdmin", user_id="admin",
                          body={"name": "C", "phone": phone, "address": "x",
                                "lat": coords[0], "lng": coords[1]})
    return b["data"]


def make_rider(phone="r"):
    s, b = CLIENT.request("POST", "/api/riders", role="PlatformAdmin", user_id="admin",
                          body={"name": "R", "phone": phone})
    return b["data"]


def go_online(r):
    CLIENT.request("POST", f"/api/riders/{r['id']}/go-online", role="Rider", user_id=r["id"])


def add_menu(rid, price=2000, name="X"):
    s, b = CLIENT.request("POST", f"/api/restaurants/{rid}/menu-items",
                          role="Restaurant", user_id=rid,
                          body={"name": name, "price_cents": price})
    return b["data"]


def place_order(cid, rid, items):
    s, b = CLIENT.request("POST", "/api/orders", role="Customer", user_id=cid,
                          body={"customer_id": cid, "restaurant_id": rid, "items": items})
    return b["data"]


# === Restaurant override boundary values ===
def t_override_boundary_low():
    CLIENT.reset()
    # 0.05 lower bound — accepted
    s, b = CLIENT.request("POST", "/api/restaurants", role="PlatformAdmin", user_id="admin",
                          body={"name": "Q", "address": "x", "lat": 40.0, "lng": -74.0,
                                "commission_rate_override": 0.05})
    assert s == 201, (s, b)


def t_override_boundary_high():
    CLIENT.reset()
    s, b = CLIENT.request("POST", "/api/restaurants", role="PlatformAdmin", user_id="admin",
                          body={"name": "Q", "address": "x", "lat": 40.0, "lng": -74.0,
                                "commission_rate_override": 0.35})
    assert s == 201, (s, b)


def t_override_outside_range():
    CLIENT.reset()
    s, b = CLIENT.request("POST", "/api/restaurants", role="PlatformAdmin", user_id="admin",
                          body={"name": "Q", "address": "x", "lat": 40.0, "lng": -74.0,
                                "commission_rate_override": 0.04})
    assert s == 422, (s, b)
    s, b = CLIENT.request("POST", "/api/restaurants", role="PlatformAdmin", user_id="admin",
                          body={"name": "Q2", "address": "x", "lat": 40.0, "lng": -74.0,
                                "commission_rate_override": 0.36})
    assert s == 422, (s, b)


# === Dispatch: explicit /dispatch while one rider holds OFFERED targets a different rider ===
def t_dispatch_excludes_only_live_holders():
    """PRD §3.6: '/dispatch always creates a new OFFERED Assignment so long as the pool is non-empty'.
    The rider currently OFFERED is excluded from the new dispatch's pool."""
    CLIENT.reset()
    r = make_restaurant()
    c = make_customer()
    rider1 = make_rider("r1"); go_online(rider1)
    rider2 = make_rider("r2"); go_online(rider2)
    m = add_menu(r["id"])
    o = place_order(c["id"], r["id"], [{"menu_item_id": m["id"], "quantity": 1}])
    CLIENT.request("POST", f"/api/orders/{o['id']}/accept", role="Restaurant", user_id=r["id"])
    CLIENT.request("POST", f"/api/orders/{o['id']}/start-preparing", role="Restaurant", user_id=r["id"])
    from store import STORE
    # First OFFERED should go to rider2 (most recently registered).
    a1 = next(a for a in STORE.assignments.values() if a["order_id"] == o["id"] and a["status"] == "OFFERED")
    first_rider = a1["rider_id"]
    # Explicit /dispatch — should target the OTHER rider since the first holds OFFERED.
    s, b = CLIENT.request("POST", f"/api/orders/{o['id']}/dispatch",
                          role="PlatformAdmin", user_id="admin")
    assert s == 201, (s, b)
    a2_id = b["data"]["id"]
    a2 = STORE.assignments[a2_id]
    assert a2["rider_id"] != first_rider, (a2, first_rider)
    # Both rider1 and rider2 should now hold offers.
    offers = [a for a in STORE.assignments.values()
              if a["order_id"] == o["id"] and a["status"] == "OFFERED"]
    assert len(offers) == 2, offers
    # No third dispatch is possible — pool is now empty.
    s, b = CLIENT.request("POST", f"/api/orders/{o['id']}/dispatch",
                          role="PlatformAdmin", user_id="admin")
    assert s == 409 and b["data"]["error_id"] == "ERR_INVALID_STATE", (s, b)


def t_dispatch_pool_empty_returns_invalid_state():
    """Manual /dispatch when there are no riders → ERR_INVALID_STATE."""
    CLIENT.reset()
    r = make_restaurant(); c = make_customer()
    m = add_menu(r["id"])
    o = place_order(c["id"], r["id"], [{"menu_item_id": m["id"], "quantity": 1}])
    CLIENT.request("POST", f"/api/orders/{o['id']}/accept", role="Restaurant", user_id=r["id"])
    s, b = CLIENT.request("POST", f"/api/orders/{o['id']}/dispatch",
                          role="PlatformAdmin", user_id="admin")
    assert s == 409 and b["data"]["error_id"] == "ERR_INVALID_STATE", (s, b)


def t_dispatch_tiebreaker_created_at_desc():
    """Among AVAILABLE riders, most recently registered wins."""
    CLIENT.reset()
    r = make_restaurant(); c = make_customer()
    r1 = make_rider("r1"); go_online(r1)
    r2 = make_rider("r2"); go_online(r2)
    r3 = make_rider("r3"); go_online(r3)  # registered last
    m = add_menu(r["id"])
    o = place_order(c["id"], r["id"], [{"menu_item_id": m["id"], "quantity": 1}])
    CLIENT.request("POST", f"/api/orders/{o['id']}/accept", role="Restaurant", user_id=r["id"])
    CLIENT.request("POST", f"/api/orders/{o['id']}/start-preparing", role="Restaurant", user_id=r["id"])
    from store import STORE
    live = next(a for a in STORE.assignments.values() if a["order_id"] == o["id"] and a["status"] == "OFFERED")
    assert live["rider_id"] == r3["id"], (live, r3, r2, r1)


# === Order list filter by rider_id ===
def t_orders_list_by_rider():
    CLIENT.reset()
    r = make_restaurant(); c = make_customer()
    rider = make_rider(); go_online(rider)
    m = add_menu(r["id"])
    o = place_order(c["id"], r["id"], [{"menu_item_id": m["id"], "quantity": 1}])
    CLIENT.request("POST", f"/api/orders/{o['id']}/accept", role="Restaurant", user_id=r["id"])
    CLIENT.request("POST", f"/api/orders/{o['id']}/start-preparing", role="Restaurant", user_id=r["id"])
    from store import STORE
    a = next(a for a in STORE.assignments.values() if a["order_id"] == o["id"])
    CLIENT.request("POST", f"/api/assignments/{a['id']}/accept", role="Rider", user_id=rider["id"])
    s, b = CLIENT.request("GET", f"/api/orders?rider_id={rider['id']}",
                          role="PlatformAdmin", user_id="admin")
    assert s == 200
    ids = [r["id"] for r in b["data"]]
    assert o["id"] in ids


# === menu_item_id from different restaurant → ERR_RESTAURANT_UNAVAILABLE ===
def t_menu_item_from_different_restaurant():
    CLIENT.reset()
    r1 = make_restaurant("R1"); r2 = make_restaurant("R2", coords=(40.8, -74.1))
    c = make_customer()
    m_at_r2 = add_menu(r2["id"])
    s, b = CLIENT.request("POST", "/api/orders", role="Customer", user_id=c["id"],
                          body={"customer_id": c["id"], "restaurant_id": r1["id"],
                                "items": [{"menu_item_id": m_at_r2["id"], "quantity": 1}]})
    assert s == 422 and b["data"]["error_id"] == "ERR_RESTAURANT_UNAVAILABLE", (s, b)


# === Customer ABUSIVE_RETURN deducts credit_balance via fine ===
def t_abusive_fine_deducts_credit():
    CLIENT.reset()
    r = make_restaurant(); c = make_customer()
    rider = make_rider(); go_online(rider)
    from store import STORE
    STORE.customers[c["id"]]["trust_score"] = 0.2
    STORE.customers[c["id"]]["credit_balance_cents"] = 10000
    # Run a delivery
    m = add_menu(r["id"], price=3000)
    o = place_order(c["id"], r["id"], [{"menu_item_id": m["id"], "quantity": 1}])
    CLIENT.request("POST", f"/api/orders/{o['id']}/accept", role="Restaurant", user_id=r["id"])
    CLIENT.request("POST", f"/api/orders/{o['id']}/start-preparing", role="Restaurant", user_id=r["id"])
    a = next(a for a in STORE.assignments.values() if a["order_id"] == o["id"])
    CLIENT.request("POST", f"/api/assignments/{a['id']}/accept", role="Rider", user_id=rider["id"])
    CLIENT.request("POST", f"/api/orders/{o['id']}/ready", role="Restaurant", user_id=r["id"])
    CLIENT.request("POST", f"/api/assignments/{a['id']}/pickup", role="Rider", user_id=rider["id"])
    CLIENT.request("POST", f"/api/assignments/{a['id']}/deliver", role="Rider", user_id=rider["id"])
    credit_before = STORE.customers[c["id"]]["credit_balance_cents"]
    # Open + approve return with reason QUALITY_ISSUE — abusive fine = approved cents
    s, ret = CLIENT.request("POST", f"/api/orders/{o['id']}/returns",
                            role="Customer", user_id=c["id"],
                            body={"reason": "QUALITY_ISSUE", "requested_refund_cents": 1000})
    assert s == 201, (s, ret)
    # Approval credits 1000, then ABUSIVE_RETURN fine of 1000 deducts 1000 from credit.
    s, ap = CLIENT.request("POST", f"/api/returns/{ret['data']['id']}/approve",
                           role="CustomerService", user_id="cs",
                           body={"approved_refund_cents": 1000})
    assert s == 200, (s, ap)
    credit_after = STORE.customers[c["id"]]["credit_balance_cents"]
    # +1000 from approve, -1000 from abusive fine → net 0
    assert credit_after == credit_before, (credit_before, credit_after)


# === WorkOrder close only from RESOLVED ===
def t_wo_close_only_from_resolved():
    CLIENT.reset()
    c = make_customer()
    s, b = CLIENT.request("POST", "/api/work-orders", role="Customer", user_id=c["id"],
                          body={"opened_by_role": "CUSTOMER", "opened_by_id": c["id"],
                                "category": "OTHER"})
    wid = b["data"]["id"]
    # Try close while OPEN
    s, b = CLIENT.request("POST", f"/api/work-orders/{wid}/close",
                          role="CustomerService", user_id="cs")
    assert s == 409 and b["data"]["error_id"] == "ERR_INVALID_STATE", (s, b)


# === Fine query scope for Customer ===
def t_fine_query_scope_customer():
    CLIENT.reset()
    r = make_restaurant(); c = make_customer(); c2 = make_customer(phone="999")
    from store import STORE
    STORE.customers[c["id"]]["trust_score"] = 0.0
    rider = make_rider(); go_online(rider)
    # Deliver, then return → abusive fine on c
    m = add_menu(r["id"], price=3000)
    o = place_order(c["id"], r["id"], [{"menu_item_id": m["id"], "quantity": 1}])
    CLIENT.request("POST", f"/api/orders/{o['id']}/accept", role="Restaurant", user_id=r["id"])
    CLIENT.request("POST", f"/api/orders/{o['id']}/start-preparing", role="Restaurant", user_id=r["id"])
    a = next(a for a in STORE.assignments.values() if a["order_id"] == o["id"])
    CLIENT.request("POST", f"/api/assignments/{a['id']}/accept", role="Rider", user_id=rider["id"])
    CLIENT.request("POST", f"/api/orders/{o['id']}/ready", role="Restaurant", user_id=r["id"])
    CLIENT.request("POST", f"/api/assignments/{a['id']}/pickup", role="Rider", user_id=rider["id"])
    CLIENT.request("POST", f"/api/assignments/{a['id']}/deliver", role="Rider", user_id=rider["id"])
    s, ret = CLIENT.request("POST", f"/api/orders/{o['id']}/returns",
                            role="Customer", user_id=c["id"],
                            body={"reason": "QUALITY_ISSUE", "requested_refund_cents": 500})
    CLIENT.request("POST", f"/api/returns/{ret['data']['id']}/approve",
                   role="CustomerService", user_id="cs",
                   body={"approved_refund_cents": 500})
    # Customer c queries their own fines — should work.
    s, b = CLIENT.request("GET", f"/api/fines?subject_type=CUSTOMER&subject_id={c['id']}",
                          role="Customer", user_id=c["id"])
    assert s == 200 and len(b["data"]) >= 1, (s, b)
    # Customer c2 querying c's fines — FORBIDDEN.
    s, b = CLIENT.request("GET", f"/api/fines?subject_type=CUSTOMER&subject_id={c['id']}",
                          role="Customer", user_id=c2["id"])
    assert s == 403, (s, b)
    # PlatformAdmin can query any.
    s, b = CLIENT.request("GET", f"/api/fines?subject_type=CUSTOMER&subject_id={c['id']}",
                          role="PlatformAdmin", user_id="admin")
    assert s == 200, (s, b)


# === Fines query for Restaurant scope ===
def t_fine_query_restaurant_only_own():
    CLIENT.reset()
    r = make_restaurant(); r2 = make_restaurant("R2", coords=(40.8, -74.1))
    s, b = CLIENT.request("GET", f"/api/fines?subject_type=RESTAURANT&subject_id={r2['id']}",
                          role="Restaurant", user_id=r["id"])
    assert s == 403, (s, b)


# === Fine read RBAC ===
def t_fine_read_scope():
    CLIENT.reset()
    r = make_restaurant(); c = make_customer()
    rider = make_rider(); go_online(rider)
    from store import STORE
    m = add_menu(r["id"], price=2000)
    o = place_order(c["id"], r["id"], [{"menu_item_id": m["id"], "quantity": 1}])
    CLIENT.request("POST", f"/api/orders/{o['id']}/accept", role="Restaurant", user_id=r["id"])
    CLIENT.request("POST", f"/api/orders/{o['id']}/start-preparing", role="Restaurant", user_id=r["id"])
    a = next(a for a in STORE.assignments.values() if a["order_id"] == o["id"])
    CLIENT.request("POST", f"/api/assignments/{a['id']}/accept", role="Rider", user_id=rider["id"])
    # Rider cancels → NO_SHOW fine on rider
    CLIENT.request("POST", f"/api/assignments/{a['id']}/cancel", role="Rider", user_id=rider["id"])
    fine = next(f for f in STORE.fines.values() if f["subject_id"] == rider["id"])
    # Rider can read own
    s, b = CLIENT.request("GET", f"/api/fines/{fine['id']}", role="Rider", user_id=rider["id"])
    assert s == 200, (s, b)
    # Another rider can't
    rider2 = make_rider("rr2"); go_online(rider2)
    s, b = CLIENT.request("GET", f"/api/fines/{fine['id']}", role="Rider", user_id=rider2["id"])
    assert s == 403, (s, b)


# === Menu-item update only by owner / admin ===
def t_menu_item_patch_ownership():
    CLIENT.reset()
    r = make_restaurant(); r2 = make_restaurant("R2", coords=(40.8, -74.1))
    m = add_menu(r["id"])
    # Another restaurant can't patch
    s, b = CLIENT.request("PATCH", f"/api/menu-items/{m['id']}",
                          role="Restaurant", user_id=r2["id"],
                          body={"price_cents": 1500})
    assert s == 403, (s, b)
    # Owner can
    s, b = CLIENT.request("PATCH", f"/api/menu-items/{m['id']}",
                          role="Restaurant", user_id=r["id"],
                          body={"price_cents": 1500})
    assert s == 200, (s, b)


# === Menu item price boundary ===
def t_menu_item_price_boundary():
    CLIENT.reset()
    r = make_restaurant()
    # 0 → invalid
    s, b = CLIENT.request("POST", f"/api/restaurants/{r['id']}/menu-items",
                          role="Restaurant", user_id=r["id"],
                          body={"name": "x", "price_cents": 0})
    assert s == 422, (s, b)
    # 1_000_001 → invalid
    s, b = CLIENT.request("POST", f"/api/restaurants/{r['id']}/menu-items",
                          role="Restaurant", user_id=r["id"],
                          body={"name": "x", "price_cents": 1_000_001})
    assert s == 422, (s, b)
    # 1 → ok
    s, b = CLIENT.request("POST", f"/api/restaurants/{r['id']}/menu-items",
                          role="Restaurant", user_id=r["id"],
                          body={"name": "x", "price_cents": 1})
    assert s == 201, (s, b)


# === Restaurant reinstate ===
def t_restaurant_reinstate():
    CLIENT.reset()
    r = make_restaurant()
    rider = make_rider(); go_online(rider)
    # Force suspension by manipulating rider metrics? No — restaurant suspend works without preconditions.
    s, b = CLIENT.request("POST", f"/api/restaurants/{r['id']}/suspend",
                          role="PlatformAdmin", user_id="admin")
    assert s == 200 and b["data"]["status"] == "SUSPENDED"
    s, b = CLIENT.request("POST", f"/api/restaurants/{r['id']}/reinstate",
                          role="PlatformAdmin", user_id="admin")
    assert s == 200 and b["data"]["status"] == "ACTIVE"
    # Reinstate from PENDING_APPROVAL should fail
    s, b = CLIENT.request("POST", "/api/restaurants", role="PlatformAdmin", user_id="admin",
                          body={"name": "Q", "address": "x", "lat": 40.0, "lng": -74.0})
    rid = b["data"]["id"]
    s, b = CLIENT.request("POST", f"/api/restaurants/{rid}/reinstate",
                          role="PlatformAdmin", user_id="admin")
    assert s == 409, (s, b)


# === Distance rounding 1 decimal ===
def t_distance_rounded_to_one_decimal():
    """A 1.05 km distance should round to 1.1 → 2 bands (ceil(1.1) = 2)."""
    CLIENT.reset()
    # Use lat differences such that distance ≈ 1.05 km
    r = make_restaurant("R", coords=(40.0, -74.0))
    # 0.00945° lat ≈ 1.052 km
    c = make_customer(coords=(40.00945, -74.0))
    m = add_menu(r["id"])
    o = place_order(c["id"], r["id"], [{"menu_item_id": m["id"], "quantity": 1}])
    # distance_km should round to 1.1
    assert o["distance_km"] == 1.1, o["distance_km"]
    # Off-peak provisional fee: 300 + 120*ceil(1.1) = 300 + 240 = 540
    # But this depends on whether it's peak — let's just assert the formula
    expected_bands = 2
    expected_fee = 300 + 120 * expected_bands + (200 if o["is_peak"] else 0)
    assert o["provisional_delivery_fee_cents"] == expected_fee, (o,)


# === Restaurant CLOSED is terminal ===
def t_restaurant_cannot_close_via_endpoint():
    """PRD: CLOSED is a terminal lifecycle bucket but no endpoint sets it.
    Just confirm reinstate from CLOSED isn't possible (can't reach CLOSED via API)."""
    CLIENT.reset()
    r = make_restaurant()
    # No /close endpoint exists in the API surface — this is fine.
    s, b = CLIENT.request("POST", f"/api/restaurants/{r['id']}/close",
                          role="PlatformAdmin", user_id="admin")
    assert s == 404, (s, b)  # endpoint doesn't exist


# === Bonus tier exact boundary scores ===
def t_bonus_tier_exact_900_is_platinum():
    from bonus import compute_bonus_tier
    # 0.6*on + 0.3*acc + 0.1*(rating/5) — pick values that score exactly 0.900
    # on=1, acc=1, rating=0 → 0.6 + 0.3 + 0 = 0.9
    assert compute_bonus_tier(1.0, 1.0, 0.0) == "PLATINUM"
    # 0.6*on + 0.3*acc + 0.1*(rating/5) = 0.8 → on=1, acc=0.667, rating=0
    # Actually use: on=0.5, acc=1.0, rating=5.0 → 0.3+0.3+0.1 = 0.7 → SILVER
    assert compute_bonus_tier(0.5, 1.0, 5.0) == "SILVER"
    # 0.0 → BRONZE
    assert compute_bonus_tier(0.0, 0.0, 0.0) == "BRONZE"


# === payment_status FULLY_REFUNDED when approved == subtotal ===
def t_fully_refunded_status():
    CLIENT.reset()
    r = make_restaurant(); c = make_customer()
    rider = make_rider(); go_online(rider)
    from store import STORE
    m = add_menu(r["id"], price=3000)
    o = place_order(c["id"], r["id"], [{"menu_item_id": m["id"], "quantity": 1}])
    CLIENT.request("POST", f"/api/orders/{o['id']}/accept", role="Restaurant", user_id=r["id"])
    CLIENT.request("POST", f"/api/orders/{o['id']}/start-preparing", role="Restaurant", user_id=r["id"])
    a = next(a for a in STORE.assignments.values() if a["order_id"] == o["id"])
    CLIENT.request("POST", f"/api/assignments/{a['id']}/accept", role="Rider", user_id=rider["id"])
    CLIENT.request("POST", f"/api/orders/{o['id']}/ready", role="Restaurant", user_id=r["id"])
    CLIENT.request("POST", f"/api/assignments/{a['id']}/pickup", role="Rider", user_id=rider["id"])
    CLIENT.request("POST", f"/api/assignments/{a['id']}/deliver", role="Rider", user_id=rider["id"])
    s, ret = CLIENT.request("POST", f"/api/orders/{o['id']}/returns",
                            role="Customer", user_id=c["id"],
                            body={"reason": "WRONG_ITEM", "requested_refund_cents": 3000})
    s, ap = CLIENT.request("POST", f"/api/returns/{ret['data']['id']}/approve",
                           role="CustomerService", user_id="cs",
                           body={"approved_refund_cents": 3000})
    s, ob = CLIENT.request("GET", f"/api/orders/{o['id']}", role="PlatformAdmin", user_id="admin")
    assert ob["data"]["payment_status"] == "FULLY_REFUNDED", ob["data"]


# === order with quantity > 1 computes subtotal correctly ===
def t_subtotal_quantity_aware():
    CLIENT.reset()
    r = make_restaurant(); c = make_customer()
    m = add_menu(r["id"], price=500)
    o = place_order(c["id"], r["id"], [{"menu_item_id": m["id"], "quantity": 4}])
    assert o["subtotal_cents"] == 2000, o


# === Assignment record has no version/updated_at ===
def t_assignment_no_version_field():
    CLIENT.reset()
    r = make_restaurant(); c = make_customer()
    rider = make_rider(); go_online(rider)
    from store import STORE
    m = add_menu(r["id"])
    o = place_order(c["id"], r["id"], [{"menu_item_id": m["id"], "quantity": 1}])
    CLIENT.request("POST", f"/api/orders/{o['id']}/accept", role="Restaurant", user_id=r["id"])
    CLIENT.request("POST", f"/api/orders/{o['id']}/start-preparing", role="Restaurant", user_id=r["id"])
    a = next(a for a in STORE.assignments.values() if a["order_id"] == o["id"])
    s, b = CLIENT.request("GET", f"/api/assignments/{a['id']}",
                          role="PlatformAdmin", user_id="admin")
    assert "version" not in b["data"]
    assert "updated_at" not in b["data"]


# === Fine record has no version/updated_at ===
def t_fine_no_version_field():
    CLIENT.reset()
    r = make_restaurant(); c = make_customer()
    rider = make_rider(); go_online(rider)
    from store import STORE
    m = add_menu(r["id"])
    o = place_order(c["id"], r["id"], [{"menu_item_id": m["id"], "quantity": 1}])
    CLIENT.request("POST", f"/api/orders/{o['id']}/accept", role="Restaurant", user_id=r["id"])
    CLIENT.request("POST", f"/api/orders/{o['id']}/start-preparing", role="Restaurant", user_id=r["id"])
    a = next(a for a in STORE.assignments.values() if a["order_id"] == o["id"])
    CLIENT.request("POST", f"/api/assignments/{a['id']}/accept", role="Rider", user_id=rider["id"])
    CLIENT.request("POST", f"/api/assignments/{a['id']}/cancel", role="Rider", user_id=rider["id"])
    fine = next(f for f in STORE.fines.values() if f["reason"] == "RIDER_NO_SHOW")
    s, b = CLIENT.request("GET", f"/api/fines/{fine['id']}",
                          role="PlatformAdmin", user_id="admin")
    assert "version" not in b["data"]
    assert "updated_at" not in b["data"]


# === Suspended restaurant cancels PLACED orders with payment_status VOIDED ===
def t_suspend_cancels_with_voided_payment():
    CLIENT.reset()
    r = make_restaurant(); c = make_customer()
    m = add_menu(r["id"])
    o = place_order(c["id"], r["id"], [{"menu_item_id": m["id"], "quantity": 1}])
    s, b = CLIENT.request("POST", f"/api/restaurants/{r['id']}/suspend",
                          role="PlatformAdmin", user_id="admin")
    s, ob = CLIENT.request("GET", f"/api/orders/{o['id']}", role="PlatformAdmin", user_id="admin")
    assert ob["data"]["status"] == "CANCELLED"
    assert ob["data"]["payment_status"] == "VOIDED", ob["data"]


# === order list filter by status ===
def t_orders_list_status_filter():
    CLIENT.reset()
    r = make_restaurant(); c = make_customer()
    m = add_menu(r["id"])
    o1 = place_order(c["id"], r["id"], [{"menu_item_id": m["id"], "quantity": 1}])
    o2 = place_order(c["id"], r["id"], [{"menu_item_id": m["id"], "quantity": 1}])
    CLIENT.request("POST", f"/api/orders/{o1['id']}/accept", role="Restaurant", user_id=r["id"])
    s, b = CLIENT.request("GET", "/api/orders?status=PLACED",
                          role="PlatformAdmin", user_id="admin")
    assert s == 200
    ids = [x["id"] for x in b["data"]]
    assert o2["id"] in ids and o1["id"] not in ids


# === Empty pool dispatch from start-preparing → no offer ===
def t_start_preparing_no_riders_no_offer():
    CLIENT.reset()
    r = make_restaurant(); c = make_customer()
    m = add_menu(r["id"])
    o = place_order(c["id"], r["id"], [{"menu_item_id": m["id"], "quantity": 1}])
    CLIENT.request("POST", f"/api/orders/{o['id']}/accept", role="Restaurant", user_id=r["id"])
    s, b = CLIENT.request("POST", f"/api/orders/{o['id']}/start-preparing",
                          role="Restaurant", user_id=r["id"])
    # PRD §3.5: start-preparing advances order, also opens dispatch but no error if pool empty.
    assert s == 200
    from store import STORE
    assert STORE.orders[o["id"]]["status"] == "PREPARING"
    live = [a for a in STORE.assignments.values()
            if a["order_id"] == o["id"] and a["status"] == "OFFERED"]
    assert live == []


# === Auth empty string ===
def t_auth_empty_user_id():
    CLIENT.reset()
    # X-User-ID empty → still treated as present?
    s, b = CLIENT.request("GET", "/api/restaurants", role="PlatformAdmin", user_id="")
    # PRD §2.1: missing header → ERR_AUTH_REQUIRED. Empty string is debatable but treated as missing.
    assert s == 401, (s, b)


# === ERR_VALIDATION for malformed body ===
def t_generic_validation_error():
    CLIENT.reset()
    s, b = CLIENT.request("POST", "/api/restaurants", role="PlatformAdmin", user_id="admin",
                          body={"name": ""})  # missing address, empty name
    assert s == 422 and b["data"]["error_id"] in ("ERR_VALIDATION",), (s, b)


# === Customer can read own work order, not others ===
def t_wo_read_scope():
    CLIENT.reset()
    c = make_customer(); c2 = make_customer(phone="999")
    s, b = CLIENT.request("POST", "/api/work-orders",
                          role="Customer", user_id=c["id"],
                          body={"opened_by_role": "CUSTOMER", "opened_by_id": c["id"],
                                "category": "OTHER"})
    wid = b["data"]["id"]
    s, b = CLIENT.request("GET", f"/api/work-orders/{wid}", role="Customer", user_id=c["id"])
    assert s == 200
    s, b = CLIENT.request("GET", f"/api/work-orders/{wid}", role="Customer", user_id=c2["id"])
    assert s == 403, (s, b)


TESTS = [
    ("override boundary low 0.05", t_override_boundary_low),
    ("override boundary high 0.35", t_override_boundary_high),
    ("override outside range rejected", t_override_outside_range),
    ("dispatch excludes only live OFFERED holders", t_dispatch_excludes_only_live_holders),
    ("dispatch pool empty → INVALID_STATE", t_dispatch_pool_empty_returns_invalid_state),
    ("dispatch tie-breaker: most recent rider wins", t_dispatch_tiebreaker_created_at_desc),
    ("orders list filter by rider_id", t_orders_list_by_rider),
    ("menu_item from different restaurant → UNAVAILABLE", t_menu_item_from_different_restaurant),
    ("abusive fine deducts credit balance", t_abusive_fine_deducts_credit),
    ("WO close only from RESOLVED", t_wo_close_only_from_resolved),
    ("fine query — customer scope", t_fine_query_scope_customer),
    ("fine query — restaurant only own", t_fine_query_restaurant_only_own),
    ("fine read RBAC", t_fine_read_scope),
    ("menu item patch ownership", t_menu_item_patch_ownership),
    ("menu item price boundary", t_menu_item_price_boundary),
    ("restaurant reinstate from SUSPENDED", t_restaurant_reinstate),
    ("distance rounded to 1 decimal", t_distance_rounded_to_one_decimal),
    ("restaurant has no /close endpoint", t_restaurant_cannot_close_via_endpoint),
    ("bonus tier 0.900 = PLATINUM exact", t_bonus_tier_exact_900_is_platinum),
    ("FULLY_REFUNDED status on full refund", t_fully_refunded_status),
    ("subtotal quantity aware", t_subtotal_quantity_aware),
    ("assignment has no version/updated_at", t_assignment_no_version_field),
    ("fine has no version/updated_at", t_fine_no_version_field),
    ("suspend cancels PLACED with VOIDED payment", t_suspend_cancels_with_voided_payment),
    ("orders list filter by status", t_orders_list_status_filter),
    ("start-preparing with no riders → no offer, order still PREPARING", t_start_preparing_no_riders_no_offer),
    ("auth — empty user id → 401", t_auth_empty_user_id),
    ("generic ERR_VALIDATION for malformed body", t_generic_validation_error),
    ("WO read scope — only opener", t_wo_read_scope),
]

if __name__ == "__main__":
    for name, fn in TESTS:
        R.run(name, fn)
    ok = R.report()
    sys.exit(0 if ok else 1)
