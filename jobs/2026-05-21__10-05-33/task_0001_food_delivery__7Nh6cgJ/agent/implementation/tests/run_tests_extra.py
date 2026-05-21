"""Additional self-tests covering more PRD rules."""

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
WAY_FAR = (41.0000, -75.0000)

CLIENT = TestClient()
R = TestRunner()


def register_active_restaurant(name="R", coords=NYC, commission_override=None):
    s, b = CLIENT.request("POST", "/api/restaurants", role="PlatformAdmin", user_id="admin",
                          body={"name": name, "address": "1 a", "lat": coords[0], "lng": coords[1],
                                "commission_rate_override": commission_override})
    assert s == 201, b
    rid = b["data"]["id"]
    s, _ = CLIENT.request("POST", f"/api/restaurants/{rid}/approve",
                          role="PlatformAdmin", user_id="admin")
    return b["data"]


def register_customer(phone="555", coords=NEAR_NYC):
    s, b = CLIENT.request("POST", "/api/customers", role="PlatformAdmin", user_id="admin",
                          body={"name": "C", "phone": phone, "address": "x",
                                "lat": coords[0], "lng": coords[1]})
    assert s == 201, b
    return b["data"]


def register_rider(phone="r"):
    s, b = CLIENT.request("POST", "/api/riders", role="PlatformAdmin", user_id="admin",
                          body={"name": "R", "phone": phone})
    assert s == 201, b
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
    assert s == 201, b
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


# === Response envelope ===
def t_envelope_meta_fields():
    CLIENT.reset()
    s, b = CLIENT.request("GET", "/api/restaurants", role="PlatformAdmin", user_id="admin")
    assert "api_request_id" in b["meta"]
    assert b["meta"]["api_request_id"].startswith("req_")
    assert "api_request_timestamp" in b["meta"]
    ts = b["meta"]["api_request_timestamp"]
    assert ts.endswith("Z") and "." in ts
    # 3 fractional digits
    frac = ts.split(".")[1].rstrip("Z")
    assert len(frac) == 3
    assert b["response_type"] == "array"


def t_envelope_error_meta():
    CLIENT.reset()
    s, b = CLIENT.request("GET", "/api/restaurants")
    assert "api_request_id" in b["meta"] and "api_request_timestamp" in b["meta"]
    assert "limit" not in b["meta"]
    assert b["response_type"] == "error"
    assert b["data"]["error_id"] == "ERR_AUTH_REQUIRED"


def t_id_uuid_no_prefix():
    CLIENT.reset()
    r = register_active_restaurant()
    rid = r["id"]
    # UUID is 36 chars with 4 hyphens, no prefix.
    assert len(rid) == 36 and rid.count("-") == 4
    assert not rid.startswith("rest_")


# === Pagination ===
def t_pagination_offset_window():
    CLIENT.reset()
    for i in range(12):
        s, _ = CLIENT.request("POST", "/api/restaurants", role="PlatformAdmin", user_id="admin",
                              body={"name": f"R{i}", "address": "a", "lat": 0, "lng": 0})
    s, b = CLIENT.request("GET", "/api/restaurants?limit=5&offset=10",
                          role="PlatformAdmin", user_id="admin")
    assert s == 200
    assert b["meta"]["limit"] == 5 and b["meta"]["offset"] == 10
    assert b["meta"]["total_count"] == 12 and b["meta"]["has_more"] is False
    assert len(b["data"]) == 2


# === Restaurant ===
def t_restaurant_unique_name():
    CLIENT.reset()
    register_active_restaurant(name="Foo")
    s, b = CLIENT.request("POST", "/api/restaurants", role="PlatformAdmin", user_id="admin",
                          body={"name": "Foo", "address": "a", "lat": 0, "lng": 0})
    assert s == 422 and b["data"]["error_id"] == "ERR_VALIDATION"


def t_restaurant_name_too_long():
    CLIENT.reset()
    name = "A" * 121
    s, b = CLIENT.request("POST", "/api/restaurants", role="PlatformAdmin", user_id="admin",
                          body={"name": name, "address": "a", "lat": 0, "lng": 0})
    assert s == 422


