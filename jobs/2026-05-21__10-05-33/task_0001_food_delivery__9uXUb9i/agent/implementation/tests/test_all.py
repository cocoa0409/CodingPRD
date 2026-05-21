"""Granular self-tests covering each PRD rule.

Run with `python3 tests/test_all.py` from inside the implementation directory.
Each test prints a single PASS/FAIL line so individual outcomes are visible.
"""
from __future__ import annotations

import os
import sys
import json
import math
import traceback
from datetime import datetime, timezone

# Make sibling modules importable when run as a script.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import store
from app import create_app


_failures: list[tuple[str, str]] = []
_passed = 0


def _print(name: str, ok: bool, detail: str = "") -> None:
    global _passed
    if ok:
        _passed += 1
        print(f"PASS  {name}")
    else:
        _failures.append((name, detail))
        print(f"FAIL  {name}  -- {detail}")


def hdrs(role: str, uid: str = "admin-1") -> dict:
    return {"X-User-ID": uid, "X-User-Role": role}


def env_call(client, method, path, role=None, uid=None, json_body=None):
    headers = {}
    if role is not None:
        headers["X-User-ID"] = uid or "admin-1"
        headers["X-User-Role"] = role
    headers["Content-Type"] = "application/json"
    fn = getattr(client, method.lower())
    resp = fn(path, headers=headers, data=json.dumps(json_body) if json_body is not None else None)
    body = resp.get_json()
    return resp.status_code, body


def expect_ok(name, code, body, *, status=None):
    if status is not None and code != status:
        _print(name, False, f"expected status {status}, got {code} body={body}")
        return False
    if not (200 <= code < 300):
        _print(name, False, f"expected 2xx, got {code} body={body}")
        return False
    if body is None or body.get("response_type") == "error":
        _print(name, False, f"unexpected error body: {body}")
        return False
    return True


def expect_err(name, code, body, expected_id, expected_status=None):
    if body is None or body.get("response_type") != "error":
        _print(name, False, f"expected error envelope, got code={code} body={body}")
        return False
    got = body.get("data", {}).get("error_id")
    if got != expected_id:
        _print(name, False, f"expected error_id={expected_id}, got {got} (code={code})")
        return False
    if expected_status is not None and code != expected_status:
        _print(name, False, f"expected status {expected_status}, got {code}")
        return False
    return True


# ---- Test bodies -----------------------------------------------------------


def t_envelope_basic(client):
    code, body = env_call(client, "GET", "/api/restaurants", role="PlatformAdmin")
    if not expect_ok("envelope basic OK", code, body, status=200):
        return
    meta = body.get("meta", {})
    if not isinstance(meta.get("api_request_id"), str) or not meta["api_request_id"].startswith("req_"):
        _print("envelope api_request_id format", False, str(meta))
        return
    ts = meta.get("api_request_timestamp", "")
    if not (isinstance(ts, str) and ts.endswith("Z") and "." in ts):
        _print("envelope timestamp format", False, ts)
        return
    if body.get("response_type") != "array":
        _print("envelope response_type=array on list", False, body.get("response_type"))
        return
    _print("envelope success format", True)


def t_auth_required(client):
    code, body = env_call(client, "GET", "/api/restaurants")
    expect_err("auth required (no headers)", code, body, "ERR_AUTH_REQUIRED", 401) and _print(
        "auth required missing headers", True
    )

    code, body = env_call(client, "GET", "/api/restaurants", role="Bogus")
    expect_err("invalid role", code, body, "ERR_AUTH_REQUIRED", 401) and _print(
        "auth required invalid role", True
    )


def t_forbidden_role(client):
    code, body = env_call(client, "POST", "/api/restaurants", role="Customer", json_body={"name": "x"})
    if expect_err("forbidden role POST restaurants", code, body, "ERR_FORBIDDEN", 403):
        _print("RBAC: Customer cannot register restaurants", True)


def t_restaurant_lifecycle(client):
    store.reset_all()
    # Register
    code, body = env_call(
        client, "POST", "/api/restaurants",
        role="PlatformAdmin",
        json_body={"name": "Resto", "address": "1 St", "lat": 0.0, "lng": 0.0},
    )
    if not expect_ok("restaurant register 201", code, body, status=201):
        return
    rid = body["data"]["id"]
    if body["data"]["status"] != "PENDING_APPROVAL":
        _print("restaurant initial status", False, body["data"]["status"]); return
    _print("restaurant initial status PENDING_APPROVAL", True)
    if body["data"]["version"] != 1:
        _print("restaurant initial version", False, str(body["data"]["version"])); return
    _print("restaurant initial version=1", True)

    # Approve
    code, body = env_call(client, "POST", f"/api/restaurants/{rid}/approve", role="PlatformAdmin")
    if not expect_ok("restaurant approve", code, body, status=200): return
    if body["data"]["status"] != "ACTIVE":
        _print("restaurant approve -> ACTIVE", False, body["data"]["status"]); return
    if body["data"]["version"] != 2:
        _print("restaurant version bump on approve", False, str(body["data"]["version"])); return
    _print("restaurant approve cascade version+1", True)

    # Suspend (no orders yet)
    code, body = env_call(client, "POST", f"/api/restaurants/{rid}/suspend", role="PlatformAdmin")
    if not expect_ok("restaurant suspend", code, body): return
    if body["data"]["status"] != "SUSPENDED":
        _print("restaurant suspend status", False, body["data"]["status"]); return
    _print("restaurant suspend OK", True)

    # Reinstate
    code, body = env_call(client, "POST", f"/api/restaurants/{rid}/reinstate", role="PlatformAdmin")
    if body["data"]["status"] != "ACTIVE":
        _print("restaurant reinstate", False, body["data"]["status"]); return
    _print("restaurant reinstate -> ACTIVE", True)

    # Settle
    code, body = env_call(client, "POST", f"/api/restaurants/{rid}/settle", role="PlatformAdmin")
    if body["data"]["pending_settlement_cents"] != 0:
        _print("restaurant settle zeroes", False, str(body["data"])); return
    _print("restaurant settle zeroes pending", True)

    # Patch with bad rate
    code, body = env_call(
        client, "PATCH", f"/api/restaurants/{rid}",
        role="PlatformAdmin",
        json_body={"commission_rate_override": 0.04},
    )
    expect_err("patch reject too-low rate", code, body, "ERR_VALIDATION", 422) and _print(
        "commission_rate_override below 0.05 rejected", True
    )

    # Patch with name (immutable)
    code, body = env_call(
        client, "PATCH", f"/api/restaurants/{rid}",
        role="PlatformAdmin",
        json_body={"name": "Other"},
    )
    expect_err("name immutable", code, body, "ERR_VALIDATION", 422) and _print(
        "restaurant name immutable", True
    )


def t_restaurant_name_unique(client):
    store.reset_all()
    env_call(client, "POST", "/api/restaurants", role="PlatformAdmin",
             json_body={"name": "Same", "address": "a", "lat": 0, "lng": 0})
    code, body = env_call(client, "POST", "/api/restaurants", role="PlatformAdmin",
                          json_body={"name": "Same", "address": "b", "lat": 0, "lng": 0})
    expect_err("restaurant name unique", code, body, "ERR_VALIDATION", 422) and _print(
        "restaurant name unique among active restaurants", True
    )


def t_occ_version(client):
    store.reset_all()
    code, body = env_call(client, "POST", "/api/restaurants", role="PlatformAdmin",
                          json_body={"name": "OCC", "address": "a", "lat": 0, "lng": 0})
    rid = body["data"]["id"]
    env_call(client, "POST", f"/api/restaurants/{rid}/approve", role="PlatformAdmin")
    # Now version is 2.
    code, body = env_call(client, "PATCH", f"/api/restaurants/{rid}", role="PlatformAdmin",
                          json_body={"address": "new", "version": 99})
    expect_err("OCC mismatch", code, body, "ERR_VERSION_CONFLICT", 409) and _print(
        "OCC conflict on mismatched version", True
    )
    # OCC matches
    code, body = env_call(client, "PATCH", f"/api/restaurants/{rid}", role="PlatformAdmin",
                          json_body={"address": "new", "version": 2})
    if expect_ok("OCC match", code, body, status=200):
        if body["data"]["version"] == 3:
            _print("OCC match advances version", True)
        else:
            _print("OCC match advances version", False, str(body["data"]["version"]))


def t_menu_items(client):
    store.reset_all()
    _, body = env_call(client, "POST", "/api/restaurants", role="PlatformAdmin",
                       json_body={"name": "M", "address": "a", "lat": 0, "lng": 0})
    rid = body["data"]["id"]
    env_call(client, "POST", f"/api/restaurants/{rid}/approve", role="PlatformAdmin")
    # Restaurant identity for menu-item create
    code, body = env_call(client, "POST", f"/api/restaurants/{rid}/menu-items",
                          role="Restaurant", uid="not-this-restaurant",
                          json_body={"name": "Pizza", "price_cents": 1000})
    expect_err("menu item restaurant identity", code, body, "ERR_FORBIDDEN", 403) and _print(
        "menu item create requires identity match", True
    )

    code, body = env_call(client, "POST", f"/api/restaurants/{rid}/menu-items",
                          role="Restaurant", uid=rid,
                          json_body={"name": "Pizza", "price_cents": 0})
    expect_err("menu item price low", code, body, "ERR_VALIDATION", 422) and _print(
        "menu item price < 1 rejected", True
    )

    code, body = env_call(client, "POST", f"/api/restaurants/{rid}/menu-items",
                          role="Restaurant", uid=rid,
                          json_body={"name": "Pizza", "price_cents": 1500})
    if not expect_ok("menu item create", code, body, status=201): return
    mid = body["data"]["id"]

    # Patch is_listed
    code, body = env_call(client, "PATCH", f"/api/menu-items/{mid}",
                          role="Restaurant", uid=rid,
                          json_body={"is_listed": False})
    if expect_ok("menu item patch", code, body, status=200):
        if body["data"]["is_listed"] is False:
            _print("menu item patch is_listed", True)
        else:
            _print("menu item patch is_listed", False, str(body))