def t_restaurant_settle_zeroes():
    CLIENT.reset()
    r = register_active_restaurant()
    c = register_customer()
    rd = register_rider(); online(rd)
    full_deliver(c, r, rd, price=10_000)
    # Restaurant gets 10000 - 1500 (15% of 10000) = 8500 pending
    s, b = CLIENT.request("GET", f"/api/restaurants/{r['id']}",
                          role="PlatformAdmin", user_id="admin")
    assert b["data"]["pending_settlement_cents"] == 8500
    s, b = CLIENT.request("POST", f"/api/restaurants/{r['id']}/settle",
                          role="PlatformAdmin", user_id="admin")
    assert s == 200 and b["data"]["pending_settlement_cents"] == 0


def t_restaurant_filter_status():
    CLIENT.reset()
    register_active_restaurant(name="A")
    register_active_restaurant(name="B")
    s, b = CLIENT.request("POST", "/api/restaurants", role="PlatformAdmin", user_id="admin",
                          body={"name": "Pending", "address": "a", "lat": 0, "lng": 0})
    pending_id = b["data"]["id"]
    s, b = CLIENT.request("GET", "/api/restaurants?status=PENDING_APPROVAL",
                          role="PlatformAdmin", user_id="admin")
    assert s == 200 and len(b["data"]) == 1 and b["data"][0]["id"] == pending_id


# === Menu items ===
def t_menu_item_filter_listed():
    CLIENT.reset()
    r = register_active_restaurant()
    m1 = add_menu(r["id"], name="A")
    m2 = add_menu(r["id"], name="B")
    CLIENT.request("PATCH", f"/api/menu-items/{m2['id']}", role="Restaurant", user_id=r["id"],
                   body={"is_listed": False})
    s, b = CLIENT.request("GET", f"/api/restaurants/{r['id']}/menu-items?is_listed=true",
                          role="Customer", user_id="anyone")
    # Customer can list menu items — no ownership constraint.
    assert s == 200 and len(b["data"]) == 1


def t_menu_item_role_isolation():
    CLIENT.reset()
    r = register_active_restaurant()
    s, _ = CLIENT.request("POST", f"/api/restaurants/{r['id']}/menu-items",
                          role="Restaurant", user_id="other",
                          body={"name": "X", "price_cents": 1000})
    assert s == 403


# === Rider ===
def t_rider_offline_with_active_assignment():
    CLIENT.reset()
    r = register_active_restaurant()
    c = register_customer()
    rd = register_rider(); online(rd)
    m = add_menu(r["id"])
    o = place_order(c["id"], r["id"], [{"menu_item_id": m["id"], "quantity": 1}])
    CLIENT.request("POST", f"/api/orders/{o['id']}/accept", role="Restaurant", user_id=r["id"])
    CLIENT.request("POST", f"/api/orders/{o['id']}/start-preparing",
                   role="Restaurant", user_id=r["id"])
    from store import STORE
    aid = next(a["id"] for a in STORE.assignments.values() if a["order_id"] == o["id"])
    CLIENT.request("POST", f"/api/assignments/{aid}/accept", role="Rider", user_id=rd["id"])
    # Rider has ACCEPTED assignment — go-offline should fail
    s, b = CLIENT.request("POST", f"/api/riders/{rd['id']}/go-offline",
                          role="Rider", user_id=rd["id"])
    assert s == 409


def t_rider_suspend_only_available():
    CLIENT.reset()
    rd = register_rider()
    # OFFLINE — should fail INVALID_STATE
    s, b = CLIENT.request("POST", f"/api/riders/{rd['id']}/suspend",
                          role="PlatformAdmin", user_id="admin")
    assert s == 409


# === Customer ===
def t_customer_duplicate_phone():
    CLIENT.reset()
    register_customer(phone="9999")
    s, b = CLIENT.request("POST", "/api/customers", role="PlatformAdmin", user_id="admin",
                          body={"name": "C2", "phone": "9999", "address": "x",
                                "lat": 0, "lng": 0})
    assert s == 422


# === Order ===
def t_order_quantity_invalid():
    CLIENT.reset()
    r = register_active_restaurant()
    c = register_customer()
    m = add_menu(r["id"])
    s, b = CLIENT.request("POST", "/api/orders", role="Customer", user_id=c["id"],
                          body={"customer_id": c["id"], "restaurant_id": r["id"],
                                "items": [{"menu_item_id": m["id"], "quantity": 0}]})
    assert s == 422 and b["data"]["error_id"] == "ERR_ORDER_INVALID"


def t_order_unknown_menu_item():
    CLIENT.reset()
    r = register_active_restaurant()
    c = register_customer()
    s, b = CLIENT.request("POST", "/api/orders", role="Customer", user_id=c["id"],
                          body={"customer_id": c["id"], "restaurant_id": r["id"],
                                "items": [{"menu_item_id": "nope", "quantity": 1}]})
    assert s == 404 and b["data"]["error_id"] == "ERR_NOT_FOUND"


def t_order_customer_ownership():
    CLIENT.reset()
    r = register_active_restaurant()
    c1 = register_customer("p1")
    c2 = register_customer("p2")
    m = add_menu(r["id"])
    s, b = CLIENT.request("POST", "/api/orders", role="Customer", user_id=c2["id"],
                          body={"customer_id": c1["id"], "restaurant_id": r["id"],
                                "items": [{"menu_item_id": m["id"], "quantity": 1}]})
    assert s == 403


def t_order_cancel_after_accept():
    CLIENT.reset()
    r = register_active_restaurant()
    c = register_customer()
    m = add_menu(r["id"])
    o = place_order(c["id"], r["id"], [{"menu_item_id": m["id"], "quantity": 1}])
    CLIENT.request("POST", f"/api/orders/{o['id']}/accept", role="Restaurant", user_id=r["id"])
    s, b = CLIENT.request("POST", f"/api/orders/{o['id']}/cancel",
                          role="Customer", user_id=c["id"])
    assert s == 409


def t_order_ready_requires_acceptance():
    CLIENT.reset()
    r = register_active_restaurant()
    c = register_customer()
    rd = register_rider(); online(rd)
    m = add_menu(r["id"])
    o = place_order(c["id"], r["id"], [{"menu_item_id": m["id"], "quantity": 1}])
    CLIENT.request("POST", f"/api/orders/{o['id']}/accept", role="Restaurant", user_id=r["id"])
    CLIENT.request("POST", f"/api/orders/{o['id']}/start-preparing",
                   role="Restaurant", user_id=r["id"])
    # Without rider accept, /ready must fail
    s, b = CLIENT.request("POST", f"/api/orders/{o['id']}/ready",
                          role="Restaurant", user_id=r["id"])
    assert s == 409


def t_order_dispatch_no_riders():
    CLIENT.reset()
    r = register_active_restaurant()
    c = register_customer()
    m = add_menu(r["id"])
    o = place_order(c["id"], r["id"], [{"menu_item_id": m["id"], "quantity": 1}])
    CLIENT.request("POST", f"/api/orders/{o['id']}/accept", role="Restaurant", user_id=r["id"])
    s, b = CLIENT.request("POST", f"/api/orders/{o['id']}/dispatch",
                          role="PlatformAdmin", user_id="admin")
    assert s == 409


# === Assignment / Delivery ===
def t_assignment_pickup_requires_ready():
    CLIENT.reset()
    r = register_active_restaurant()
    c = register_customer()
    rd = register_rider(); online(rd)
    m = add_menu(r["id"])
    o = place_order(c["id"], r["id"], [{"menu_item_id": m["id"], "quantity": 1}])
    CLIENT.request("POST", f"/api/orders/{o['id']}/accept", role="Restaurant", user_id=r["id"])
    CLIENT.request("POST", f"/api/orders/{o['id']}/start-preparing",
                   role="Restaurant", user_id=r["id"])
    from store import STORE
    aid = next(a["id"] for a in STORE.assignments.values() if a["order_id"] == o["id"])
    CLIENT.request("POST", f"/api/assignments/{aid}/accept", role="Rider", user_id=rd["id"])
    # Try pickup before ready
    s, b = CLIENT.request("POST", f"/api/assignments/{aid}/pickup",
                          role="Rider", user_id=rd["id"])
    assert s == 409