def t_customer_register(client):
    store.reset_all()
    code, body = env_call(client, "POST", "/api/customers", role="PlatformAdmin",
                          json_body={"name": "C", "phone": "111", "address": "a", "lat": 0, "lng": 0})
    if not expect_ok("customer register", code, body, status=201): return
    cid = body["data"]["id"]
    if body["data"]["credit_balance_cents"] != 0 or body["data"]["trust_score"] != 1.0:
        _print("customer defaults", False, str(body["data"])); return
    _print("customer initial credit=0 trust=1.0", True)
    # Identity check
    code, body = env_call(client, "GET", f"/api/customers/{cid}", role="Customer", uid="other")
    expect_err("customer identity", code, body, "ERR_FORBIDDEN", 403) and _print(
        "customer cannot read another customer", True
    )
    # Duplicate phone
    code, body = env_call(client, "POST", "/api/customers", role="PlatformAdmin",
                          json_body={"name": "D", "phone": "111", "address": "a", "lat": 0, "lng": 0})
    expect_err("customer phone unique", code, body, "ERR_VALIDATION", 422) and _print(
        "customer phone uniqueness", True
    )


def t_rider_lifecycle(client):
    store.reset_all()
    _, body = env_call(client, "POST", "/api/riders", role="PlatformAdmin",
                       json_body={"name": "R", "phone": "222"})
    rid = body["data"]["id"]
    if body["data"]["status"] != "OFFLINE" or body["data"]["bonus_tier"] != "BRONZE":
        _print("rider initial state", False, str(body["data"])); return
    _print("rider initial OFFLINE/BRONZE", True)

    # Go online
    code, body = env_call(client, "POST", f"/api/riders/{rid}/go-online", role="Rider", uid=rid)
    if body["data"]["status"] != "AVAILABLE":
        _print("rider go-online -> AVAILABLE", False, str(body["data"])); return
    _print("rider go-online -> AVAILABLE", True)

    # Suspend criteria not met
    code, body = env_call(client, "POST", f"/api/riders/{rid}/suspend", role="PlatformAdmin")
    expect_err("rider suspend criteria", code, body, "ERR_SUSPEND_CRITERIA_NOT_MET", 422) and _print(
        "rider suspend criteria not met", True
    )

    # Force metrics down then suspend
    rider_rec = store.riders[rid]
    rider_rec["on_time_rate"] = 0.5
    code, body = env_call(client, "POST", f"/api/riders/{rid}/suspend", role="PlatformAdmin")
    if expect_ok("rider suspend", code, body, status=200):
        if body["data"]["status"] == "SUSPENDED":
            _print("rider suspend OK once threshold breached", True)
        else:
            _print("rider suspend OK once threshold breached", False, str(body))


def _setup_order_world(client, distance_km=1.0):
    """Helper: returns (restaurant_id, customer_id, menu_item_id, rider_id)."""
    store.reset_all()
    _, body = env_call(client, "POST", "/api/restaurants", role="PlatformAdmin",
                       json_body={"name": "Rt", "address": "a", "lat": 0.0, "lng": 0.0})
    rid = body["data"]["id"]
    env_call(client, "POST", f"/api/restaurants/{rid}/approve", role="PlatformAdmin")
    # Customer at offset that gives ~distance_km via lng
    # 1 degree lng at equator ~ 111.319 km
    lng_offset = distance_km / 111.319
    _, body = env_call(client, "POST", "/api/customers", role="PlatformAdmin",
                       json_body={"name": "Cu", "phone": "1", "address": "x",
                                  "lat": 0.0, "lng": lng_offset})
    cid = body["data"]["id"]
    _, body = env_call(client, "POST", f"/api/restaurants/{rid}/menu-items",
                       role="Restaurant", uid=rid,
                       json_body={"name": "Pizza", "price_cents": 1000})
    mid = body["data"]["id"]
    _, body = env_call(client, "POST", "/api/riders", role="PlatformAdmin",
                       json_body={"name": "Ri", "phone": "9"})
    riderid = body["data"]["id"]
    env_call(client, "POST", f"/api/riders/{riderid}/go-online", role="Rider", uid=riderid)
    return rid, cid, mid, riderid


def t_order_placement(client):
    rid, cid, mid, riderid = _setup_order_world(client, distance_km=2.0)
    # Bad subtotal: empty items
    code, body = env_call(client, "POST", "/api/orders", role="Customer", uid=cid,
                          json_body={"customer_id": cid, "restaurant_id": rid, "items": []})
    expect_err("empty items", code, body, "ERR_ORDER_INVALID", 422) and _print(
        "order with empty items rejected", True
    )

    # qty 0
    code, body = env_call(client, "POST", "/api/orders", role="Customer", uid=cid,
                          json_body={"customer_id": cid, "restaurant_id": rid,
                                     "items": [{"menu_item_id": mid, "quantity": 0}]})
    expect_err("qty 0", code, body, "ERR_ORDER_INVALID", 422) and _print(
        "order with qty 0 rejected", True
    )

    # Identity mismatch
    code, body = env_call(client, "POST", "/api/orders", role="Customer", uid="other",
                          json_body={"customer_id": cid, "restaurant_id": rid,
                                     "items": [{"menu_item_id": mid, "quantity": 1}]})
    expect_err("customer identity on order", code, body, "ERR_FORBIDDEN", 403) and _print(
        "customer identity mismatch on placement", True
    )

    # Successful placement
    code, body = env_call(client, "POST", "/api/orders", role="Customer", uid=cid,
                          json_body={"customer_id": cid, "restaurant_id": rid,
                                     "items": [{"menu_item_id": mid, "quantity": 2}]})
    if not expect_ok("place order", code, body, status=201): return
    o = body["data"]
    if o["subtotal_cents"] != 2000:
        _print("order subtotal", False, str(o)); return
    _print("subtotal_cents computed correctly (2*1000=2000)", True)
    # provisional commission @ 15% on 2000 = 300
    if o["provisional_commission_cents"] != 300:
        _print("provisional commission tier-1", False, str(o)); return
    _print("provisional_commission_cents tier-1 (300)", True)
    if o["payment_status"] != "AUTHORIZED":
        _print("payment status AUTHORIZED", False, str(o)); return
    _print("payment_status -> AUTHORIZED at placement", True)


def t_provisional_fee_formula(client):
    # distance 2.0 km, peak False -> base 300 + 120*2 + 0 = 540
    rid, cid, mid, riderid = _setup_order_world(client, distance_km=2.0)
    _, body = env_call(client, "POST", "/api/orders", role="Customer", uid=cid,
                       json_body={"customer_id": cid, "restaurant_id": rid,
                                  "items": [{"menu_item_id": mid, "quantity": 1}]})
    o = body["data"]
    expected = 300 + 120 * math.ceil(o["distance_km"]) + (200 if o["is_peak"] else 0)
    if o["provisional_delivery_fee_cents"] == expected:
        _print(f"provisional fee formula correct (distance={o['distance_km']}km peak={o['is_peak']} -> {expected})", True)
    else:
        _print("provisional fee formula", False, f"expected {expected} got {o['provisional_delivery_fee_cents']}")


def t_inactive_restaurant_blocks(client):
    rid, cid, mid, riderid = _setup_order_world(client)
    env_call(client, "POST", f"/api/restaurants/{rid}/suspend", role="PlatformAdmin")
    code, body = env_call(client, "POST", "/api/orders", role="Customer", uid=cid,
                          json_body={"customer_id": cid, "restaurant_id": rid,
                                     "items": [{"menu_item_id": mid, "quantity": 1}]})
    expect_err("inactive restaurant", code, body, "ERR_RESTAURANT_UNAVAILABLE", 422) and _print(
        "inactive restaurant blocks placement", True
    )