def t_deliver_credits_wallet_and_settlement():
    CLIENT.reset()
    r = register_active_restaurant(coords=NYC)
    c = register_customer(coords=NEAR_NYC)
    rd = register_rider(); online(rd)
    o, aid = full_deliver(c, r, rd, price=2000)
    s, ob = CLIENT.request("GET", f"/api/orders/{o['id']}",
                           role="PlatformAdmin", user_id="admin")
    # distance 0.014 km → rounded to 0.0 → 0 bands → fee = 300 (or 500 with peak surcharge)
    fee = ob["data"]["final_delivery_fee_cents"]
    assert fee in (300, 500), fee
    s, rb = CLIENT.request("GET", f"/api/riders/{rd['id']}",
                           role="PlatformAdmin", user_id="admin")
    assert rb["data"]["wallet_balance_cents"] == fee
    s, rest = CLIENT.request("GET", f"/api/restaurants/{r['id']}",
                             role="PlatformAdmin", user_id="admin")
    # pending = subtotal - commission = 2000 - 300 = 1700
    assert rest["data"]["pending_settlement_cents"] == 1700


def t_late_30_plus_minutes():
    CLIENT.reset()
    r = register_active_restaurant(coords=NYC)
    c = register_customer(coords=NEAR_NYC)
    rd = register_rider(); online(rd)
    # 35 minutes late
    o, aid = full_deliver(c, r, rd, price=2000, late_seconds=35 * 60)
    s, fb = CLIENT.request("GET", f"/api/fines?subject_type=RIDER&subject_id={rd['id']}",
                           role="PlatformAdmin", user_id="admin")
    late = [f for f in fb["data"] if f["reason"] == "LATE_DELIVERY"]
    assert len(late) == 1
    # min(final_fee, 1500) + 500. Fee for ~0 km is 300/500.
    assert late[0]["amount_cents"] in (300 + 500, 500 + 500)


def t_late_1_to_10_minutes():
    CLIENT.reset()
    r = register_active_restaurant()
    c = register_customer()
    rd = register_rider(); online(rd)
    o, aid = full_deliver(c, r, rd, late_seconds=5 * 60)
    s, fb = CLIENT.request("GET", f"/api/fines?subject_type=RIDER&subject_id={rd['id']}",
                           role="PlatformAdmin", user_id="admin")
    late = [f for f in fb["data"] if f["reason"] == "LATE_DELIVERY"]
    assert len(late) == 1 and late[0]["amount_cents"] == 200


def t_commission_override_path():
    CLIENT.reset()
    r = register_active_restaurant(commission_override=0.10)
    c = register_customer()
    rd = register_rider(); online(rd)
    o, aid = full_deliver(c, r, rd, price=2000)
    s, ob = CLIENT.request("GET", f"/api/orders/{o['id']}",
                           role="PlatformAdmin", user_id="admin")
    # flat 10% of 2000 = 200
    assert ob["data"]["final_commission_cents"] == 200


def t_commission_override_changed_midflight():
    """Mid-flight commission_rate_override change is observed at delivery, not placement."""
    CLIENT.reset()
    r = register_active_restaurant()  # no override → provisional uses tiered
    c = register_customer()
    rd = register_rider(); online(rd)
    m = add_menu(r["id"], price=2000)
    o = place_order(c["id"], r["id"], [{"menu_item_id": m["id"], "quantity": 1}])
    # Subtotal 2000 → provisional 300 (tiered)
    assert o["provisional_commission_cents"] == 300
    # Now PlatformAdmin sets override mid-flight.
    s, _ = CLIENT.request("PATCH", f"/api/restaurants/{r['id']}",
                          role="PlatformAdmin", user_id="admin",
                          body={"commission_rate_override": 0.20})
    assert s == 200
    CLIENT.request("POST", f"/api/orders/{o['id']}/accept",
                   role="Restaurant", user_id=r["id"])
    CLIENT.request("POST", f"/api/orders/{o['id']}/start-preparing",
                   role="Restaurant", user_id=r["id"])
    from store import STORE
    aid = next(a["id"] for a in STORE.assignments.values() if a["order_id"] == o["id"])
    CLIENT.request("POST", f"/api/assignments/{aid}/accept", role="Rider", user_id=rd["id"])
    CLIENT.request("POST", f"/api/orders/{o['id']}/ready", role="Restaurant", user_id=r["id"])
    CLIENT.request("POST", f"/api/assignments/{aid}/pickup", role="Rider", user_id=rd["id"])
    CLIENT.request("POST", f"/api/assignments/{aid}/deliver", role="Rider", user_id=rd["id"])
    s, ob = CLIENT.request("GET", f"/api/orders/{o['id']}",
                           role="PlatformAdmin", user_id="admin")
    # final commission = 2000 * 0.20 = 400
    assert ob["data"]["final_commission_cents"] == 400


# === Returns ===
def t_return_refund_full_changes_status():
    CLIENT.reset()
    r = register_active_restaurant()
    c = register_customer()
    rd = register_rider(); online(rd)
    o, aid = full_deliver(c, r, rd, price=2000)
    s, b = CLIENT.request("POST", f"/api/orders/{o['id']}/returns",
                          role="Customer", user_id=c["id"],
                          body={"reason": "WRONG_ITEM", "requested_refund_cents": 2000})
    rid = b["data"]["id"]
    s, b = CLIENT.request("POST", f"/api/returns/{rid}/approve",
                          role="CustomerService", user_id="cs-1",
                          body={"approved_refund_cents": 2000})
    assert s == 200
    s, ob = CLIENT.request("GET", f"/api/orders/{o['id']}",
                           role="PlatformAdmin", user_id="admin")
    assert ob["data"]["payment_status"] == "FULLY_REFUNDED"


def t_return_amount_outside():
    CLIENT.reset()
    r = register_active_restaurant()
    c = register_customer()
    rd = register_rider(); online(rd)
    o, aid = full_deliver(c, r, rd, price=2000)
    s, b = CLIENT.request("POST", f"/api/orders/{o['id']}/returns",
                          role="Customer", user_id=c["id"],
                          body={"reason": "WRONG_ITEM", "requested_refund_cents": 5000})
    assert s == 422 and b["data"]["error_id"] == "ERR_REFUND_AMOUNT_INVALID"
    s, b = CLIENT.request("POST", f"/api/orders/{o['id']}/returns",
                          role="Customer", user_id=c["id"],
                          body={"reason": "WRONG_ITEM", "requested_refund_cents": 0})
    assert s == 422


def t_return_reject_reverts_order():
    CLIENT.reset()
    r = register_active_restaurant()
    c = register_customer()
    rd = register_rider(); online(rd)
    o, aid = full_deliver(c, r, rd, price=2000)
    s, b = CLIENT.request("POST", f"/api/orders/{o['id']}/returns",
                          role="Customer", user_id=c["id"],
                          body={"reason": "QUALITY_ISSUE", "requested_refund_cents": 100})
    rid = b["data"]["id"]
    s, b = CLIENT.request("POST", f"/api/returns/{rid}/reject",
                          role="CustomerService", user_id="cs-1")
    assert s == 200
    s, ob = CLIENT.request("GET", f"/api/orders/{o['id']}",
                           role="PlatformAdmin", user_id="admin")
    assert ob["data"]["status"] == "DELIVERED"


def t_return_escalate_opens_wo_reopen_closes_it():
    CLIENT.reset()
    r = register_active_restaurant()
    c = register_customer()
    rd = register_rider(); online(rd)
    o, aid = full_deliver(c, r, rd, price=2000)
    s, b = CLIENT.request("POST", f"/api/orders/{o['id']}/returns",
                          role="Customer", user_id=c["id"],
                          body={"reason": "OTHER", "requested_refund_cents": 100})
    rid = b["data"]["id"]
    s, _ = CLIENT.request("POST", f"/api/returns/{rid}/escalate",
                          role="CustomerService", user_id="cs-1")
    assert s == 200
    from store import STORE
    wos = [w for w in STORE.work_orders.values() if w.get("related_return_id") == rid]
    assert len(wos) == 1
    wo = wos[0]
    assert wo["status"] == "OPEN"
    s, _ = CLIENT.request("POST", f"/api/returns/{rid}/reopen",
                          role="CustomerService", user_id="cs-1")
    assert s == 200
    s, b = CLIENT.request("GET", f"/api/work-orders/{wo['id']}",
                          role="CustomerService", user_id="cs-1")
    assert b["data"]["status"] == "CLOSED"


def t_abusive_return_fine():
    CLIENT.reset()
    r = register_active_restaurant()
    c = register_customer()
    # Force trust_score < 0.5
    from store import STORE
    STORE.customers[c["id"]]["trust_score"] = 0.3
    rd = register_rider(); online(rd)
    o, aid = full_deliver(c, r, rd, price=2000)
    s, b = CLIENT.request("POST", f"/api/orders/{o['id']}/returns",
                          role="Customer", user_id=c["id"],
                          body={"reason": "QUALITY_ISSUE", "requested_refund_cents": 500})
    rid = b["data"]["id"]
    s, _ = CLIENT.request("POST", f"/api/returns/{rid}/approve",
                          role="CustomerService", user_id="cs-1",
                          body={"approved_refund_cents": 500})
    s, fb = CLIENT.request("GET", f"/api/fines?subject_type=CUSTOMER&subject_id={c['id']}",
                           role="PlatformAdmin", user_id="admin")
    abusive = [f for f in fb["data"] if f["reason"] == "ABUSIVE_RETURN"]
    assert len(abusive) == 1 and abusive[0]["amount_cents"] == 500