def t_full_happy_path(client):
    """Place -> accept -> start-preparing -> rider accept -> ready -> pickup -> deliver,
    verifying every cascade."""
    rid, cid, mid, riderid = _setup_order_world(client, distance_km=2.0)
    # Set commission override to None (tiered).
    _, body = env_call(client, "POST", "/api/orders", role="Customer", uid=cid,
                       json_body={"customer_id": cid, "restaurant_id": rid,
                                  "items": [{"menu_item_id": mid, "quantity": 3}]})
    oid = body["data"]["id"]
    # Accept
    env_call(client, "POST", f"/api/orders/{oid}/accept", role="Restaurant", uid=rid)
    # Start preparing -> opens dispatch
    code, body = env_call(client, "POST", f"/api/orders/{oid}/start-preparing", role="Restaurant", uid=rid)
    if not expect_ok("start-preparing", code, body): return
    # There should be exactly one OFFERED assignment
    offers = [a for a in store.assignments.values() if a["order_id"] == oid and a["status"] == "OFFERED"]
    if len(offers) != 1:
        _print("dispatch creates one OFFERED", False, str(offers)); return
    _print("start-preparing opens dispatch (OFFERED)", True)
    aid = offers[0]["id"]
    # Rider accepts
    code, body = env_call(client, "POST", f"/api/assignments/{aid}/accept", role="Rider", uid=riderid)
    if not expect_ok("rider accept", code, body): return
    if store.riders[riderid]["status"] != "ON_DELIVERY":
        _print("rider ON_DELIVERY post-accept", False, store.riders[riderid]["status"]); return
    _print("rider becomes ON_DELIVERY on accept", True)
    # Ready
    code, body = env_call(client, "POST", f"/api/orders/{oid}/ready", role="Restaurant", uid=rid)
    if body["data"]["status"] != "READY_FOR_PICKUP":
        _print("ready cascade", False, str(body["data"])); return
    _print("order ready cascade", True)
    # Pickup
    code, body = env_call(client, "POST", f"/api/assignments/{aid}/pickup", role="Rider", uid=riderid)
    if body["data"]["status"] != "PICKED_UP":
        _print("pickup assignment", False, str(body["data"])); return
    if store.orders[oid]["status"] != "PICKED_UP":
        _print("pickup cascade order", False, store.orders[oid]["status"]); return
    _print("pickup cascades to order", True)
    # Deliver
    code, body = env_call(client, "POST", f"/api/assignments/{aid}/deliver", role="Rider", uid=riderid)
    if not expect_ok("deliver", code, body): return
    o = store.orders[oid]
    if o["status"] != "DELIVERED" or o["payment_status"] != "CAPTURED":
        _print("deliver order state", False, str(o)); return
    _print("deliver: order DELIVERED + payment_status CAPTURED", True)
    # final_commission tiered (3000 subtotal): 3000 * 0.15 = 450
    if o["final_commission_cents"] != 450:
        _print("final_commission tiered", False, str(o)); return
    _print("final_commission tiered correct (450)", True)
    if o["final_delivery_fee_cents"] != o["provisional_delivery_fee_cents"]:
        # solo, no merge; should match provisional
        _print("solo final fee equals provisional", False, str(o)); return
    _print("solo final delivery fee == provisional", True)
    # Restaurant pending_settlement_cents = subtotal - final_commission
    rest = store.restaurants[rid]
    expected_settle = 3000 - 450
    if rest["pending_settlement_cents"] != expected_settle:
        _print("restaurant pending_settlement", False, str(rest)); return
    _print(f"restaurant pending_settlement_cents += {expected_settle}", True)
    # Rider wallet credited with final fee
    rider = store.riders[riderid]
    if rider["wallet_balance_cents"] != o["final_delivery_fee_cents"]:
        _print("rider wallet credit", False, str(rider)); return
    _print("rider wallet credited with final fee", True)
    # Rider returns to AVAILABLE
    if rider["status"] != "AVAILABLE":
        _print("rider returns AVAILABLE post-delivery", False, rider["status"]); return
    _print("rider returns to AVAILABLE", True)


def t_commission_tiered_boundaries(client):
    from pricing import compute_tiered_commission
    cases = {
        20_000: 3000,  # 20000 * 0.15 = 3000
        50_000: 3000 + 30_000 * 0.18,  # 8400
        # 60_000: 3000 + 5400 + 10000*0.22 = 10600
    }
    for sub, expected in cases.items():
        got = compute_tiered_commission(sub)
        if got != int(round(expected)):
            _print(f"tiered commission@{sub}", False, f"expected {int(round(expected))} got {got}")
            return
    _print("tiered commission boundary cases correct", True)


def t_commission_override(client):
    from pricing import compute_final_commission
    if compute_final_commission(10_000, 0.10) != 1000:
        _print("override commission flat", False, "10000 * 0.10 expected 1000"); return
    _print("commission override flat-rate", True)


def t_late_delivery_fine(client):
    rid, cid, mid, riderid = _setup_order_world(client, distance_km=1.0)
    _, body = env_call(client, "POST", "/api/orders", role="Customer", uid=cid,
                       json_body={"customer_id": cid, "restaurant_id": rid,
                                  "items": [{"menu_item_id": mid, "quantity": 1}]})
    oid = body["data"]["id"]
    env_call(client, "POST", f"/api/orders/{oid}/accept", role="Restaurant", uid=rid)
    env_call(client, "POST", f"/api/orders/{oid}/start-preparing", role="Restaurant", uid=rid)
    aid = [a["id"] for a in store.assignments.values() if a["order_id"] == oid][0]
    env_call(client, "POST", f"/api/assignments/{aid}/accept", role="Rider", uid=riderid)
    env_call(client, "POST", f"/api/orders/{oid}/ready", role="Restaurant", uid=rid)
    env_call(client, "POST", f"/api/assignments/{aid}/pickup", role="Rider", uid=riderid)
    # Advance clock 50 minutes (5 min past 45-min promise)
    env_call(client, "POST", "/api/_clock/advance", role="PlatformAdmin", json_body={"seconds": 50 * 60})
    env_call(client, "POST", f"/api/assignments/{aid}/deliver", role="Rider", uid=riderid)
    o = store.orders[oid]
    if o["minutes_late"] != 5:
        _print("minutes_late computed", False, str(o)); return
    _print("minutes_late computed (5min)", True)
    # Fine should be flat 200 for 1..10 minutes
    fines = [f for f in store.fines.values() if f["reason"] == "LATE_DELIVERY"]
    if not fines or fines[0]["amount_cents"] != 200:
        _print("late fine 1-10min=200", False, str(fines)); return
    _print("late fine tier-1 (200 cents for 5min)", True)


def t_late_fine_tier2_tier3(client):
    from pricing import compute_late_fine_amount
    if compute_late_fine_amount(20, 999) != 500 + 50 * 10:
        _print("late fine tier-2 (20min)", False); return
    _print("late fine tier-2 formula (20min=1000)", True)
    # 40 minutes: clawback min(fee, 1500) + 500
    if compute_late_fine_amount(40, 800) != 800 + 500:
        _print("late fine tier-3 (clawback < 1500)", False); return
    _print("late fine tier-3 clawback < 1500", True)
    if compute_late_fine_amount(40, 5000) != 1500 + 500:
        _print("late fine tier-3 clawback cap", False); return
    _print("late fine tier-3 clawback cap at 1500", True)


def t_bonus_tier_boundaries(client):
    from pricing import compute_bonus_tier
    # exact 0.900 -> PLATINUM
    # weights: 0.6*on_time + 0.3*acc + 0.1*(rating/5)
    # Choose values that produce 0.900 score: on_time=1.0, acc=1.0, rating=0 -> 0.6+0.3+0 = 0.9
    if compute_bonus_tier(1.0, 1.0, 0.0) != "PLATINUM":
        _print("bonus tier 0.900 -> PLATINUM", False); return
    _print("bonus tier exact 0.900 -> PLATINUM", True)
    # 0.800: on_time=1.0 acc=1.0 rating=-?  not feasible with rating in 0..5. Use on_time=0.5 acc=1.0 rating=5 -> 0.3+0.3+0.1=0.7. We need 0.8.
    # on_time=0.8333... acc=1.0 rating=0 -> 0.5+0.3=0.8 exactly when on_time=5/6=0.833...
    # Instead use direct constructed values: on_time=0.5, acc=1.0, rating=5 -> 0.3+0.3+0.1=0.7 (SILVER)
    if compute_bonus_tier(0.5, 1.0, 5.0) != "SILVER":
        _print("bonus tier 0.700 -> SILVER", False); return
    _print("bonus tier exact 0.700 -> SILVER", True)
    # < 0.7 -> BRONZE
    if compute_bonus_tier(0.0, 0.0, 0.0) != "BRONZE":
        _print("bonus tier 0 -> BRONZE", False); return
    _print("bonus tier < 0.7 -> BRONZE", True)


def t_peak_window_freezes(client):
    # Manually set up an order during peak window using clock advance.
    rid, cid, mid, riderid = _setup_order_world(client, distance_km=1.0)
    # The clock starts at real-time; we cannot easily make placement land at
    # 11:00 UTC. Use peak via store.is_peak directly. Instead, advance clock
    # to next 11:00 UTC.
    from datetime import datetime, timezone, timedelta
    nowt = store.now()
    secs_to_11 = ((11 - nowt.hour) % 24) * 3600 - nowt.minute * 60 - nowt.second
    if secs_to_11 <= 0:
        secs_to_11 += 24 * 3600
    env_call(client, "POST", "/api/_clock/advance", role="PlatformAdmin",
             json_body={"seconds": secs_to_11 + 60})  # 11:01
    _, body = env_call(client, "POST", "/api/orders", role="Customer", uid=cid,
                       json_body={"customer_id": cid, "restaurant_id": rid,
                                  "items": [{"menu_item_id": mid, "quantity": 1}]})
    o = body["data"]
    if not o["is_peak"]:
        _print("peak window flagged", False, str(o)); return
    _print("is_peak set during 11-13 UTC window", True)
    # The provisional fee includes peak +200
    expected = 300 + 120 * math.ceil(o["distance_km"]) + 200
    if o["provisional_delivery_fee_cents"] != expected:
        _print("peak provisional fee +200", False, str(o)); return
    _print("provisional fee includes peak surcharge", True)