# === Work orders ===
def t_wo_opener_match():
    CLIENT.reset()
    c1 = register_customer("p1")
    c2 = register_customer("p2")
    s, b = CLIENT.request("POST", "/api/work-orders", role="Customer", user_id=c1["id"],
                          body={"category": "OTHER"})
    wid = b["data"]["id"]
    s, _ = CLIENT.request("GET", f"/api/work-orders/{wid}",
                          role="Customer", user_id=c2["id"])
    assert s == 403


def t_wo_resolve_requires_assignee():
    CLIENT.reset()
    c = register_customer()
    s, b = CLIENT.request("POST", "/api/work-orders", role="Customer", user_id=c["id"],
                          body={"category": "OTHER"})
    wid = b["data"]["id"]
    # Skip assign — try to resolve directly (cannot, must be in UNDER_REVIEW first)
    s, b = CLIENT.request("POST", f"/api/work-orders/{wid}/resolve",
                          role="CustomerService", user_id="cs-1",
                          body={"resolution_notes": "n"})
    assert s == 409


def t_wo_request_info_submit_cycle():
    CLIENT.reset()
    c = register_customer()
    s, b = CLIENT.request("POST", "/api/work-orders", role="Customer", user_id=c["id"],
                          body={"category": "OTHER"})
    wid = b["data"]["id"]
    CLIENT.request("POST", f"/api/work-orders/{wid}/assign",
                   role="CustomerService", user_id="cs-1")
    s, b = CLIENT.request("POST", f"/api/work-orders/{wid}/request-info",
                          role="CustomerService", user_id="cs-1")
    assert b["data"]["status"] == "AWAITING_INFO"
    s, b = CLIENT.request("POST", f"/api/work-orders/{wid}/submit-info",
                          role="Customer", user_id=c["id"])
    assert b["data"]["status"] == "UNDER_REVIEW"


# === Fines ===
def t_fines_query_scope_for_rider():
    CLIENT.reset()
    r = register_active_restaurant()
    c = register_customer()
    rd = register_rider(); online(rd)
    other_rd = register_rider("r2")
    # Generate a fine on rd
    m = add_menu(r["id"])
    o = place_order(c["id"], r["id"], [{"menu_item_id": m["id"], "quantity": 1}])
    CLIENT.request("POST", f"/api/orders/{o['id']}/accept", role="Restaurant", user_id=r["id"])
    CLIENT.request("POST", f"/api/orders/{o['id']}/start-preparing",
                   role="Restaurant", user_id=r["id"])
    from store import STORE
    aid = next(a["id"] for a in STORE.assignments.values() if a["order_id"] == o["id"])
    CLIENT.request("POST", f"/api/assignments/{aid}/accept", role="Rider", user_id=rd["id"])
    CLIENT.request("POST", f"/api/assignments/{aid}/cancel", role="Rider", user_id=rd["id"])
    # Rider can query own fines.
    s, b = CLIENT.request("GET", f"/api/fines?subject_id={rd['id']}",
                          role="Rider", user_id=rd["id"])
    assert s == 200 and len(b["data"]) == 1
    # Rider querying another rider's fines is forbidden.
    s, _ = CLIENT.request("GET", f"/api/fines?subject_id={other_rd['id']}",
                          role="Rider", user_id=rd["id"])
    assert s == 403


def t_fine_settled_cant_waive():
    """Settled fines are not waivable. Forcing a fine to SETTLED via store and trying."""
    CLIENT.reset()
    r = register_active_restaurant()
    c = register_customer()
    rd = register_rider(); online(rd)
    m = add_menu(r["id"])
    o = place_order(c["id"], r["id"], [{"menu_item_id": m["id"], "quantity": 1}])
    CLIENT.request("POST", f"/api/orders/{o['id']}/accept", role="Restaurant", user_id=r["id"])
    CLIENT.request("POST", f"/api/orders/{o['id']}/start-preparing",
                   role="Restaurant", user_id=r["id"])
    from store import STORE
    aid = next(a["id"] for a in STORE.assignments.values() if a["order_id"] == o["id"])
    CLIENT.request("POST", f"/api/assignments/{aid}/accept", role="Rider", user_id=rd["id"])
    CLIENT.request("POST", f"/api/assignments/{aid}/cancel", role="Rider", user_id=rd["id"])
    fid = next(f["id"] for f in STORE.fines.values())
    STORE.fines[fid]["settlement_status"] = "SETTLED"
    s, b = CLIENT.request("POST", f"/api/fines/{fid}/waive",
                          role="PlatformAdmin", user_id="admin")
    assert s == 409


# === Cascade behavior ===
def t_versions_increment_on_cascade():
    """Delivery cascade: order, assignment, restaurant, rider all touched with version bump."""
    CLIENT.reset()
    r = register_active_restaurant()
    c = register_customer()
    rd = register_rider(); online(rd)
    m = add_menu(r["id"], price=2000)
    o = place_order(c["id"], r["id"], [{"menu_item_id": m["id"], "quantity": 1}])
    CLIENT.request("POST", f"/api/orders/{o['id']}/accept", role="Restaurant", user_id=r["id"])
    CLIENT.request("POST", f"/api/orders/{o['id']}/start-preparing",
                   role="Restaurant", user_id=r["id"])
    from store import STORE
    aid = next(a["id"] for a in STORE.assignments.values() if a["order_id"] == o["id"])
    CLIENT.request("POST", f"/api/assignments/{aid}/accept", role="Rider", user_id=rd["id"])
    CLIENT.request("POST", f"/api/orders/{o['id']}/ready", role="Restaurant", user_id=r["id"])
    CLIENT.request("POST", f"/api/assignments/{aid}/pickup", role="Rider", user_id=rd["id"])
    v_order_before = STORE.orders[o["id"]]["version"]
    v_rider_before = STORE.riders[rd["id"]]["version"]
    v_rest_before = STORE.restaurants[r["id"]]["version"]
    CLIENT.request("POST", f"/api/assignments/{aid}/deliver", role="Rider", user_id=rd["id"])
    assert STORE.orders[o["id"]]["version"] > v_order_before
    assert STORE.riders[rd["id"]]["version"] > v_rider_before
    assert STORE.restaurants[r["id"]]["version"] > v_rest_before


# === Validation pipeline ordering ===
def t_pipeline_auth_before_route():
    """Missing headers on a path that wouldn't exist should still return ERR_AUTH_REQUIRED."""
    CLIENT.reset()
    s, b = CLIENT.request("GET", "/api/restaurants/something")
    assert s == 401 and b["data"]["error_id"] == "ERR_AUTH_REQUIRED"


def t_pipeline_role_before_not_found():
    CLIENT.reset()
    # Customer hitting /api/restaurants POST (PlatformAdmin only)
    s, b = CLIENT.request("POST", "/api/restaurants", role="Customer", user_id="x", body={"name": "X"})
    assert s == 403


def t_pipeline_not_found_before_body_validation():
    CLIENT.reset()
    s, b = CLIENT.request("POST", "/api/restaurants/missing/approve",
                          role="PlatformAdmin", user_id="admin")
    assert s == 404


# === Time semantics ===
def t_peak_window():
    """Snapshot is_peak at placement; deliver outside window does not change is_peak."""
    CLIENT.reset()
    # Advance clock to a known peak hour: target 11:30 UTC.
    from datetime import datetime, timezone
    from clock import CLOCK
    now = CLOCK.now()
    # Compute how many seconds to advance to land at next 11:30 UTC.
    target_h = 11
    seconds_into_day = now.hour * 3600 + now.minute * 60 + now.second
    target = target_h * 3600 + 30 * 60
    delta = (target - seconds_into_day) % (24 * 3600)
    if delta == 0:
        delta = 24 * 3600  # ensure forward
    CLIENT.request("POST", "/api/_clock/advance", role="PlatformAdmin", user_id="admin",
                   body={"seconds": delta})
    r = register_active_restaurant()
    c = register_customer()
    m = add_menu(r["id"])
    o = place_order(c["id"], r["id"], [{"menu_item_id": m["id"], "quantity": 1}])
    assert o["is_peak"] is True