def t_validation_pipeline_order(client):
    """First-failure wins: auth before role before path-FK before body-FK etc."""
    # Missing X-User-ID
    code, body = env_call(client, "POST", "/api/restaurants/abc/approve")
    expect_err("missing auth before NF", code, body, "ERR_AUTH_REQUIRED", 401) and _print(
        "AUTH precedes NOT_FOUND", True
    )
    # Wrong role: returns FORBIDDEN, not NOT_FOUND
    code, body = env_call(client, "POST", "/api/restaurants/abc/approve", role="Customer")
    expect_err("wrong role before NF", code, body, "ERR_FORBIDDEN", 403) and _print(
        "RBAC precedes NOT_FOUND", True
    )
    # Path NOT_FOUND surfaces before body FK NOT_FOUND
    rid, cid, mid, riderid = _setup_order_world(client)
    # path id wrong
    code, body = env_call(client, "POST", "/api/orders/missing/accept", role="Restaurant", uid=rid)
    expect_err("path FK precedes state", code, body, "ERR_NOT_FOUND", 404) and _print(
        "path FK NF precedes state check", True
    )


def t_order_already_assigned(client):
    rid, cid, mid, riderid = _setup_order_world(client)
    _, body = env_call(client, "POST", "/api/orders", role="Customer", uid=cid,
                       json_body={"customer_id": cid, "restaurant_id": rid,
                                  "items": [{"menu_item_id": mid, "quantity": 1}]})
    oid = body["data"]["id"]
    env_call(client, "POST", f"/api/orders/{oid}/accept", role="Restaurant", uid=rid)
    env_call(client, "POST", f"/api/orders/{oid}/start-preparing", role="Restaurant", uid=rid)
    aid1 = [a["id"] for a in store.assignments.values() if a["order_id"] == oid][0]
    # Force-create a second OFFERED assignment for the same order, then have
    # rider accept both.
    _, body = env_call(client, "POST", "/api/riders", role="PlatformAdmin",
                       json_body={"name": "R2", "phone": "p2"})
    rid2 = body["data"]["id"]
    env_call(client, "POST", f"/api/riders/{rid2}/go-online", role="Rider", uid=rid2)
    # Forcibly create a second OFFERED assignment by calling /dispatch.
    code, body = env_call(client, "POST", f"/api/orders/{oid}/dispatch", role="PlatformAdmin")
    if not expect_ok("force redispatch", code, body, status=201): return
    aid2 = body["data"]["id"]
    # Now first rider accepts aid1; then second rider tries aid2.
    env_call(client, "POST", f"/api/assignments/{aid1}/accept", role="Rider", uid=riderid)
    code, body = env_call(client, "POST", f"/api/assignments/{aid2}/accept", role="Rider", uid=rid2)
    expect_err("already assigned", code, body, "ERR_ORDER_ALREADY_ASSIGNED", 409) and _print(
        "ERR_ORDER_ALREADY_ASSIGNED on race", True
    )


def t_no_show_fine(client):
    rid, cid, mid, riderid = _setup_order_world(client)
    _, body = env_call(client, "POST", "/api/orders", role="Customer", uid=cid,
                       json_body={"customer_id": cid, "restaurant_id": rid,
                                  "items": [{"menu_item_id": mid, "quantity": 1}]})
    oid = body["data"]["id"]
    env_call(client, "POST", f"/api/orders/{oid}/accept", role="Restaurant", uid=rid)
    env_call(client, "POST", f"/api/orders/{oid}/start-preparing", role="Restaurant", uid=rid)
    aid = [a["id"] for a in store.assignments.values() if a["order_id"] == oid][0]
    env_call(client, "POST", f"/api/assignments/{aid}/accept", role="Rider", uid=riderid)
    # Rider cancels (no-show)
    code, body = env_call(client, "POST", f"/api/assignments/{aid}/cancel", role="Rider", uid=riderid)
    if not expect_ok("rider cancel", code, body): return
    fines = [f for f in store.fines.values() if f["reason"] == "RIDER_NO_SHOW"]
    if len(fines) != 1 or fines[0]["amount_cents"] != 500:
        _print("no-show fine 500", False, str(fines)); return
    _print("no-show fine 500 created", True)
    if store.riders[riderid]["wallet_balance_cents"] != -500:
        _print("no-show wallet debit", False, str(store.riders[riderid])); return
    _print("no-show wallet debited 500", True)


def t_clock_offer_timeout(client):
    rid, cid, mid, riderid = _setup_order_world(client)
    _, body = env_call(client, "POST", "/api/orders", role="Customer", uid=cid,
                       json_body={"customer_id": cid, "restaurant_id": rid,
                                  "items": [{"menu_item_id": mid, "quantity": 1}]})
    oid = body["data"]["id"]
    env_call(client, "POST", f"/api/orders/{oid}/accept", role="Restaurant", uid=rid)
    env_call(client, "POST", f"/api/orders/{oid}/start-preparing", role="Restaurant", uid=rid)
    aid = [a["id"] for a in store.assignments.values() if a["order_id"] == oid][0]
    env_call(client, "POST", "/api/_clock/advance", role="PlatformAdmin", json_body={"seconds": 65})
    a = store.assignments[aid]
    if a["status"] != "REJECTED":
        _print("clock sweep REJECTED", False, a["status"]); return
    _print("60s sweep moves OFFERED -> REJECTED", True)


def t_return_window(client):
    # Complete an order then attempt a return inside / outside the window.
    rid, cid, mid, riderid = _setup_order_world(client)
    _, body = env_call(client, "POST", "/api/orders", role="Customer", uid=cid,
                       json_body={"customer_id": cid, "restaurant_id": rid,
                                  "items": [{"menu_item_id": mid, "quantity": 1}]})
    oid = body["data"]["id"]
    env_call(client, "POST", f"/api/orders/{oid}/accept", role="Restaurant", uid=rid)
    env_call(client, "POST", f"/api/orders/{oid}/start-preparing", role="Restaurant", uid=rid)
    aid = [a["id"] for a in store.assignments.values() if a["order_id"] == oid][0]
    env_call(client, "POST", f"/api/assignments/{aid}/accept", role="Rider", uid=riderid)
    env_call(client, "POST", f"/api/orders/{oid}/ready", role="Restaurant", uid=rid)
    env_call(client, "POST", f"/api/assignments/{aid}/pickup", role="Rider", uid=riderid)
    env_call(client, "POST", f"/api/assignments/{aid}/deliver", role="Rider", uid=riderid)
    # Inside window
    code, body = env_call(client, "POST", f"/api/orders/{oid}/returns", role="Customer", uid=cid,
                          json_body={"reason": "QUALITY_ISSUE", "requested_refund_cents": 500})
    if not expect_ok("return inside window", code, body, status=201): return
    _print("return open inside 24h window", True)
    rretid = body["data"]["id"]
    # Approve too much
    code, body = env_call(client, "POST", f"/api/returns/{rretid}/approve",
                          role="CustomerService", uid="cs-1",
                          json_body={"approved_refund_cents": 9999})
    expect_err("approved > requested", code, body, "ERR_REFUND_AMOUNT_INVALID", 422) and _print(
        "approve refund > requested rejected", True
    )
    # Approve OK
    code, body = env_call(client, "POST", f"/api/returns/{rretid}/approve",
                          role="CustomerService", uid="cs-1",
                          json_body={"approved_refund_cents": 500})
    if not expect_ok("approve return", code, body): return
    _print("return APPROVED and order REFUNDED", True)
    o = store.orders[oid]
    if o["status"] != "REFUNDED" or o["payment_status"] != "PARTIALLY_REFUNDED":
        _print("order REFUNDED + payment status", False, str(o)); return
    _print("order PARTIALLY_REFUNDED when approved < subtotal", True)
    cust = store.customers[cid]
    if cust["credit_balance_cents"] != 500:
        _print("customer credit credited", False, str(cust)); return
    _print("customer credit_balance += approved refund", True)


def t_duplicate_return(client):
    rid, cid, mid, riderid = _setup_order_world(client)
    _, body = env_call(client, "POST", "/api/orders", role="Customer", uid=cid,
                       json_body={"customer_id": cid, "restaurant_id": rid,
                                  "items": [{"menu_item_id": mid, "quantity": 1}]})
    oid = body["data"]["id"]
    env_call(client, "POST", f"/api/orders/{oid}/accept", role="Restaurant", uid=rid)
    env_call(client, "POST", f"/api/orders/{oid}/start-preparing", role="Restaurant", uid=rid)
    aid = [a["id"] for a in store.assignments.values() if a["order_id"] == oid][0]
    env_call(client, "POST", f"/api/assignments/{aid}/accept", role="Rider", uid=riderid)
    env_call(client, "POST", f"/api/orders/{oid}/ready", role="Restaurant", uid=rid)
    env_call(client, "POST", f"/api/assignments/{aid}/pickup", role="Rider", uid=riderid)
    env_call(client, "POST", f"/api/assignments/{aid}/deliver", role="Rider", uid=riderid)
    env_call(client, "POST", f"/api/orders/{oid}/returns", role="Customer", uid=cid,
             json_body={"reason": "QUALITY_ISSUE", "requested_refund_cents": 100})
    code, body = env_call(client, "POST", f"/api/orders/{oid}/returns", role="Customer", uid=cid,
                          json_body={"reason": "QUALITY_ISSUE", "requested_refund_cents": 100})
    expect_err("duplicate return", code, body, "ERR_DUPLICATE_RETURN", 409) and _print(
        "duplicate return rejected", True
    )