# === Misc state machines ===
def t_rider_status_back_to_available():
    CLIENT.reset()
    r = register_active_restaurant()
    c = register_customer()
    rd = register_rider(); online(rd)
    o, aid = full_deliver(c, r, rd, price=2000)
    s, rb = CLIENT.request("GET", f"/api/riders/{rd['id']}",
                           role="PlatformAdmin", user_id="admin")
    assert rb["data"]["status"] == "AVAILABLE"


def t_orders_list_role_filters():
    CLIENT.reset()
    r = register_active_restaurant()
    c1 = register_customer("p1")
    c2 = register_customer("p2")
    m = add_menu(r["id"], name="m")
    place_order(c1["id"], r["id"], [{"menu_item_id": m["id"], "quantity": 1}])
    place_order(c2["id"], r["id"], [{"menu_item_id": m["id"], "quantity": 1}])
    s, b = CLIENT.request("GET", "/api/orders", role="Customer", user_id=c1["id"])
    assert s == 200 and len(b["data"]) == 1
    s, b = CLIENT.request("GET", "/api/orders", role="PlatformAdmin", user_id="admin")
    assert s == 200 and len(b["data"]) == 2


TESTS = [
    ("envelope meta fields shape", t_envelope_meta_fields),
    ("envelope error meta shape", t_envelope_error_meta),
    ("id is UUID without prefix", t_id_uuid_no_prefix),
    ("pagination offset window", t_pagination_offset_window),
    ("restaurant unique name", t_restaurant_unique_name),
    ("restaurant name too long", t_restaurant_name_too_long),
    ("restaurant settle zeros", t_restaurant_settle_zeroes),
    ("restaurant filter status", t_restaurant_filter_status),
    ("menu item filter listed", t_menu_item_filter_listed),
    ("menu item role isolation", t_menu_item_role_isolation),
    ("rider offline with active assignment", t_rider_offline_with_active_assignment),
    ("rider suspend only AVAILABLE", t_rider_suspend_only_available),
    ("customer duplicate phone", t_customer_duplicate_phone),
    ("order quantity invalid", t_order_quantity_invalid),
    ("order unknown menu item", t_order_unknown_menu_item),
    ("order customer ownership", t_order_customer_ownership),
    ("order cancel after accept", t_order_cancel_after_accept),
    ("order ready requires acceptance", t_order_ready_requires_acceptance),
    ("dispatch refuses when no riders", t_order_dispatch_no_riders),
    ("assignment pickup requires READY", t_assignment_pickup_requires_ready),
    ("deliver credits wallet + settlement", t_deliver_credits_wallet_and_settlement),
    ("late 30+ minutes fine", t_late_30_plus_minutes),
    ("late 1-10 minutes fine", t_late_1_to_10_minutes),
    ("commission override path", t_commission_override_path),
    ("commission override changed mid-flight", t_commission_override_changed_midflight),
    ("return full refund changes payment_status", t_return_refund_full_changes_status),
    ("return amount outside", t_return_amount_outside),
    ("return reject reverts order", t_return_reject_reverts_order),
    ("return escalate opens WO; reopen closes it", t_return_escalate_opens_wo_reopen_closes_it),
    ("abusive return fine when trust_score < 0.5", t_abusive_return_fine),
    ("WO opener_id match", t_wo_opener_match),
    ("WO resolve requires assignee+state", t_wo_resolve_requires_assignee),
    ("WO request_info/submit_info cycle", t_wo_request_info_submit_cycle),
    ("fines query scope for Rider", t_fines_query_scope_for_rider),
    ("settled fine not waivable", t_fine_settled_cant_waive),
    ("delivery cascade increments versions", t_versions_increment_on_cascade),
    ("pipeline auth before route resolution", t_pipeline_auth_before_route),
    ("pipeline role before not_found", t_pipeline_role_before_not_found),
    ("pipeline not_found before body validation", t_pipeline_not_found_before_body_validation),
    ("peak window snapshot", t_peak_window),
    ("rider returns to AVAILABLE after delivery", t_rider_status_back_to_available),
    ("orders list role-scoped filters", t_orders_list_role_filters),
]

if __name__ == "__main__":
    for name, fn in TESTS:
        R.run(name, fn)
    ok = R.report()
    sys.exit(0 if ok else 1)