def t_return_window_expired(client):
    rid, cid, mid, riderid = _setup_order_world(client)
    _, body = env_call(client, "POST", "/api/orders", role="Customer", uid=cid,
                       json_body={"customer_id": cid, "restaurant_id": rid,
                                  "items": [{"menu_item_id": mid, "quantity": 1}]})
    oid = body["data"]["id"]
    env_call(client, "POST", f"/api/orders/{oid}/accept", role="Restaurant", uid=rid)
    env_call(client, "POST", f"/api/orders/{oid}/start-preparing", role="Restaurant", uid=rid)
    aid = [a["id"] for a in store.assignments.values() if a["order_id"] == oid][0]
    env_call(client, "POST", f"/api/assignments/{aid}/accept", role="Rider", uid=riderid)
    env_call(client, "POST", f"/api/orders/{oid}/ready", role="Restaurant", uid=rid)
    env_call(client, "POST", f"/api/assignments/{aid}/pickup", role="Rider", uid=riderid)
    env_call(client, "POST", f"/api/assignments/{aid}/deliver", role="Rider", uid=riderid)
    env_call(client, "POST", "/api/_clock/advance", role="PlatformAdmin", json_body={"seconds": 25 * 3600})
    code, body = env_call(client, "POST", f"/api/orders/{oid}/returns", role="Customer", uid=cid,
                          json_body={"reason": "OTHER", "requested_refund_cents": 100})
    expect_err("return expired", code, body, "ERR_RETURN_WINDOW_EXPIRED", 422) and _print(
        "return window expired rejection", True
    )


def t_work_order_resolve_gating(client):
    rid, cid, mid, riderid = _setup_order_world(client)
    _, body = env_call(client, "POST", "/api/orders", role="Customer", uid=cid,
                       json_body={"customer_id": cid, "restaurant_id": rid,
                                  "items": [{"menu_item_id": mid, "quantity": 1}]})
    oid = body["data"]["id"]
    env_call(client, "POST", f"/api/orders/{oid}/accept", role="Restaurant", uid=rid)
    env_call(client, "POST", f"/api/orders/{oid}/start-preparing", role="Restaurant", uid=rid)
    aid = [a["id"] for a in store.assignments.values() if a["order_id"] == oid][0]
    env_call(client, "POST", f"/api/assignments/{aid}/accept", role="Rider", uid=riderid)
    env_call(client, "POST", f"/api/orders/{oid}/ready", role="Restaurant", uid=rid)
    env_call(client, "POST", f"/api/assignments/{aid}/pickup", role="Rider", uid=riderid)
    env_call(client, "POST", f"/api/assignments/{aid}/deliver", role="Rider", uid=riderid)
    _, body = env_call(client, "POST", f"/api/orders/{oid}/returns", role="Customer", uid=cid,
                       json_body={"reason": "QUALITY_ISSUE", "requested_refund_cents": 100})
    rretid = body["data"]["id"]
    # Escalate -> work order auto-created
    env_call(client, "POST", f"/api/returns/{rretid}/escalate", role="CustomerService", uid="cs-1")
    # Find linked WO
    wos = [w for w in store.work_orders.values() if w.get("related_return_id") == rretid]
    if not wos:
        _print("escalation auto-opens work order", False); return
    _print("escalation auto-opens work order", True)
    wid = wos[0]["id"]
    env_call(client, "POST", f"/api/work-orders/{wid}/assign", role="CustomerService", uid="cs-1")
    # Try resolve while return is still ESCALATED
    code, body = env_call(client, "POST", f"/api/work-orders/{wid}/resolve",
                          role="CustomerService", uid="cs-1",
                          json_body={"resolution_notes": "done"})
    expect_err("resolve gated", code, body, "ERR_RELATED_RETURN_UNRESOLVED", 422) and _print(
        "resolve gated by unresolved return", True
    )
    # Reopen return -> work order auto-closes
    env_call(client, "POST", f"/api/returns/{rretid}/reopen", role="CustomerService", uid="cs-1")
    if store.work_orders[wid]["status"] != "CLOSED":
        _print("reopen closes linked WO", False, str(store.work_orders[wid])); return
    _print("return reopen closes linked work order", True)


def t_fine_waive(client):
    rid, cid, mid, riderid = _setup_order_world(client)
    _, body = env_call(client, "POST", "/api/orders", role="Customer", uid=cid,
                       json_body={"customer_id": cid, "restaurant_id": rid,
                                  "items": [{"menu_item_id": mid, "quantity": 1}]})
    oid = body["data"]["id"]
    env_call(client, "POST", f"/api/orders/{oid}/accept", role="Restaurant", uid=rid)
    env_call(client, "POST", f"/api/orders/{oid}/start-preparing", role="Restaurant", uid=rid)
    aid = [a["id"] for a in store.assignments.values() if a["order_id"] == oid][0]
    env_call(client, "POST", f"/api/assignments/{aid}/accept", role="Rider", uid=riderid)
    env_call(client, "POST", f"/api/assignments/{aid}/cancel", role="Rider", uid=riderid)
    fines = [f for f in store.fines.values() if f["reason"] == "RIDER_NO_SHOW"]
    fid = fines[0]["id"]
    code, body = env_call(client, "POST", f"/api/fines/{fid}/waive", role="CustomerService", uid="cs-1")
    if not expect_ok("waive fine", code, body): return
    if body["data"]["settlement_status"] != "WAIVED":
        _print("fine waived status", False, str(body["data"])); return
    _print("fine moves to WAIVED on waive", True)
    if store.riders[riderid]["wallet_balance_cents"] != 0:
        _print("fine waive wallet restore", False, str(store.riders[riderid])); return
    _print("waive restores rider wallet balance", True)
    # Cannot waive again
    code, body = env_call(client, "POST", f"/api/fines/{fid}/waive", role="CustomerService", uid="cs-1")
    expect_err("waive again", code, body, "ERR_INVALID_STATE", 409) and _print(
        "double-waive rejected", True
    )


def t_suspended_cancels_placed_orders(client):
    rid, cid, mid, riderid = _setup_order_world(client)
    _, body = env_call(client, "POST", "/api/orders", role="Customer", uid=cid,
                       json_body={"customer_id": cid, "restaurant_id": rid,
                                  "items": [{"menu_item_id": mid, "quantity": 1}]})
    oid = body["data"]["id"]
    env_call(client, "POST", f"/api/restaurants/{rid}/suspend", role="PlatformAdmin")
    o = store.orders[oid]
    if o["status"] != "CANCELLED" or o["payment_status"] != "VOIDED":
        _print("suspend cancels placed orders", False, str(o)); return
    _print("suspending restaurant cancels its PLACED orders -> VOIDED", True)


def t_pagination(client):
    store.reset_all()
    for i in range(15):
        env_call(client, "POST", "/api/restaurants", role="PlatformAdmin",
                 json_body={"name": f"R{i}", "address": "a", "lat": 0, "lng": 0})
    code, body = env_call(client, "GET", "/api/restaurants?limit=5&offset=0", role="PlatformAdmin")
    if not expect_ok("paginate", code, body): return
    if body["meta"]["total_count"] != 15 or body["meta"]["has_more"] is not True:
        _print("paginate meta", False, str(body["meta"])); return
    if len(body["data"]) != 5:
        _print("paginate limit", False, str(len(body["data"]))); return
    _print("pagination total_count/has_more/limit", True)


def t_route_merge(client):
    """Two orders from same restaurant; rider on first should merge second."""
    store.reset_all()
    _, body = env_call(client, "POST", "/api/restaurants", role="PlatformAdmin",
                       json_body={"name": "R", "address": "a", "lat": 0.0, "lng": 0.0})
    rest_id = body["data"]["id"]
    env_call(client, "POST", f"/api/restaurants/{rest_id}/approve", role="PlatformAdmin")
    _, body = env_call(client, "POST", f"/api/restaurants/{rest_id}/menu-items",
                       role="Restaurant", uid=rest_id,
                       json_body={"name": "Pizza", "price_cents": 1000})
    mid = body["data"]["id"]
    _, body = env_call(client, "POST", "/api/customers", role="PlatformAdmin",
                       json_body={"name": "C1", "phone": "1", "address": "x",
                                  "lat": 0.01, "lng": 0.01})
    cid1 = body["data"]["id"]
    _, body = env_call(client, "POST", "/api/customers", role="PlatformAdmin",
                       json_body={"name": "C2", "phone": "2", "address": "x",
                                  "lat": 0.02, "lng": 0.02})
    cid2 = body["data"]["id"]
    _, body = env_call(client, "POST", "/api/riders", role="PlatformAdmin",
                       json_body={"name": "R1", "phone": "9"})
    riderid = body["data"]["id"]
    env_call(client, "POST", f"/api/riders/{riderid}/go-online", role="Rider", uid=riderid)

    # First order
    _, body = env_call(client, "POST", "/api/orders", role="Customer", uid=cid1,
                       json_body={"customer_id": cid1, "restaurant_id": rest_id,
                                  "items": [{"menu_item_id": mid, "quantity": 1}]})
    o1 = body["data"]["id"]
    env_call(client, "POST", f"/api/orders/{o1}/accept", role="Restaurant", uid=rest_id)
    env_call(client, "POST", f"/api/orders/{o1}/start-preparing", role="Restaurant", uid=rest_id)
    a1 = [a["id"] for a in store.assignments.values() if a["order_id"] == o1][0]
    # Need a route group for merge. Create one manually on accept since we don't
    # auto-create groups for solo orders.
    env_call(client, "POST", f"/api/assignments/{a1}/accept", role="Rider", uid=riderid)
    # Manually create a route group for rider for testability
    from store import gen_id, iso_z, now
    gid = gen_id()
    store.route_groups[gid] = {
        "id": gid,
        "rider_id": riderid,
        "assignment_ids": [a1],
        "merged_at": iso_z(now()),
        "status": "ACTIVE",
        "created_at": iso_z(now()),
    }
    store.assignments[a1]["route_group_id"] = gid

    # Second order from same restaurant
    _, body = env_call(client, "POST", "/api/orders", role="Customer", uid=cid2,
                       json_body={"customer_id": cid2, "restaurant_id": rest_id,
                                  "items": [{"menu_item_id": mid, "quantity": 1}]})
    o2 = body["data"]["id"]
    env_call(client, "POST", f"/api/orders/{o2}/accept", role="Restaurant", uid=rest_id)
    env_call(client, "POST", f"/api/orders/{o2}/start-preparing", role="Restaurant", uid=rest_id)
    a2 = [a["id"] for a in store.assignments.values() if a["order_id"] == o2][0]
    env_call(client, "POST", f"/api/assignments/{a2}/accept", role="Rider", uid=riderid)
    if store.assignments[a2].get("route_group_id") != gid:
        _print("route merge attaches to group", False, str(store.assignments[a2])); return
    if a2 not in store.route_groups[gid]["assignment_ids"]:
        _print("route merge appends id to group", False, str(store.route_groups[gid])); return
    _print("route merge attaches second leg to ACTIVE group", True)


def t_merge_discount(client):
    """Direct test of fee formula with merge."""
    from pricing import solo_delivery_fee_cents, final_delivery_fee_cents
    solo = solo_delivery_fee_cents(2.0, False)  # 300 + 240 + 0 = 540
    if solo != 540:
        _print("solo fee compute", False, str(solo)); return
    merged = final_delivery_fee_cents(2.0, False, merged=True)
    # discount = floor(540 * 0.25) = 135; final = 540 - 135 = 405
    if merged != 540 - 135:
        _print("merge discount floor", False, f"got {merged}"); return
    _print("merge discount = solo - floor(solo*0.25)", True)


def t_abusive_return_fine(client):
    rid, cid, mid, riderid = _setup_order_world(client)
    # Lower trust_score to 0.4
    store.customers[cid]["trust_score"] = 0.4
    _, body = env_call(client, "POST", "/api/orders", role="Customer", uid=cid,
                       json_body={"customer_id": cid, "restaurant_id": rid,
                                  "items": [{"menu_item_id": mid, "quantity": 1}]})
    oid = body["data"]["id"]
    env_call(client, "POST", f"/api/orders/{oid}/accept", role="Restaurant", uid=rid)
    env_call(client, "POST", f"/api/orders/{oid}/start-preparing", role="Restaurant", uid=rid)
    aid = [a["id"] for a in store.assignments.values() if a["order_id"] == oid][0]
    env_call(client, "POST", f"/api/assignments/{aid}/accept", role="Rider", uid=riderid)
    env_call(client, "POST", f"/api/orders/{oid}/ready", role="Restaurant", uid=rid)
    env_call(client, "POST", f"/api/assignments/{aid}/pickup", role="Rider", uid=riderid)
    env_call(client, "POST", f"/api/assignments/{aid}/deliver", role="Rider", uid=riderid)
    _, body = env_call(client, "POST", f"/api/orders/{oid}/returns", role="Customer", uid=cid,
                       json_body={"reason": "QUALITY_ISSUE", "requested_refund_cents": 200})
    rretid = body["data"]["id"]
    env_call(client, "POST", f"/api/returns/{rretid}/approve", role="CustomerService", uid="cs-1",
             json_body={"approved_refund_cents": 200})
    fines = [f for f in store.fines.values() if f["reason"] == "ABUSIVE_RETURN"]
    if not fines or fines[0]["amount_cents"] != 200:
        _print("abusive return fine", False, str(fines)); return
    _print("ABUSIVE_RETURN fine on trust<0.5 + QUALITY_ISSUE", True)


def t_haversine_distance(client):
    from common import haversine_km
    d = haversine_km(0, 0, 0, 1.0)
    # ~111.319 km at equator
    if not (110 < d < 112):
        _print("haversine sanity", False, str(d)); return
    _print("haversine equator ~111km", True)


def t_dispatch_no_riders(client):
    """When no riders are AVAILABLE, /dispatch returns ERR_INVALID_STATE."""
    store.reset_all()
    _, body = env_call(client, "POST", "/api/restaurants", role="PlatformAdmin",
                       json_body={"name": "R", "address": "a", "lat": 0, "lng": 0})
    rest_id = body["data"]["id"]
    env_call(client, "POST", f"/api/restaurants/{rest_id}/approve", role="PlatformAdmin")
    _, body = env_call(client, "POST", f"/api/restaurants/{rest_id}/menu-items",
                       role="Restaurant", uid=rest_id,
                       json_body={"name": "P", "price_cents": 1000})
    mid = body["data"]["id"]
    _, body = env_call(client, "POST", "/api/customers", role="PlatformAdmin",
                       json_body={"name": "C", "phone": "1", "address": "a", "lat": 0, "lng": 0})
    cid = body["data"]["id"]
    _, body = env_call(client, "POST", "/api/orders", role="Customer", uid=cid,
                       json_body={"customer_id": cid, "restaurant_id": rest_id,
                                  "items": [{"menu_item_id": mid, "quantity": 1}]})
    oid = body["data"]["id"]
    env_call(client, "POST", f"/api/orders/{oid}/accept", role="Restaurant", uid=rest_id)
    code, body = env_call(client, "POST", f"/api/orders/{oid}/dispatch", role="PlatformAdmin")
    expect_err("dispatch no riders", code, body, "ERR_INVALID_STATE", 409) and _print(
        "explicit /dispatch with empty pool -> ERR_INVALID_STATE", True
    )


def t_ready_requires_accepted_dispatch(client):
    rid, cid, mid, riderid = _setup_order_world(client)
    _, body = env_call(client, "POST", "/api/orders", role="Customer", uid=cid,
                       json_body={"customer_id": cid, "restaurant_id": rid,
                                  "items": [{"menu_item_id": mid, "quantity": 1}]})
    oid = body["data"]["id"]
    env_call(client, "POST", f"/api/orders/{oid}/accept", role="Restaurant", uid=rid)
    env_call(client, "POST", f"/api/orders/{oid}/start-preparing", role="Restaurant", uid=rid)
    # No rider has accepted yet
    code, body = env_call(client, "POST", f"/api/orders/{oid}/ready", role="Restaurant", uid=rid)
    expect_err("ready before accepted", code, body, "ERR_INVALID_STATE", 409) and _print(
        "ready refused until rider ACCEPTED", True
    )


def t_go_offline_blocked_by_live_assignment(client):
    rid, cid, mid, riderid = _setup_order_world(client)
    _, body = env_call(client, "POST", "/api/orders", role="Customer", uid=cid,
                       json_body={"customer_id": cid, "restaurant_id": rid,
                                  "items": [{"menu_item_id": mid, "quantity": 1}]})
    oid = body["data"]["id"]
    env_call(client, "POST", f"/api/orders/{oid}/accept", role="Restaurant", uid=rid)
    env_call(client, "POST", f"/api/orders/{oid}/start-preparing", role="Restaurant", uid=rid)
    # offered to rider, but they cannot go offline
    code, body = env_call(client, "POST", f"/api/riders/{riderid}/go-offline", role="Rider", uid=riderid)
    expect_err("go-offline blocked", code, body, "ERR_INVALID_STATE", 409) and _print(
        "go-offline blocked while OFFERED assignment exists", True
    )


def t_cancel_after_placed_disallowed(client):
    rid, cid, mid, riderid = _setup_order_world(client)
    _, body = env_call(client, "POST", "/api/orders", role="Customer", uid=cid,
                       json_body={"customer_id": cid, "restaurant_id": rid,
                                  "items": [{"menu_item_id": mid, "quantity": 1}]})
    oid = body["data"]["id"]
    env_call(client, "POST", f"/api/orders/{oid}/accept", role="Restaurant", uid=rid)
    code, body = env_call(client, "POST", f"/api/orders/{oid}/cancel", role="Customer", uid=cid)
    expect_err("cancel after PLACED", code, body, "ERR_INVALID_STATE", 409) and _print(
        "cancel disallowed beyond PLACED", True
    )


def t_id_format_no_prefix(client):
    store.reset_all()
    _, body = env_call(client, "POST", "/api/restaurants", role="PlatformAdmin",
                       json_body={"name": "X", "address": "a", "lat": 0, "lng": 0})
    rid = body["data"]["id"]
    # UUID format without prefix
    import re
    if not re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", rid):
        _print("resource id is bare UUID", False, rid); return
    _print("resource id emitted as bare UUID without prefix", True)


def t_order_invalid_subtotal_below_100(client):
    rid, cid, mid, riderid = _setup_order_world(client)
    # Make a 50-cent menu item
    _, body = env_call(client, "POST", f"/api/restaurants/{rid}/menu-items",
                       role="Restaurant", uid=rid,
                       json_body={"name": "Tiny", "price_cents": 50})
    tiny_mid = body["data"]["id"]
    code, body = env_call(client, "POST", "/api/orders", role="Customer", uid=cid,
                          json_body={"customer_id": cid, "restaurant_id": rid,
                                     "items": [{"menu_item_id": tiny_mid, "quantity": 1}]})
    expect_err("subtotal too low", code, body, "ERR_ORDER_INVALID", 422) and _print(
        "subtotal < 100 cents rejected", True
    )


def t_order_bad_menu_item(client):
    rid, cid, mid, riderid = _setup_order_world(client)
    code, body = env_call(client, "POST", "/api/orders", role="Customer", uid=cid,
                          json_body={"customer_id": cid, "restaurant_id": rid,
                                     "items": [{"menu_item_id": "bogus", "quantity": 1}]})
    expect_err("bad menu item id", code, body, "ERR_NOT_FOUND", 404) and _print(
        "bad menu_item_id -> ERR_NOT_FOUND", True
    )


def t_order_unlisted_menu_item(client):
    rid, cid, mid, riderid = _setup_order_world(client)
    env_call(client, "PATCH", f"/api/menu-items/{mid}", role="Restaurant", uid=rid,
             json_body={"is_listed": False})
    code, body = env_call(client, "POST", "/api/orders", role="Customer", uid=cid,
                          json_body={"customer_id": cid, "restaurant_id": rid,
                                     "items": [{"menu_item_id": mid, "quantity": 1}]})
    expect_err("unlisted item", code, body, "ERR_RESTAURANT_UNAVAILABLE", 422) and _print(
        "unlisted menu item -> ERR_RESTAURANT_UNAVAILABLE", True
    )


def t_validation_missing_field(client):
    store.reset_all()
    code, body = env_call(client, "POST", "/api/restaurants", role="PlatformAdmin",
                          json_body={"name": "x"})
    expect_err("missing field", code, body, "ERR_VALIDATION", 422) and _print(
        "missing required field -> ERR_VALIDATION", True
    )


def t_validation_pipeline_path_before_body_fk(client):
    """Path id NF before body FK NF."""
    rid, cid, mid, riderid = _setup_order_world(client)
    # Path id wrong, body FK valid -> NF on path id
    code, body = env_call(client, "POST", "/api/orders/missing-order/cancel",
                          role="Customer", uid=cid)
    expect_err("path NF wins", code, body, "ERR_NOT_FOUND", 404) and _print(
        "path-FK NF precedes body-FK NF", True
    )


def t_restaurant_patch_identity(client):
    store.reset_all()
    _, body = env_call(client, "POST", "/api/restaurants", role="PlatformAdmin",
                       json_body={"name": "R", "address": "a", "lat": 0, "lng": 0})
    rid = body["data"]["id"]
    # Different restaurant identity
    code, body = env_call(client, "PATCH", f"/api/restaurants/{rid}",
                          role="Restaurant", uid="other",
                          json_body={"address": "b"})
    expect_err("restaurant patch identity", code, body, "ERR_FORBIDDEN", 403) and _print(
        "restaurant cannot patch another restaurant", True
    )


def t_settle_decrement_on_approve(client):
    """Restaurant pending_settlement_cents is decremented by approved_refund_cents on return approval."""
    rid, cid, mid, riderid = _setup_order_world(client)
    _, body = env_call(client, "POST", "/api/orders", role="Customer", uid=cid,
                       json_body={"customer_id": cid, "restaurant_id": rid,
                                  "items": [{"menu_item_id": mid, "quantity": 5}]})  # 5000 subtotal
    oid = body["data"]["id"]
    env_call(client, "POST", f"/api/orders/{oid}/accept", role="Restaurant", uid=rid)
    env_call(client, "POST", f"/api/orders/{oid}/start-preparing", role="Restaurant", uid=rid)
    aid = [a["id"] for a in store.assignments.values() if a["order_id"] == oid][0]
    env_call(client, "POST", f"/api/assignments/{aid}/accept", role="Rider", uid=riderid)
    env_call(client, "POST", f"/api/orders/{oid}/ready", role="Restaurant", uid=rid)
    env_call(client, "POST", f"/api/assignments/{aid}/pickup", role="Rider", uid=riderid)
    env_call(client, "POST", f"/api/assignments/{aid}/deliver", role="Rider", uid=riderid)
    rest_before = store.restaurants[rid]["pending_settlement_cents"]
    # Return 500
    _, body = env_call(client, "POST", f"/api/orders/{oid}/returns", role="Customer", uid=cid,
                       json_body={"reason": "WRONG_ITEM", "requested_refund_cents": 500})
    rretid = body["data"]["id"]
    env_call(client, "POST", f"/api/returns/{rretid}/approve", role="CustomerService", uid="cs-1",
             json_body={"approved_refund_cents": 500})
    if store.restaurants[rid]["pending_settlement_cents"] != rest_before - 500:
        _print("settle decremented on approve", False,
               f"before={rest_before} after={store.restaurants[rid]['pending_settlement_cents']}"); return
    _print("approve decrements restaurant pending_settlement", True)


def t_full_refund_status(client):
    rid, cid, mid, riderid = _setup_order_world(client)
    _, body = env_call(client, "POST", "/api/orders", role="Customer", uid=cid,
                       json_body={"customer_id": cid, "restaurant_id": rid,
                                  "items": [{"menu_item_id": mid, "quantity": 1}]})
    oid = body["data"]["id"]
    env_call(client, "POST", f"/api/orders/{oid}/accept", role="Restaurant", uid=rid)
    env_call(client, "POST", f"/api/orders/{oid}/start-preparing", role="Restaurant", uid=rid)
    aid = [a["id"] for a in store.assignments.values() if a["order_id"] == oid][0]
    env_call(client, "POST", f"/api/assignments/{aid}/accept", role="Rider", uid=riderid)
    env_call(client, "POST", f"/api/orders/{oid}/ready", role="Restaurant", uid=rid)
    env_call(client, "POST", f"/api/assignments/{aid}/pickup", role="Rider", uid=riderid)
    env_call(client, "POST", f"/api/assignments/{aid}/deliver", role="Rider", uid=riderid)
    subtotal = store.orders[oid]["subtotal_cents"]
    _, body = env_call(client, "POST", f"/api/orders/{oid}/returns", role="Customer", uid=cid,
                       json_body={"reason": "LATE", "requested_refund_cents": subtotal})
    rretid = body["data"]["id"]
    env_call(client, "POST", f"/api/returns/{rretid}/approve", role="CustomerService", uid="cs-1",
             json_body={"approved_refund_cents": subtotal})
    if store.orders[oid]["payment_status"] != "FULLY_REFUNDED":
        _print("full refund payment status", False, str(store.orders[oid])); return
    _print("full refund sets FULLY_REFUNDED", True)


def t_reject_return_reverts(client):
    rid, cid, mid, riderid = _setup_order_world(client)
    _, body = env_call(client, "POST", "/api/orders", role="Customer", uid=cid,
                       json_body={"customer_id": cid, "restaurant_id": rid,
                                  "items": [{"menu_item_id": mid, "quantity": 1}]})
    oid = body["data"]["id"]
    env_call(client, "POST", f"/api/orders/{oid}/accept", role="Restaurant", uid=rid)
    env_call(client, "POST", f"/api/orders/{oid}/start-preparing", role="Restaurant", uid=rid)
    aid = [a["id"] for a in store.assignments.values() if a["order_id"] == oid][0]
    env_call(client, "POST", f"/api/assignments/{aid}/accept", role="Rider", uid=riderid)
    env_call(client, "POST", f"/api/orders/{oid}/ready", role="Restaurant", uid=rid)
    env_call(client, "POST", f"/api/assignments/{aid}/pickup", role="Rider", uid=riderid)
    env_call(client, "POST", f"/api/assignments/{aid}/deliver", role="Rider", uid=riderid)
    _, body = env_call(client, "POST", f"/api/orders/{oid}/returns", role="Customer", uid=cid,
                       json_body={"reason": "OTHER", "requested_refund_cents": 100})
    rretid = body["data"]["id"]
    env_call(client, "POST", f"/api/returns/{rretid}/reject", role="CustomerService", uid="cs-1")
    if store.orders[oid]["status"] != "DELIVERED":
        _print("reject reverts order", False, str(store.orders[oid])); return
    _print("reject return reverts order to DELIVERED", True)


def t_return_reopen(client):
    rid, cid, mid, riderid = _setup_order_world(client)
    _, body = env_call(client, "POST", "/api/orders", role="Customer", uid=cid,
                       json_body={"customer_id": cid, "restaurant_id": rid,
                                  "items": [{"menu_item_id": mid, "quantity": 1}]})
    oid = body["data"]["id"]
    env_call(client, "POST", f"/api/orders/{oid}/accept", role="Restaurant", uid=rid)
    env_call(client, "POST", f"/api/orders/{oid}/start-preparing", role="Restaurant", uid=rid)
    aid = [a["id"] for a in store.assignments.values() if a["order_id"] == oid][0]
    env_call(client, "POST", f"/api/assignments/{aid}/accept", role="Rider", uid=riderid)
    env_call(client, "POST", f"/api/orders/{oid}/ready", role="Restaurant", uid=rid)
    env_call(client, "POST", f"/api/assignments/{aid}/pickup", role="Rider", uid=riderid)
    env_call(client, "POST", f"/api/assignments/{aid}/deliver", role="Rider", uid=riderid)
    _, body = env_call(client, "POST", f"/api/orders/{oid}/returns", role="Customer", uid=cid,
                       json_body={"reason": "OTHER", "requested_refund_cents": 100})
    rretid = body["data"]["id"]
    env_call(client, "POST", f"/api/returns/{rretid}/escalate", role="CustomerService", uid="cs-1")
    code, body = env_call(client, "POST", f"/api/returns/{rretid}/reopen",
                          role="CustomerService", uid="cs-1")
    if store.returns_[rretid]["status"] != "REQUESTED":
        _print("reopen sets REQUESTED", False, str(store.returns_[rretid])); return
    _print("reopen ESCALATED -> REQUESTED", True)


def t_work_order_open_and_lifecycle(client):
    store.reset_all()
    # Customer opens a generic ticket
    _, body = env_call(client, "POST", "/api/customers", role="PlatformAdmin",
                       json_body={"name": "C", "phone": "1", "address": "a", "lat": 0, "lng": 0})
    cid = body["data"]["id"]
    code, body = env_call(client, "POST", "/api/work-orders", role="Customer", uid=cid,
                          json_body={"category": "OTHER"})
    if not expect_ok("open work order", code, body, status=201): return
    wid = body["data"]["id"]
    if body["data"]["opened_by_role"] != "CUSTOMER":
        _print("opened_by_role CUSTOMER", False, str(body["data"])); return
    _print("customer opens work order; opened_by_role=CUSTOMER", True)
    env_call(client, "POST", f"/api/work-orders/{wid}/assign", role="CustomerService", uid="cs-7")
    if store.work_orders[wid]["assigned_cs_user_id"] != "cs-7":
        _print("WO assign records cs id", False); return
    _print("WO assign stamps assigned_cs_user_id", True)
    env_call(client, "POST", f"/api/work-orders/{wid}/request-info", role="CustomerService", uid="cs-7")
    code, body = env_call(client, "POST", f"/api/work-orders/{wid}/submit-info",
                          role="Customer", uid=cid)
    if store.work_orders[wid]["status"] != "UNDER_REVIEW":
        _print("submit-info returns UNDER_REVIEW", False); return
    _print("submit-info -> UNDER_REVIEW", True)
    env_call(client, "POST", f"/api/work-orders/{wid}/resolve", role="CustomerService", uid="cs-7",
             json_body={"resolution_notes": "ok"})
    if store.work_orders[wid]["status"] != "RESOLVED":
        _print("resolve unrelated WO", False); return
    _print("resolve without linked return", True)
    env_call(client, "POST", f"/api/work-orders/{wid}/close", role="CustomerService", uid="cs-7")
    if store.work_orders[wid]["status"] != "CLOSED":
        _print("close WO", False); return
    _print("WO close RESOLVED -> CLOSED", True)


def t_fine_subject_filter_identity(client):
    """A Rider asking for fines must be limited to their own subject_id."""
    rid, cid, mid, riderid = _setup_order_world(client)
    _, body = env_call(client, "POST", "/api/orders", role="Customer", uid=cid,
                       json_body={"customer_id": cid, "restaurant_id": rid,
                                  "items": [{"menu_item_id": mid, "quantity": 1}]})
    oid = body["data"]["id"]
    env_call(client, "POST", f"/api/orders/{oid}/accept", role="Restaurant", uid=rid)
    env_call(client, "POST", f"/api/orders/{oid}/start-preparing", role="Restaurant", uid=rid)
    aid = [a["id"] for a in store.assignments.values() if a["order_id"] == oid][0]
    env_call(client, "POST", f"/api/assignments/{aid}/accept", role="Rider", uid=riderid)
    env_call(client, "POST", f"/api/assignments/{aid}/cancel", role="Rider", uid=riderid)
    # Rider lists fines: should see their own
    code, body = env_call(client, "GET", "/api/fines", role="Rider", uid=riderid)
    if not expect_ok("rider lists own fines", code, body): return
    if not any(f["subject_id"] == riderid for f in body["data"]):
        _print("rider sees their own fine", False, str(body["data"])); return
    _print("rider lists own fines", True)
    # Another subject_id is forbidden
    code, body = env_call(client, "GET", "/api/fines?subject_id=other", role="Rider", uid=riderid)
    expect_err("rider lists other's fines", code, body, "ERR_FORBIDDEN", 403) and _print(
        "rider cannot query another subject's fines", True
    )


def t_dispatch_excludes_same_rider(client):
    """Rider already holding an OFFERED for the order is excluded from new dispatch pool."""
    rid, cid, mid, riderid = _setup_order_world(client)
    _, body = env_call(client, "POST", "/api/orders", role="Customer", uid=cid,
                       json_body={"customer_id": cid, "restaurant_id": rid,
                                  "items": [{"menu_item_id": mid, "quantity": 1}]})
    oid = body["data"]["id"]
    env_call(client, "POST", f"/api/orders/{oid}/accept", role="Restaurant", uid=rid)
    env_call(client, "POST", f"/api/orders/{oid}/start-preparing", role="Restaurant", uid=rid)
    # Only one rider, who now has OFFERED. /dispatch should refuse with empty pool.
    code, body = env_call(client, "POST", f"/api/orders/{oid}/dispatch", role="PlatformAdmin")
    expect_err("rider excluded", code, body, "ERR_INVALID_STATE", 409) and _print(
        "rider already holding OFFERED is excluded from /dispatch pool", True
    )


def t_workorder_resolve_requires_assignee(client):
    store.reset_all()
    _, body = env_call(client, "POST", "/api/customers", role="PlatformAdmin",
                       json_body={"name": "C", "phone": "1", "address": "a", "lat": 0, "lng": 0})
    cid = body["data"]["id"]
    _, body = env_call(client, "POST", "/api/work-orders", role="Customer", uid=cid,
                       json_body={"category": "OTHER"})
    wid = body["data"]["id"]
    # Without assign, resolve should fail
    code, body = env_call(client, "POST", f"/api/work-orders/{wid}/resolve",
                          role="CustomerService", uid="cs-1",
                          json_body={"resolution_notes": "x"})
    expect_err("resolve before assign", code, body, "ERR_INVALID_STATE", 409) and _print(
        "WO resolve requires assigned_cs_user_id", True
    )


def t_clock_advance_validates(client):
    code, body = env_call(client, "POST", "/api/_clock/advance", role="PlatformAdmin",
                          json_body={"seconds": -1})
    expect_err("clock advance negative", code, body, "ERR_VALIDATION", 422) and _print(
        "clock advance rejects negative seconds", True
    )


def t_rider_metric_init(client):
    store.reset_all()
    _, body = env_call(client, "POST", "/api/riders", role="PlatformAdmin",
                       json_body={"name": "R", "phone": "9"})
    r = body["data"]
    if (r["on_time_rate"] == 1.0 and r["acceptance_rate"] == 1.0 and
            r["rating"] == 5.0 and r["wallet_balance_cents"] == 0):
        _print("rider initial metrics 1.0/1.0/5.0/0", True)
    else:
        _print("rider initial metrics", False, str(r))


def t_full_pipeline(client):
    tests = [
        t_envelope_basic,
        t_auth_required,
        t_forbidden_role,
        t_restaurant_lifecycle,
        t_restaurant_name_unique,
        t_occ_version,
        t_menu_items,
        t_customer_register,
        t_rider_lifecycle,
        t_order_placement,
        t_provisional_fee_formula,
        t_inactive_restaurant_blocks,
        t_full_happy_path,
        t_commission_tiered_boundaries,
        t_commission_override,
        t_late_delivery_fine,
        t_late_fine_tier2_tier3,
        t_bonus_tier_boundaries,
        t_peak_window_freezes,
        t_validation_pipeline_order,
        t_order_already_assigned,
        t_no_show_fine,
        t_clock_offer_timeout,
        t_return_window,
        t_duplicate_return,
        t_return_window_expired,
        t_work_order_resolve_gating,
        t_fine_waive,
        t_suspended_cancels_placed_orders,
        t_pagination,
        t_route_merge,
        t_merge_discount,
        t_abusive_return_fine,
        t_haversine_distance,
        t_dispatch_no_riders,
        t_ready_requires_accepted_dispatch,
        t_go_offline_blocked_by_live_assignment,
        t_cancel_after_placed_disallowed,
        t_id_format_no_prefix,
        t_order_invalid_subtotal_below_100,
        t_order_bad_menu_item,
        t_order_unlisted_menu_item,
        t_validation_missing_field,
        t_validation_pipeline_path_before_body_fk,
        t_restaurant_patch_identity,
        t_settle_decrement_on_approve,
        t_full_refund_status,
        t_reject_return_reverts,
        t_return_reopen,
        t_work_order_open_and_lifecycle,
        t_fine_subject_filter_identity,
        t_dispatch_excludes_same_rider,
        t_workorder_resolve_requires_assignee,
        t_clock_advance_validates,
        t_rider_metric_init,
    ]
    for t in tests:
        try:
            store.reset_all()
            t(client)
        except Exception as exc:
            tb = traceback.format_exc()
            _print(t.__name__, False, f"{exc}\n{tb}")


def main() -> int:
    app = create_app()
    with app.test_client() as client:
        t_full_pipeline(client)
    print(f"\n{_passed} passed, {len(_failures)} failed")
    if _failures:
        print("\nFailures:")
        for name, detail in _failures:
            print(f" - {name}: {detail[:300]}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
