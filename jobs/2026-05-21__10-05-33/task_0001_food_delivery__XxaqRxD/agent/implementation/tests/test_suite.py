"""Self-test suite mapped to PRD clauses."""
from __future__ import annotations

from tests.harness import TestApp, expect, expect_eq, expect_err, run_all, test


# ----------------------------------------------------------------- helpers


def register_restaurant(t: TestApp, name="R", lat=40.0, lng=-74.0, cro=None):
    body = {"name": name, "address": "addr", "lat": lat, "lng": lng}
    if cro is not None:
        body["commission_rate_override"] = cro
    code, b = t.admin("POST", "/api/restaurants", json_body=body)
    expect_eq(code, 201, "register_restaurant")
    return b["data"]["id"]


def approve_restaurant(t: TestApp, rid: str):
    code, b = t.admin("POST", f"/api/restaurants/{rid}/approve")
    expect_eq(code, 200, "approve_restaurant")
    return b["data"]


def setup_active_restaurant(t: TestApp, name="R", **kw):
    rid = register_restaurant(t, name=name, **kw)
    approve_restaurant(t, rid)
    return rid


def add_menu_item(t: TestApp, rid: str, name="Pizza", price=1200):
    code, b = t.admin(
        "POST", f"/api/restaurants/{rid}/menu-items", json_body={"name": name, "price_cents": price}
    )
    expect_eq(code, 201, "add_menu_item")
    return b["data"]["id"]


def register_customer(t: TestApp, name="C", phone="+1-555", lat=40.02, lng=-74.0):
    code, b = t.admin(
        "POST",
        "/api/customers",
        json_body={"name": name, "phone": phone, "address": "a", "lat": lat, "lng": lng},
    )
    expect_eq(code, 201)
    return b["data"]["id"]


def register_rider(t: TestApp, name="Bob", phone="+1-666"):
    code, b = t.admin("POST", "/api/riders", json_body={"name": name, "phone": phone})
    expect_eq(code, 201)
    return b["data"]["id"]


def go_online(t: TestApp, rid: str):
    code, b = t.request("POST", f"/api/riders/{rid}/go-online", user_id=rid, role="Rider")
    expect_eq(code, 200)
    return b


def place_order(t: TestApp, cid: str, rid_rest: str, item_id: str, qty=2):
    code, b = t.request(
        "POST",
        "/api/orders",
        user_id=cid,
        role="Customer",
        json_body={
            "customer_id": cid,
            "restaurant_id": rid_rest,
            "items": [{"menu_item_id": item_id, "quantity": qty}],
        },
    )
    expect_eq(code, 201, f"place_order: {b}")
    return b["data"]


def get_assignment_for_order(app: TestApp, order_id: str, status_in=None):
    for a in app.store.assignments.values():
        if a["order_id"] == order_id:
            if status_in is None or a["status"] in status_in:
                return a
    return None


# =============================================================== Section 2.1


@test("2.1 RBAC")
def auth_missing_headers(t):
    code, b = t.client.open("/api/restaurants", method="GET"), None
    sc, body = code.status_code, None
    expect_eq(sc, 401, "no headers => 401")


@test("2.1 RBAC")
def auth_unknown_role(t):
    code, body = t.request("GET", "/api/restaurants", user_id="x", role="Banana")
    expect_eq(code, 401)
    expect_eq(body["data"]["error_id"], "ERR_AUTH_REQUIRED")


@test("2.1 RBAC")
def role_not_allowed_register_restaurant(t):
    code, body = t.request("POST", "/api/restaurants", user_id="c1", role="Customer", json_body={"name": "X", "address": "a", "lat": 0.0, "lng": 0.0})
    expect_eq(code, 403)
    expect_eq(body["data"]["error_id"], "ERR_FORBIDDEN")


@test("2.1 RBAC")
def customer_cannot_read_other_customer(t):
    a = register_customer(t, phone="1")
    b = register_customer(t, phone="2")
    code, body = t.request("GET", f"/api/customers/{b}", user_id=a, role="Customer")
    expect_eq(code, 403)
    expect_eq(body["data"]["error_id"], "ERR_FORBIDDEN")


@test("2.1 RBAC")
def opaque_role_user_id_not_compared(t):
    # CS can read any customer; X-User-ID is opaque
    c = register_customer(t)
    code, body = t.request("GET", f"/api/customers/{c}", user_id="any-opaque", role="CustomerService")
    expect_eq(code, 200)


# =============================================================== Section 2.2


@test("2.2 Envelope")
def success_envelope_shape(t):
    code, body = t.admin("GET", "/api/restaurants")
    expect_eq(code, 200)
    expect("meta" in body and "response_type" in body and "data" in body)
    expect(body["response_type"] == "array")
    expect_eq(body["meta"]["limit"], 10)
    expect_eq(body["meta"]["offset"], 0)
    expect_eq(body["meta"]["total_count"], 0)
    expect_eq(body["meta"]["has_more"], False)
    expect(body["meta"]["api_request_id"].startswith("req_"))


@test("2.2 Envelope")
def error_envelope_shape(t):
    code, body = t.client.open("/api/restaurants", method="GET").status_code, None
    # use proper request
    code, body = t.request("GET", "/api/restaurants/nope", user_id="admin1", role="PlatformAdmin")
    expect_eq(code, 404)
    expect_eq(body["response_type"], "error")
    expect_eq(body["data"]["error_id"], "ERR_NOT_FOUND")
    expect("api_request_id" in body["meta"])
    expect("api_request_timestamp" in body["meta"])


# =============================================================== Section 2.3 pagination


@test("2.3 Pagination")
def pagination_defaults(t):
    code, body = t.admin("GET", "/api/restaurants")
    expect_eq(body["meta"]["limit"], 10)
    expect_eq(body["meta"]["offset"], 0)


@test("2.3 Pagination")
def pagination_window_and_has_more(t):
    for i in range(15):
        register_restaurant(t, name=f"R{i}")
    code, body = t.admin("GET", "/api/restaurants", params={"limit": "5", "offset": "10"})
    expect_eq(code, 200)
    expect_eq(body["meta"]["limit"], 5)
    expect_eq(body["meta"]["offset"], 10)
    expect_eq(body["meta"]["total_count"], 15)
    expect_eq(body["meta"]["has_more"], False)
    expect_eq(len(body["data"]), 5)


@test("2.3 Pagination")
def pagination_limit_oob_rejected(t):
    code, body = t.admin("GET", "/api/restaurants", params={"limit": "101"})
    expect_eq(code, 422)
    expect_eq(body["data"]["error_id"], "ERR_VALIDATION")
    code, body = t.admin("GET", "/api/restaurants", params={"limit": "0"})
    expect_eq(code, 422)
    code, body = t.admin("GET", "/api/restaurants", params={"offset": "-1"})
    expect_eq(code, 422)


# =============================================================== Section 2.4 audit fields


@test("2.4 Audit")
def restaurant_has_audit_fields(t):
    rid = register_restaurant(t)
    code, body = t.admin("GET", f"/api/restaurants/{rid}")
    d = body["data"]
    for f in ("id", "created_at", "updated_at", "version"):
        expect(f in d, f"missing {f}")
    expect_eq(d["version"], 1)


@test("2.4 Audit")
def assignment_no_version_field(t):
    # Set up an order and produce an assignment.
    rid = setup_active_restaurant(t)
    mid = add_menu_item(t, rid)
    cid = register_customer(t)
    rider = register_rider(t)
    go_online(t, rider)
    o = place_order(t, cid, rid, mid)
    t.request("POST", f"/api/orders/{o['id']}/accept", user_id=rid, role="Restaurant")
    t.request("POST", f"/api/orders/{o['id']}/start-preparing", user_id=rid, role="Restaurant")
    a = get_assignment_for_order(t, o["id"])
    expect(a is not None, "assignment should exist")
    code, body = t.admin("GET", f"/api/assignments/{a['id']}")
    d = body["data"]
    expect("version" not in d, "assignment must not expose version")
    expect("updated_at" not in d, "assignment must not expose updated_at")


# =============================================================== Section 2.5 OCC


@test("2.5 OCC")
def occ_version_mismatch(t):
    rid = register_restaurant(t)
    code, body = t.admin("PATCH", f"/api/restaurants/{rid}", json_body={"address": "x", "version": 99})
    expect_eq(code, 409)
    expect_eq(body["data"]["error_id"], "ERR_VERSION_CONFLICT")


@test("2.5 OCC")
def occ_no_version_no_check(t):
    rid = register_restaurant(t)
    code, body = t.admin("PATCH", f"/api/restaurants/{rid}", json_body={"address": "x"})
    expect_eq(code, 200)


@test("2.5 OCC")
def occ_two_writers_race(t):
    rid = register_restaurant(t)
    # First write with version=1
    code1, b1 = t.admin("PATCH", f"/api/restaurants/{rid}", json_body={"address": "a1", "version": 1})
    expect_eq(code1, 200)
    code2, b2 = t.admin("PATCH", f"/api/restaurants/{rid}", json_body={"address": "a2", "version": 1})
    expect_eq(code2, 409)


# =============================================================== Section 2.6 validation pipeline


@test("2.6 Pipeline")
def pipeline_auth_before_role(t):
    code, body = t.request("POST", "/api/restaurants", user_id=None, role=None, json_body={})
    expect_eq(code, 401)


@test("2.6 Pipeline")
def pipeline_role_before_not_found(t):
    # Customer can't create restaurants — should be FORBIDDEN even though path id is absent
    code, body = t.request("POST", "/api/restaurants", user_id="c", role="Customer", json_body={"name": "X"})
    expect_eq(code, 403)


@test("2.6 Pipeline")
def pipeline_not_found_before_state(t):
    # Approving a non-existent restaurant -> 404, not 409.
    code, body = t.admin("POST", "/api/restaurants/no-such/approve")
    expect_eq(code, 404)


# =============================================================== Section 2.8 cascade


@test("2.8 Cascade")
def cascade_suspend_cancels_placed_orders(t):
    rid = setup_active_restaurant(t)
    mid = add_menu_item(t, rid)
    cid = register_customer(t)
    o = place_order(t, cid, rid, mid)
    # Suspend the restaurant.
    code, body = t.admin("POST", f"/api/restaurants/{rid}/suspend")
    expect_eq(code, 200)
    # The placed order should now be CANCELLED, payment VOIDED.
    code, body = t.admin("GET", f"/api/orders/{o['id']}")
    expect_eq(body["data"]["status"], "CANCELLED")
    expect_eq(body["data"]["payment_status"], "VOIDED")


# =============================================================== Section 2.10 peak


@test("2.10 Peak")
def peak_window_detected(t):
    # Advance clock to 12:00 UTC.
    t.admin("POST", "/api/_clock/advance", json_body={"seconds": 12 * 3600})
    rid = setup_active_restaurant(t)
    mid = add_menu_item(t, rid)
    cid = register_customer(t)
    o = place_order(t, cid, rid, mid)
    expect_eq(o["is_peak"], True)
    # provisional fee should include 200c peak.
    # distance ~2.2km bands=3 => 300+360+200=860
    expect_eq(o["provisional_delivery_fee_cents"], 860)


@test("2.10 Peak")
def non_peak_window(t):
    # Advance clock to 10:00 UTC (not peak).
    t.admin("POST", "/api/_clock/advance", json_body={"seconds": 10 * 3600})
    rid = setup_active_restaurant(t)
    mid = add_menu_item(t, rid)
    cid = register_customer(t)
    o = place_order(t, cid, rid, mid)
    expect_eq(o["is_peak"], False)


# =============================================================== Section 3.1 restaurant lifecycle


@test("3.1 Restaurant")
def restaurant_starts_pending(t):
    rid = register_restaurant(t)
    code, body = t.admin("GET", f"/api/restaurants/{rid}")
    expect_eq(body["data"]["status"], "PENDING_APPROVAL")
    expect_eq(body["data"]["pending_settlement_cents"], 0)
    expect_eq(body["data"]["commission_rate_override"], None)


@test("3.1 Restaurant")
def restaurant_approve_only_from_pending(t):
    rid = setup_active_restaurant(t)
    code, body = t.admin("POST", f"/api/restaurants/{rid}/approve")
    expect_eq(code, 409)


@test("3.1 Restaurant")
def restaurant_suspend_reinstate(t):
    rid = setup_active_restaurant(t)
    t.admin("POST", f"/api/restaurants/{rid}/suspend")
    code, body = t.admin("GET", f"/api/restaurants/{rid}")
    expect_eq(body["data"]["status"], "SUSPENDED")
    t.admin("POST", f"/api/restaurants/{rid}/reinstate")
    code, body = t.admin("GET", f"/api/restaurants/{rid}")
    expect_eq(body["data"]["status"], "ACTIVE")


@test("3.1 Restaurant")
def restaurant_settle_zeroes_pending(t):
    rid = setup_active_restaurant(t)
    # forcibly bump pending
    t.store.restaurants[rid]["pending_settlement_cents"] = 9999
    code, body = t.admin("POST", f"/api/restaurants/{rid}/settle")
    expect_eq(code, 200)
    expect_eq(body["data"]["pending_settlement_cents"], 0)


@test("3.1 Restaurant")
def restaurant_name_immutable(t):
    rid = setup_active_restaurant(t, name="Old")
    code, body = t.admin("PATCH", f"/api/restaurants/{rid}", json_body={"name": "New"})
    # name not in mutable list per PRD — but the implementation simply ignores extra fields.
    expect_eq(code, 200)
    code, body = t.admin("GET", f"/api/restaurants/{rid}")
    expect_eq(body["data"]["name"], "Old")


@test("3.1 Restaurant")
def restaurant_commission_override_range(t):
    code, body = t.admin(
        "POST",
        "/api/restaurants",
        json_body={"name": "R", "address": "a", "lat": 0, "lng": 0, "commission_rate_override": 0.04},
    )
    expect_eq(code, 422)
    code, body = t.admin(
        "POST",
        "/api/restaurants",
        json_body={"name": "R", "address": "a", "lat": 0, "lng": 0, "commission_rate_override": 0.40},
    )
    expect_eq(code, 422)


# =============================================================== Section 3.2 customer


@test("3.2 Customer")
def customer_phone_unique(t):
    register_customer(t, phone="dup")
    code, body = t.admin(
        "POST",
        "/api/customers",
        json_body={"name": "B", "phone": "dup", "address": "x", "lat": 0, "lng": 0},
    )
    expect_eq(code, 422)


@test("3.2 Customer")
def customer_initial_fields(t):
    cid = register_customer(t)
    code, body = t.admin("GET", f"/api/customers/{cid}")
    expect_eq(body["data"]["credit_balance_cents"], 0)
    expect_eq(body["data"]["trust_score"], 1.0)


# =============================================================== Section 3.3 rider


@test("3.3 Rider")
def rider_starts_offline_bronze(t):
    rid = register_rider(t)
    code, body = t.admin("GET", f"/api/riders/{rid}")
    expect_eq(body["data"]["status"], "OFFLINE")
    expect_eq(body["data"]["bonus_tier"], "BRONZE")
    expect_eq(body["data"]["on_time_rate"], 1.0)
    expect_eq(body["data"]["acceptance_rate"], 1.0)
    expect_eq(body["data"]["rating"], 5.0)
    expect_eq(body["data"]["wallet_balance_cents"], 0)


@test("3.3 Rider")
def rider_go_offline_blocked_by_offered(t):
    rid_rest = setup_active_restaurant(t)
    mid = add_menu_item(t, rid_rest)
    cid = register_customer(t)
    rider = register_rider(t)
    go_online(t, rider)
    o = place_order(t, cid, rid_rest, mid)
    t.request("POST", f"/api/orders/{o['id']}/accept", user_id=rid_rest, role="Restaurant")
    t.request("POST", f"/api/orders/{o['id']}/start-preparing", user_id=rid_rest, role="Restaurant")
    # Rider is now ON_DELIVERY or has an OFFERED assignment. go-offline must fail.
    # First force them to AVAILABLE? Going offline while AVAILABLE with an OFFERED tied to them.
    code, body = t.request("POST", f"/api/riders/{rider}/go-offline", user_id=rider, role="Rider")
    expect_eq(code, 409)


@test("3.3 Rider")
def rider_suspend_requires_threshold_breach(t):
    rider = register_rider(t)
    go_online(t, rider)
    code, body = t.admin("POST", f"/api/riders/{rider}/suspend")
    expect_eq(code, 422)
    expect_eq(body["data"]["error_id"], "ERR_SUSPEND_CRITERIA_NOT_MET")
    # Force a metric below threshold then try again.
    t.store.riders[rider]["acceptance_rate"] = 0.3
    code, body = t.admin("POST", f"/api/riders/{rider}/suspend")
    expect_eq(code, 200)


@test("3.3 Rider")
def bonus_tier_boundaries(t):
    from server.bonus import compute_bonus_tier

    expect_eq(compute_bonus_tier(0.9, 0.9, 5.0), "PLATINUM")  # score = 0.9
    expect_eq(compute_bonus_tier(1.0, 1.0, 0.0), "PLATINUM")  # 0.6+0.3+0 = 0.9
    # Score exactly 0.8
    expect_eq(compute_bonus_tier(0.8, 0.8, 4.0), "GOLD")
    # Score exactly 0.7
    # 0.6*x + 0.3*y + 0.1*z = 0.7. Use on_time=0.7, accept=0.7, rating=3.5 → 0.42+0.21+0.07=0.70
    expect_eq(compute_bonus_tier(0.7, 0.7, 3.5), "SILVER")
    expect_eq(compute_bonus_tier(0.5, 0.5, 2.5), "BRONZE")


# =============================================================== Section 3.4 placement


@test("3.4 Placement")
def place_subtotal_distance_peak_promised(t):
    rid = setup_active_restaurant(t, lat=40.0, lng=-74.0)
    mid = add_menu_item(t, rid, price=2500)
    cid = register_customer(t, lat=40.05, lng=-74.0)
    o = place_order(t, cid, rid, mid, qty=3)
    expect_eq(o["subtotal_cents"], 7500)
    # distance ~5.56km, rounded half-up 1 dec: 5.6
    expect_eq(o["distance_km"], 5.6)
    expect_eq(o["is_peak"], False)
    expect_eq(o["status"], "PLACED")
    expect_eq(o["payment_status"], "AUTHORIZED")


@test("3.4 Placement")
def commission_tiered_at_low_subtotal(t):
    rid = setup_active_restaurant(t)
    mid = add_menu_item(t, rid, price=5000)
    cid = register_customer(t)
    o = place_order(t, cid, rid, mid, qty=2)  # subtotal 10000 -> 15% -> 1500
    expect_eq(o["provisional_commission_cents"], 1500)


@test("3.4 Placement")
def commission_tiered_at_boundary(t):
    rid = setup_active_restaurant(t)
    mid = add_menu_item(t, rid, price=10_000)
    cid = register_customer(t)
    # subtotal 30000: tier1=20000*0.15=3000, tier2=10000*0.18=1800 -> 4800
    o = place_order(t, cid, rid, mid, qty=3)
    expect_eq(o["provisional_commission_cents"], 4800)


@test("3.4 Placement")
def commission_tiered_top_tier(t):
    rid = setup_active_restaurant(t)
    mid = add_menu_item(t, rid, price=10_000)
    cid = register_customer(t)
    # subtotal 60000: 20000*0.15=3000, 30000*0.18=5400, 10000*0.22=2200 -> 10600
    o = place_order(t, cid, rid, mid, qty=6)
    expect_eq(o["provisional_commission_cents"], 10_600)


@test("3.4 Placement")
def provisional_fee_no_peak_3_bands(t):
    rid = setup_active_restaurant(t, lat=40.0, lng=-74.0)
    mid = add_menu_item(t, rid, price=500)
    cid = register_customer(t, lat=40.02, lng=-74.0)
    o = place_order(t, cid, rid, mid)  # distance ~2.2 -> bands 3 -> 300+360 = 660
    expect_eq(o["provisional_delivery_fee_cents"], 660)


@test("3.4 Placement")
def reject_empty_items(t):
    rid = setup_active_restaurant(t)
    cid = register_customer(t)
    code, body = t.request(
        "POST",
        "/api/orders",
        user_id=cid,
        role="Customer",
        json_body={"customer_id": cid, "restaurant_id": rid, "items": []},
    )
    expect_eq(code, 422)
    expect_eq(body["data"]["error_id"], "ERR_ORDER_INVALID")


@test("3.4 Placement")
def reject_zero_quantity(t):
    rid = setup_active_restaurant(t)
    mid = add_menu_item(t, rid)
    cid = register_customer(t)
    code, body = t.request(
        "POST",
        "/api/orders",
        user_id=cid,
        role="Customer",
        json_body={
            "customer_id": cid,
            "restaurant_id": rid,
            "items": [{"menu_item_id": mid, "quantity": 0}],
        },
    )
    expect_eq(code, 422)
    expect_eq(body["data"]["error_id"], "ERR_ORDER_INVALID")


@test("3.4 Placement")
def reject_subtotal_below_100(t):
    rid = setup_active_restaurant(t)
    mid = add_menu_item(t, rid, price=50)
    cid = register_customer(t)
    code, body = t.request(
        "POST",
        "/api/orders",
        user_id=cid,
        role="Customer",
        json_body={
            "customer_id": cid,
            "restaurant_id": rid,
            "items": [{"menu_item_id": mid, "quantity": 1}],
        },
    )
    expect_eq(code, 422)
    expect_eq(body["data"]["error_id"], "ERR_ORDER_INVALID")


@test("3.4 Placement")
def restaurant_unavailable_when_pending(t):
    rid = register_restaurant(t)  # PENDING
    code, body = t.admin("POST", f"/api/restaurants/{rid}/menu-items", json_body={"name": "X", "price_cents": 200})
    mid = body["data"]["id"]
    cid = register_customer(t)
    code, body = t.request(
        "POST",
        "/api/orders",
        user_id=cid,
        role="Customer",
        json_body={
            "customer_id": cid,
            "restaurant_id": rid,
            "items": [{"menu_item_id": mid, "quantity": 1}],
        },
    )
    expect_eq(code, 422)
    expect_eq(body["data"]["error_id"], "ERR_RESTAURANT_UNAVAILABLE")


@test("3.4 Placement")
def unlisted_menu_item_unavailable(t):
    rid = setup_active_restaurant(t)
    mid = add_menu_item(t, rid)
    # Unlist it
    t.admin("PATCH", f"/api/menu-items/{mid}", json_body={"is_listed": False})
    cid = register_customer(t)
    code, body = t.request(
        "POST",
        "/api/orders",
        user_id=cid,
        role="Customer",
        json_body={
            "customer_id": cid,
            "restaurant_id": rid,
            "items": [{"menu_item_id": mid, "quantity": 1}],
        },
    )
    expect_eq(code, 422)
    expect_eq(body["data"]["error_id"], "ERR_RESTAURANT_UNAVAILABLE")


@test("3.4 Placement")
def credit_drawdown_at_placement(t):
    rid = setup_active_restaurant(t)
    mid = add_menu_item(t, rid, price=500)
    cid = register_customer(t)
    # Give credit
    t.store.customers[cid]["credit_balance_cents"] = 1000
    o = place_order(t, cid, rid, mid, qty=2)  # subtotal 1000
    # Charge = subtotal + fee. Credit drained down to max(0, credit - total)
    code, body = t.admin("GET", f"/api/customers/{cid}")
    expect_eq(body["data"]["credit_balance_cents"], 0)


# =============================================================== Section 3.5 restaurant-side flow


@test("3.5 Restaurant flow")
def accept_only_from_placed(t):
    rid = setup_active_restaurant(t)
    mid = add_menu_item(t, rid)
    cid = register_customer(t)
    o = place_order(t, cid, rid, mid)
    code, body = t.request("POST", f"/api/orders/{o['id']}/accept", user_id=rid, role="Restaurant")
    expect_eq(code, 200)
    code, body = t.request("POST", f"/api/orders/{o['id']}/accept", user_id=rid, role="Restaurant")
    expect_eq(code, 409)


@test("3.5 Restaurant flow")
def ready_blocked_until_assignment_accepted(t):
    rid = setup_active_restaurant(t)
    mid = add_menu_item(t, rid)
    cid = register_customer(t)
    o = place_order(t, cid, rid, mid)
    t.request("POST", f"/api/orders/{o['id']}/accept", user_id=rid, role="Restaurant")
    t.request("POST", f"/api/orders/{o['id']}/start-preparing", user_id=rid, role="Restaurant")
    # No rider available, no offer to accept => ready should fail.
    code, body = t.request("POST", f"/api/orders/{o['id']}/ready", user_id=rid, role="Restaurant")
    expect_eq(code, 409)


@test("3.5 Restaurant flow")
def cancel_places_to_voided(t):
    rid = setup_active_restaurant(t)
    mid = add_menu_item(t, rid)
    cid = register_customer(t)
    o = place_order(t, cid, rid, mid)
    code, body = t.request("POST", f"/api/orders/{o['id']}/cancel", user_id=cid, role="Customer")
    expect_eq(code, 200)
    expect_eq(body["data"]["status"], "CANCELLED")
    expect_eq(body["data"]["payment_status"], "VOIDED")


@test("3.5 Restaurant flow")
def cancel_blocked_past_placed(t):
    rid = setup_active_restaurant(t)
    mid = add_menu_item(t, rid)
    cid = register_customer(t)
    o = place_order(t, cid, rid, mid)
    t.request("POST", f"/api/orders/{o['id']}/accept", user_id=rid, role="Restaurant")
    code, body = t.request("POST", f"/api/orders/{o['id']}/cancel", user_id=cid, role="Customer")
    expect_eq(code, 409)


# =============================================================== Section 3.6 dispatch / assignment


@test("3.6 Dispatch")
def dispatch_picks_available_rider(t):
    rid = setup_active_restaurant(t)
    mid = add_menu_item(t, rid)
    cid = register_customer(t)
    rider = register_rider(t)
    go_online(t, rider)
    o = place_order(t, cid, rid, mid)
    t.request("POST", f"/api/orders/{o['id']}/accept", user_id=rid, role="Restaurant")
    t.request("POST", f"/api/orders/{o['id']}/start-preparing", user_id=rid, role="Restaurant")
    a = get_assignment_for_order(t, o["id"])
    expect(a is not None)
    expect_eq(a["status"], "OFFERED")
    expect_eq(a["rider_id"], rider)


@test("3.6 Dispatch")
def accept_uniqueness(t):
    """A second accept on the same order must fail with ERR_ORDER_ALREADY_ASSIGNED."""
    rid = setup_active_restaurant(t)
    mid = add_menu_item(t, rid)
    cid = register_customer(t)
    r1 = register_rider(t, phone="p1")
    r2 = register_rider(t, phone="p2")
    go_online(t, r1)
    go_online(t, r2)
    o = place_order(t, cid, rid, mid)
    t.request("POST", f"/api/orders/{o['id']}/accept", user_id=rid, role="Restaurant")
    t.request("POST", f"/api/orders/{o['id']}/start-preparing", user_id=rid, role="Restaurant")
    # Force a second offer manually via /dispatch.
    code, body = t.admin("POST", f"/api/orders/{o['id']}/dispatch")
    expect_eq(code, 201)
    a2 = body["data"]
    # First accept from r2 or r1 depending on dispatch tie-breaker, then the other tries.
    a1 = None
    for a in t.store.assignments.values():
        if a["order_id"] == o["id"] and a["id"] != a2["id"] and a["status"] == "OFFERED":
            a1 = a
            break
    expect(a1 is not None, "two OFFERED assignments expected")
    # Accept the first one.
    code, body = t.request("POST", f"/api/assignments/{a1['id']}/accept", user_id=a1["rider_id"], role="Rider")
    expect_eq(code, 200)
    # Second accept should now fail.
    code, body = t.request("POST", f"/api/assignments/{a2['id']}/accept", user_id=a2["rider_id"], role="Rider")
    expect(body["data"]["error_id"] in ("ERR_ORDER_ALREADY_ASSIGNED", "ERR_INVALID_STATE"),
           f"expected uniqueness conflict, got {body}")


@test("3.6 Dispatch")
def reject_redispatches(t):
    rid = setup_active_restaurant(t)
    mid = add_menu_item(t, rid)
    cid = register_customer(t)
    r1 = register_rider(t, phone="p1")
    r2 = register_rider(t, phone="p2")
    go_online(t, r1)
    go_online(t, r2)
    o = place_order(t, cid, rid, mid)
    t.request("POST", f"/api/orders/{o['id']}/accept", user_id=rid, role="Restaurant")
    t.request("POST", f"/api/orders/{o['id']}/start-preparing", user_id=rid, role="Restaurant")
    # Find the first assignment, reject it.
    a = get_assignment_for_order(t, o["id"], status_in=("OFFERED",))
    code, body = t.request("POST", f"/api/assignments/{a['id']}/reject", user_id=a["rider_id"], role="Rider")
    expect_eq(code, 200)
    # New OFFERED assignment to the other rider.
    a2 = None
    for x in t.store.assignments.values():
        if x["order_id"] == o["id"] and x["status"] == "OFFERED":
            a2 = x
            break
    expect(a2 is not None, "redispatch should create a new OFFERED")
    expect(a2["rider_id"] != a["rider_id"], "should target a different rider")


@test("3.6 Dispatch")
def cancel_after_accept_creates_no_show_fine(t):
    rid = setup_active_restaurant(t)
    mid = add_menu_item(t, rid)
    cid = register_customer(t)
    rider = register_rider(t)
    go_online(t, rider)
    o = place_order(t, cid, rid, mid)
    t.request("POST", f"/api/orders/{o['id']}/accept", user_id=rid, role="Restaurant")
    t.request("POST", f"/api/orders/{o['id']}/start-preparing", user_id=rid, role="Restaurant")
    a = get_assignment_for_order(t, o["id"])
    t.request("POST", f"/api/assignments/{a['id']}/accept", user_id=rider, role="Rider")
    code, body = t.request("POST", f"/api/assignments/{a['id']}/cancel", user_id=rider, role="Rider")
    expect_eq(code, 200)
    # Wallet debited 500.
    code, body = t.admin("GET", f"/api/riders/{rider}")
    expect_eq(body["data"]["wallet_balance_cents"], -500)
    # A RIDER_NO_SHOW fine exists.
    fines = [f for f in t.store.fines.values() if f["reason"] == "RIDER_NO_SHOW"]
    expect_eq(len(fines), 1)


@test("3.6 Dispatch")
def route_merge_within_500m(t):
    # Two restaurants near each other (~100m).
    rid1 = setup_active_restaurant(t, name="A", lat=40.0, lng=-74.0)
    rid2 = setup_active_restaurant(t, name="B", lat=40.0009, lng=-74.0)  # ~100m
    mid1 = add_menu_item(t, rid1)
    mid2 = add_menu_item(t, rid2)
    cid = register_customer(t, lat=40.05, lng=-74.0)
    rider = register_rider(t)
    go_online(t, rider)
    # Order 1 → accept → prepare → rider accepts → ON_DELIVERY
    o1 = place_order(t, cid, rid1, mid1)
    t.request("POST", f"/api/orders/{o1['id']}/accept", user_id=rid1, role="Restaurant")
    t.request("POST", f"/api/orders/{o1['id']}/start-preparing", user_id=rid1, role="Restaurant")
    a1 = get_assignment_for_order(t, o1["id"])
    t.request("POST", f"/api/assignments/{a1['id']}/accept", user_id=rider, role="Rider")
    # Order 2 → accept → prepare → dispatch should target same rider via merge.
    o2 = place_order(t, cid, rid2, mid2)
    t.request("POST", f"/api/orders/{o2['id']}/accept", user_id=rid2, role="Restaurant")
    t.request("POST", f"/api/orders/{o2['id']}/start-preparing", user_id=rid2, role="Restaurant")
    a2 = get_assignment_for_order(t, o2["id"])
    expect(a2 is not None)
    expect_eq(a2["rider_id"], rider, "merge-ready rider should be picked")
    t.request("POST", f"/api/assignments/{a2['id']}/accept", user_id=rider, role="Rider")
    # Both assignments should share a route_group_id.
    a1_refreshed = t.store.assignments[a1["id"]]
    a2_refreshed = t.store.assignments[a2["id"]]
    expect(a1_refreshed["route_group_id"] is not None)
    expect_eq(a1_refreshed["route_group_id"], a2_refreshed["route_group_id"])


# =============================================================== Section 3.7 delivery


@test("3.7 Delivery")
def deliver_on_time_no_late_fine(t):
    rid = setup_active_restaurant(t)
    mid = add_menu_item(t, rid)
    cid = register_customer(t)
    rider = register_rider(t)
    go_online(t, rider)
    o = place_order(t, cid, rid, mid)
    t.request("POST", f"/api/orders/{o['id']}/accept", user_id=rid, role="Restaurant")
    t.request("POST", f"/api/orders/{o['id']}/start-preparing", user_id=rid, role="Restaurant")
    a = get_assignment_for_order(t, o["id"])
    t.request("POST", f"/api/assignments/{a['id']}/accept", user_id=rider, role="Rider")
    t.request("POST", f"/api/orders/{o['id']}/ready", user_id=rid, role="Restaurant")
    t.request("POST", f"/api/assignments/{a['id']}/pickup", user_id=rider, role="Rider")
    code, body = t.request("POST", f"/api/assignments/{a['id']}/deliver", user_id=rider, role="Rider")
    expect_eq(code, 200)
    code, body = t.admin("GET", f"/api/orders/{o['id']}")
    expect_eq(body["data"]["status"], "DELIVERED")
    expect_eq(body["data"]["minutes_late"], 0)
    expect_eq(body["data"]["payment_status"], "CAPTURED")
    # No LATE_DELIVERY fine.
    fines = [f for f in t.store.fines.values() if f["reason"] == "LATE_DELIVERY"]
    expect_eq(len(fines), 0)


@test("3.7 Delivery")
def deliver_late_under_10m_fine_200(t):
    rid = setup_active_restaurant(t)
    mid = add_menu_item(t, rid)
    cid = register_customer(t)
    rider = register_rider(t)
    go_online(t, rider)
    o = place_order(t, cid, rid, mid)
    t.request("POST", f"/api/orders/{o['id']}/accept", user_id=rid, role="Restaurant")
    t.request("POST", f"/api/orders/{o['id']}/start-preparing", user_id=rid, role="Restaurant")
    a = get_assignment_for_order(t, o["id"])
    t.request("POST", f"/api/assignments/{a['id']}/accept", user_id=rider, role="Rider")
    t.request("POST", f"/api/orders/{o['id']}/ready", user_id=rid, role="Restaurant")
    t.request("POST", f"/api/assignments/{a['id']}/pickup", user_id=rider, role="Rider")
    # Advance clock by 50 minutes -> 5 minutes late.
    t.admin("POST", "/api/_clock/advance", json_body={"seconds": 50 * 60})
    t.request("POST", f"/api/assignments/{a['id']}/deliver", user_id=rider, role="Rider")
    code, body = t.admin("GET", f"/api/orders/{o['id']}")
    expect_eq(body["data"]["minutes_late"], 5)
    fines = [f for f in t.store.fines.values() if f["reason"] == "LATE_DELIVERY"]
    expect_eq(len(fines), 1)
    expect_eq(fines[0]["amount_cents"], 200)


@test("3.7 Delivery")
def deliver_late_11_to_30m_fine_tier2(t):
    rid = setup_active_restaurant(t)
    mid = add_menu_item(t, rid)
    cid = register_customer(t)
    rider = register_rider(t)
    go_online(t, rider)
    o = place_order(t, cid, rid, mid)
    t.request("POST", f"/api/orders/{o['id']}/accept", user_id=rid, role="Restaurant")
    t.request("POST", f"/api/orders/{o['id']}/start-preparing", user_id=rid, role="Restaurant")
    a = get_assignment_for_order(t, o["id"])
    t.request("POST", f"/api/assignments/{a['id']}/accept", user_id=rider, role="Rider")
    t.request("POST", f"/api/orders/{o['id']}/ready", user_id=rid, role="Restaurant")
    t.request("POST", f"/api/assignments/{a['id']}/pickup", user_id=rider, role="Rider")
    # 45 + 20 minutes late
    t.admin("POST", "/api/_clock/advance", json_body={"seconds": 65 * 60})
    t.request("POST", f"/api/assignments/{a['id']}/deliver", user_id=rider, role="Rider")
    fines = [f for f in t.store.fines.values() if f["reason"] == "LATE_DELIVERY"]
    expect_eq(fines[0]["amount_cents"], 500 + 50 * 10)  # 1000


@test("3.7 Delivery")
def deliver_late_over_30m_tier3(t):
    rid = setup_active_restaurant(t, lat=40.0, lng=-74.0)
    mid = add_menu_item(t, rid)
    cid = register_customer(t, lat=40.02, lng=-74.0)  # ~2.2km
    rider = register_rider(t)
    go_online(t, rider)
    o = place_order(t, cid, rid, mid)
    t.request("POST", f"/api/orders/{o['id']}/accept", user_id=rid, role="Restaurant")
    t.request("POST", f"/api/orders/{o['id']}/start-preparing", user_id=rid, role="Restaurant")
    a = get_assignment_for_order(t, o["id"])
    t.request("POST", f"/api/assignments/{a['id']}/accept", user_id=rider, role="Rider")
    t.request("POST", f"/api/orders/{o['id']}/ready", user_id=rid, role="Restaurant")
    t.request("POST", f"/api/assignments/{a['id']}/pickup", user_id=rider, role="Rider")
    t.admin("POST", "/api/_clock/advance", json_body={"seconds": (45 + 31) * 60})
    t.request("POST", f"/api/assignments/{a['id']}/deliver", user_id=rider, role="Rider")
    # final_delivery_fee = 660. Tier3 -> min(660, 1500) + 500 = 1160
    fines = [f for f in t.store.fines.values() if f["reason"] == "LATE_DELIVERY"]
    expect_eq(fines[0]["amount_cents"], 660 + 500)


@test("3.7 Delivery")
def restaurant_settlement_incremented(t):
    rid = setup_active_restaurant(t)
    mid = add_menu_item(t, rid)
    cid = register_customer(t)
    rider = register_rider(t)
    go_online(t, rider)
    o = place_order(t, cid, rid, mid)  # subtotal 2400, comm 360
    t.request("POST", f"/api/orders/{o['id']}/accept", user_id=rid, role="Restaurant")
    t.request("POST", f"/api/orders/{o['id']}/start-preparing", user_id=rid, role="Restaurant")
    a = get_assignment_for_order(t, o["id"])
    t.request("POST", f"/api/assignments/{a['id']}/accept", user_id=rider, role="Rider")
    t.request("POST", f"/api/orders/{o['id']}/ready", user_id=rid, role="Restaurant")
    t.request("POST", f"/api/assignments/{a['id']}/pickup", user_id=rider, role="Rider")
    t.request("POST", f"/api/assignments/{a['id']}/deliver", user_id=rider, role="Rider")
    code, body = t.admin("GET", f"/api/restaurants/{rid}")
    expect_eq(body["data"]["pending_settlement_cents"], 2400 - 360)


@test("3.7 Delivery")
def commission_override_applies_at_delivery(t):
    rid = setup_active_restaurant(t, cro=0.10)
    mid = add_menu_item(t, rid)
    cid = register_customer(t)
    rider = register_rider(t)
    go_online(t, rider)
    o = place_order(t, cid, rid, mid)  # subtotal 2400 -> at placement provisional uses tiered (360)
    # But delivery uses override 0.10 -> 240
    t.request("POST", f"/api/orders/{o['id']}/accept", user_id=rid, role="Restaurant")
    t.request("POST", f"/api/orders/{o['id']}/start-preparing", user_id=rid, role="Restaurant")
    a = get_assignment_for_order(t, o["id"])
    t.request("POST", f"/api/assignments/{a['id']}/accept", user_id=rider, role="Rider")
    t.request("POST", f"/api/orders/{o['id']}/ready", user_id=rid, role="Restaurant")
    t.request("POST", f"/api/assignments/{a['id']}/pickup", user_id=rider, role="Rider")
    t.request("POST", f"/api/assignments/{a['id']}/deliver", user_id=rider, role="Rider")
    code, body = t.admin("GET", f"/api/orders/{o['id']}")
    expect_eq(body["data"]["final_commission_cents"], 240)
    expect_eq(body["data"]["provisional_commission_cents"], 360)


@test("3.7 Delivery")
def merge_discount_applied(t):
    rid1 = setup_active_restaurant(t, name="A", lat=40.0, lng=-74.0)
    rid2 = setup_active_restaurant(t, name="B", lat=40.0009, lng=-74.0)
    mid1 = add_menu_item(t, rid1)
    mid2 = add_menu_item(t, rid2)
    cid = register_customer(t, lat=40.05, lng=-74.0)
    rider = register_rider(t)
    go_online(t, rider)
    o1 = place_order(t, cid, rid1, mid1)
    o2 = place_order(t, cid, rid2, mid2)
    t.request("POST", f"/api/orders/{o1['id']}/accept", user_id=rid1, role="Restaurant")
    t.request("POST", f"/api/orders/{o1['id']}/start-preparing", user_id=rid1, role="Restaurant")
    a1 = get_assignment_for_order(t, o1["id"])
    t.request("POST", f"/api/assignments/{a1['id']}/accept", user_id=rider, role="Rider")
    t.request("POST", f"/api/orders/{o2['id']}/accept", user_id=rid2, role="Restaurant")
    t.request("POST", f"/api/orders/{o2['id']}/start-preparing", user_id=rid2, role="Restaurant")
    a2 = get_assignment_for_order(t, o2["id"])
    t.request("POST", f"/api/assignments/{a2['id']}/accept", user_id=rider, role="Rider")
    # Mark both ready, pick up both, deliver both.
    for o, a, ridr in ((o1, a1, rid1), (o2, a2, rid2)):
        t.request("POST", f"/api/orders/{o['id']}/ready", user_id=ridr, role="Restaurant")
        t.request("POST", f"/api/assignments/{a['id']}/pickup", user_id=rider, role="Rider")
    t.request("POST", f"/api/assignments/{a1['id']}/deliver", user_id=rider, role="Rider")
    a1_now = t.store.assignments[a1["id"]]
    # Solo fee for distance 5.6km no peak: 300 + 6*120 = 1020. Discount floor(0.25*1020) = 255 → 765.
    # Actually our test sets distance ~ 5.56km rounded to 5.6 → bands = ceil(5.6)=6 → 300+720=1020. Discount floor(255) = 255 → 765.
    expect_eq(a1_now["final_delivery_fee_cents"], 765)


@test("3.7 Delivery")
def rider_returns_to_available_after_last_delivery(t):
    rid = setup_active_restaurant(t)
    mid = add_menu_item(t, rid)
    cid = register_customer(t)
    rider = register_rider(t)
    go_online(t, rider)
    o = place_order(t, cid, rid, mid)
    t.request("POST", f"/api/orders/{o['id']}/accept", user_id=rid, role="Restaurant")
    t.request("POST", f"/api/orders/{o['id']}/start-preparing", user_id=rid, role="Restaurant")
    a = get_assignment_for_order(t, o["id"])
    t.request("POST", f"/api/assignments/{a['id']}/accept", user_id=rider, role="Rider")
    t.request("POST", f"/api/orders/{o['id']}/ready", user_id=rid, role="Restaurant")
    t.request("POST", f"/api/assignments/{a['id']}/pickup", user_id=rider, role="Rider")
    t.request("POST", f"/api/assignments/{a['id']}/deliver", user_id=rider, role="Rider")
    code, body = t.admin("GET", f"/api/riders/{rider}")
    expect_eq(body["data"]["status"], "AVAILABLE")


# =============================================================== Section 3.9 returns


@test("3.9 Returns")
def open_return_only_after_delivered(t):
    rid = setup_active_restaurant(t)
    mid = add_menu_item(t, rid)
    cid = register_customer(t)
    o = place_order(t, cid, rid, mid)
    code, body = t.request(
        "POST",
        f"/api/orders/{o['id']}/returns",
        user_id=cid,
        role="Customer",
        json_body={"reason": "QUALITY_ISSUE", "requested_refund_cents": 100},
    )
    expect_eq(code, 409)


@test("3.9 Returns")
def return_window_24h(t):
    rid = setup_active_restaurant(t)
    mid = add_menu_item(t, rid)
    cid = register_customer(t)
    rider = register_rider(t)
    go_online(t, rider)
    o = place_order(t, cid, rid, mid)
    t.request("POST", f"/api/orders/{o['id']}/accept", user_id=rid, role="Restaurant")
    t.request("POST", f"/api/orders/{o['id']}/start-preparing", user_id=rid, role="Restaurant")
    a = get_assignment_for_order(t, o["id"])
    t.request("POST", f"/api/assignments/{a['id']}/accept", user_id=rider, role="Rider")
    t.request("POST", f"/api/orders/{o['id']}/ready", user_id=rid, role="Restaurant")
    t.request("POST", f"/api/assignments/{a['id']}/pickup", user_id=rider, role="Rider")
    t.request("POST", f"/api/assignments/{a['id']}/deliver", user_id=rider, role="Rider")
    # Advance > 24h
    t.admin("POST", "/api/_clock/advance", json_body={"seconds": 25 * 3600})
    code, body = t.request(
        "POST",
        f"/api/orders/{o['id']}/returns",
        user_id=cid,
        role="Customer",
        json_body={"reason": "LATE", "requested_refund_cents": 100},
    )
    expect_eq(body["data"]["error_id"], "ERR_RETURN_WINDOW_EXPIRED")


@test("3.9 Returns")
def duplicate_return_blocked(t):
    rid = setup_active_restaurant(t)
    mid = add_menu_item(t, rid)
    cid = register_customer(t)
    rider = register_rider(t)
    go_online(t, rider)
    o = place_order(t, cid, rid, mid)
    t.request("POST", f"/api/orders/{o['id']}/accept", user_id=rid, role="Restaurant")
    t.request("POST", f"/api/orders/{o['id']}/start-preparing", user_id=rid, role="Restaurant")
    a = get_assignment_for_order(t, o["id"])
    t.request("POST", f"/api/assignments/{a['id']}/accept", user_id=rider, role="Rider")
    t.request("POST", f"/api/orders/{o['id']}/ready", user_id=rid, role="Restaurant")
    t.request("POST", f"/api/assignments/{a['id']}/pickup", user_id=rider, role="Rider")
    t.request("POST", f"/api/assignments/{a['id']}/deliver", user_id=rider, role="Rider")
    code, body = t.request(
        "POST",
        f"/api/orders/{o['id']}/returns",
        user_id=cid,
        role="Customer",
        json_body={"reason": "LATE", "requested_refund_cents": 100},
    )
    expect_eq(code, 201)
    code, body = t.request(
        "POST",
        f"/api/orders/{o['id']}/returns",
        user_id=cid,
        role="Customer",
        json_body={"reason": "LATE", "requested_refund_cents": 100},
    )
    expect_eq(body["data"]["error_id"], "ERR_DUPLICATE_RETURN")


@test("3.9 Returns")
def approve_partially_refunded(t):
    rid = setup_active_restaurant(t)
    mid = add_menu_item(t, rid)
    cid = register_customer(t)
    rider = register_rider(t)
    go_online(t, rider)
    o = place_order(t, cid, rid, mid)  # subtotal 2400
    t.request("POST", f"/api/orders/{o['id']}/accept", user_id=rid, role="Restaurant")
    t.request("POST", f"/api/orders/{o['id']}/start-preparing", user_id=rid, role="Restaurant")
    a = get_assignment_for_order(t, o["id"])
    t.request("POST", f"/api/assignments/{a['id']}/accept", user_id=rider, role="Rider")
    t.request("POST", f"/api/orders/{o['id']}/ready", user_id=rid, role="Restaurant")
    t.request("POST", f"/api/assignments/{a['id']}/pickup", user_id=rider, role="Rider")
    t.request("POST", f"/api/assignments/{a['id']}/deliver", user_id=rider, role="Rider")
    code, body = t.request(
        "POST",
        f"/api/orders/{o['id']}/returns",
        user_id=cid,
        role="Customer",
        json_body={"reason": "LATE", "requested_refund_cents": 1000},
    )
    rid_ret = body["data"]["id"]
    code, body = t.cs("POST", f"/api/returns/{rid_ret}/approve", json_body={"approved_refund_cents": 500})
    expect_eq(code, 200)
    # Order PARTIALLY_REFUNDED.
    code, body = t.admin("GET", f"/api/orders/{o['id']}")
    expect_eq(body["data"]["status"], "REFUNDED")
    expect_eq(body["data"]["payment_status"], "PARTIALLY_REFUNDED")
    # Customer credit += 500
    code, body = t.admin("GET", f"/api/customers/{cid}")
    expect_eq(body["data"]["credit_balance_cents"], 500)
    # Restaurant pending_settlement_cents -= 500
    code, body = t.admin("GET", f"/api/restaurants/{rid}")
    expect_eq(body["data"]["pending_settlement_cents"], 2040 - 500)


@test("3.9 Returns")
def approve_fully_refunded_at_subtotal(t):
    rid = setup_active_restaurant(t)
    mid = add_menu_item(t, rid)
    cid = register_customer(t)
    rider = register_rider(t)
    go_online(t, rider)
    o = place_order(t, cid, rid, mid)  # subtotal 2400
    t.request("POST", f"/api/orders/{o['id']}/accept", user_id=rid, role="Restaurant")
    t.request("POST", f"/api/orders/{o['id']}/start-preparing", user_id=rid, role="Restaurant")
    a = get_assignment_for_order(t, o["id"])
    t.request("POST", f"/api/assignments/{a['id']}/accept", user_id=rider, role="Rider")
    t.request("POST", f"/api/orders/{o['id']}/ready", user_id=rid, role="Restaurant")
    t.request("POST", f"/api/assignments/{a['id']}/pickup", user_id=rider, role="Rider")
    t.request("POST", f"/api/assignments/{a['id']}/deliver", user_id=rider, role="Rider")
    code, body = t.request(
        "POST",
        f"/api/orders/{o['id']}/returns",
        user_id=cid,
        role="Customer",
        json_body={"reason": "LATE", "requested_refund_cents": 2400},
    )
    rid_ret = body["data"]["id"]
    t.cs("POST", f"/api/returns/{rid_ret}/approve", json_body={"approved_refund_cents": 2400})
    code, body = t.admin("GET", f"/api/orders/{o['id']}")
    expect_eq(body["data"]["payment_status"], "FULLY_REFUNDED")


@test("3.9 Returns")
def approve_amount_above_requested_invalid(t):
    rid = setup_active_restaurant(t)
    mid = add_menu_item(t, rid)
    cid = register_customer(t)
    rider = register_rider(t)
    go_online(t, rider)
    o = place_order(t, cid, rid, mid)
    t.request("POST", f"/api/orders/{o['id']}/accept", user_id=rid, role="Restaurant")
    t.request("POST", f"/api/orders/{o['id']}/start-preparing", user_id=rid, role="Restaurant")
    a = get_assignment_for_order(t, o["id"])
    t.request("POST", f"/api/assignments/{a['id']}/accept", user_id=rider, role="Rider")
    t.request("POST", f"/api/orders/{o['id']}/ready", user_id=rid, role="Restaurant")
    t.request("POST", f"/api/assignments/{a['id']}/pickup", user_id=rider, role="Rider")
    t.request("POST", f"/api/assignments/{a['id']}/deliver", user_id=rider, role="Rider")
    code, body = t.request(
        "POST",
        f"/api/orders/{o['id']}/returns",
        user_id=cid,
        role="Customer",
        json_body={"reason": "LATE", "requested_refund_cents": 200},
    )
    rid_ret = body["data"]["id"]
    code, body = t.cs("POST", f"/api/returns/{rid_ret}/approve", json_body={"approved_refund_cents": 300})
    expect_eq(body["data"]["error_id"], "ERR_REFUND_AMOUNT_INVALID")


@test("3.9 Returns")
def escalate_opens_workorder_reopen_closes_it(t):
    rid = setup_active_restaurant(t)
    mid = add_menu_item(t, rid)
    cid = register_customer(t)
    rider = register_rider(t)
    go_online(t, rider)
    o = place_order(t, cid, rid, mid)
    t.request("POST", f"/api/orders/{o['id']}/accept", user_id=rid, role="Restaurant")
    t.request("POST", f"/api/orders/{o['id']}/start-preparing", user_id=rid, role="Restaurant")
    a = get_assignment_for_order(t, o["id"])
    t.request("POST", f"/api/assignments/{a['id']}/accept", user_id=rider, role="Rider")
    t.request("POST", f"/api/orders/{o['id']}/ready", user_id=rid, role="Restaurant")
    t.request("POST", f"/api/assignments/{a['id']}/pickup", user_id=rider, role="Rider")
    t.request("POST", f"/api/assignments/{a['id']}/deliver", user_id=rider, role="Rider")
    code, body = t.request(
        "POST",
        f"/api/orders/{o['id']}/returns",
        user_id=cid,
        role="Customer",
        json_body={"reason": "LATE", "requested_refund_cents": 100},
    )
    rid_ret = body["data"]["id"]
    code, body = t.cs("POST", f"/api/returns/{rid_ret}/escalate")
    expect_eq(code, 200)
    # A WO exists with related_return_id == rid_ret and status OPEN.
    wos = [w for w in t.store.work_orders.values() if w.get("related_return_id") == rid_ret]
    expect_eq(len(wos), 1)
    expect_eq(wos[0]["status"], "OPEN")
    code, body = t.cs("POST", f"/api/returns/{rid_ret}/reopen")
    expect_eq(code, 200)
    wos = [w for w in t.store.work_orders.values() if w.get("related_return_id") == rid_ret]
    expect_eq(wos[0]["status"], "CLOSED")


@test("3.9 Returns")
def abusive_return_fine_when_trust_low(t):
    rid = setup_active_restaurant(t)
    mid = add_menu_item(t, rid)
    cid = register_customer(t)
    t.store.customers[cid]["trust_score"] = 0.3  # force low trust
    rider = register_rider(t)
    go_online(t, rider)
    o = place_order(t, cid, rid, mid)
    t.request("POST", f"/api/orders/{o['id']}/accept", user_id=rid, role="Restaurant")
    t.request("POST", f"/api/orders/{o['id']}/start-preparing", user_id=rid, role="Restaurant")
    a = get_assignment_for_order(t, o["id"])
    t.request("POST", f"/api/assignments/{a['id']}/accept", user_id=rider, role="Rider")
    t.request("POST", f"/api/orders/{o['id']}/ready", user_id=rid, role="Restaurant")
    t.request("POST", f"/api/assignments/{a['id']}/pickup", user_id=rider, role="Rider")
    t.request("POST", f"/api/assignments/{a['id']}/deliver", user_id=rider, role="Rider")
    code, body = t.request(
        "POST",
        f"/api/orders/{o['id']}/returns",
        user_id=cid,
        role="Customer",
        json_body={"reason": "QUALITY_ISSUE", "requested_refund_cents": 1000},
    )
    rid_ret = body["data"]["id"]
    code, body = t.cs("POST", f"/api/returns/{rid_ret}/approve", json_body={"approved_refund_cents": 500})
    expect_eq(code, 200)
    abusive = [f for f in t.store.fines.values() if f["reason"] == "ABUSIVE_RETURN"]
    expect_eq(len(abusive), 1)
    expect_eq(abusive[0]["amount_cents"], 500)


# =============================================================== Section 3.10 work orders


@test("3.10 WorkOrder")
def resolve_blocked_when_related_return_unresolved(t):
    rid = setup_active_restaurant(t)
    mid = add_menu_item(t, rid)
    cid = register_customer(t)
    rider = register_rider(t)
    go_online(t, rider)
    o = place_order(t, cid, rid, mid)
    t.request("POST", f"/api/orders/{o['id']}/accept", user_id=rid, role="Restaurant")
    t.request("POST", f"/api/orders/{o['id']}/start-preparing", user_id=rid, role="Restaurant")
    a = get_assignment_for_order(t, o["id"])
    t.request("POST", f"/api/assignments/{a['id']}/accept", user_id=rider, role="Rider")
    t.request("POST", f"/api/orders/{o['id']}/ready", user_id=rid, role="Restaurant")
    t.request("POST", f"/api/assignments/{a['id']}/pickup", user_id=rider, role="Rider")
    t.request("POST", f"/api/assignments/{a['id']}/deliver", user_id=rider, role="Rider")
    code, body = t.request(
        "POST",
        f"/api/orders/{o['id']}/returns",
        user_id=cid,
        role="Customer",
        json_body={"reason": "LATE", "requested_refund_cents": 100},
    )
    rid_ret = body["data"]["id"]
    t.cs("POST", f"/api/returns/{rid_ret}/escalate")
    # Find the auto-created WO.
    wo = [w for w in t.store.work_orders.values() if w.get("related_return_id") == rid_ret][0]
    t.cs("POST", f"/api/work-orders/{wo['id']}/assign")
    code, body = t.cs("POST", f"/api/work-orders/{wo['id']}/resolve", json_body={"resolution_notes": "ok"})
    expect_eq(body["data"]["error_id"], "ERR_RELATED_RETURN_UNRESOLVED")


@test("3.10 WorkOrder")
def workorder_full_flow(t):
    cid = register_customer(t)
    code, body = t.request(
        "POST",
        "/api/work-orders",
        user_id=cid,
        role="Customer",
        json_body={"category": "PAYMENT_ISSUE"},
    )
    wid = body["data"]["id"]
    expect_eq(body["data"]["status"], "OPEN")
    code, body = t.cs("POST", f"/api/work-orders/{wid}/assign")
    expect_eq(body["data"]["status"], "UNDER_REVIEW")
    code, body = t.cs("POST", f"/api/work-orders/{wid}/request-info")
    expect_eq(body["data"]["status"], "AWAITING_INFO")
    code, body = t.request("POST", f"/api/work-orders/{wid}/submit-info", user_id=cid, role="Customer")
    expect_eq(body["data"]["status"], "UNDER_REVIEW")
    code, body = t.cs("POST", f"/api/work-orders/{wid}/resolve", json_body={"resolution_notes": "done"})
    expect_eq(body["data"]["status"], "RESOLVED")
    code, body = t.cs("POST", f"/api/work-orders/{wid}/close")
    expect_eq(body["data"]["status"], "CLOSED")


# =============================================================== Section 3.11 fines


@test("3.11 Fines")
def waive_pending_fine_reverses(t):
    rid = setup_active_restaurant(t)
    mid = add_menu_item(t, rid)
    cid = register_customer(t)
    rider = register_rider(t)
    go_online(t, rider)
    o = place_order(t, cid, rid, mid)
    t.request("POST", f"/api/orders/{o['id']}/accept", user_id=rid, role="Restaurant")
    t.request("POST", f"/api/orders/{o['id']}/start-preparing", user_id=rid, role="Restaurant")
    a = get_assignment_for_order(t, o["id"])
    t.request("POST", f"/api/assignments/{a['id']}/accept", user_id=rider, role="Rider")
    t.request("POST", f"/api/assignments/{a['id']}/cancel", user_id=rider, role="Rider")
    # Wallet is -500. Waive the fine.
    fine = next(f for f in t.store.fines.values() if f["reason"] == "RIDER_NO_SHOW")
    code, body = t.cs("POST", f"/api/fines/{fine['id']}/waive")
    expect_eq(code, 200)
    expect_eq(body["data"]["settlement_status"], "WAIVED")
    code, body = t.admin("GET", f"/api/riders/{rider}")
    expect_eq(body["data"]["wallet_balance_cents"], 0)


@test("3.11 Fines")
def waive_already_waived_fails(t):
    rid = setup_active_restaurant(t)
    mid = add_menu_item(t, rid)
    cid = register_customer(t)
    rider = register_rider(t)
    go_online(t, rider)
    o = place_order(t, cid, rid, mid)
    t.request("POST", f"/api/orders/{o['id']}/accept", user_id=rid, role="Restaurant")
    t.request("POST", f"/api/orders/{o['id']}/start-preparing", user_id=rid, role="Restaurant")
    a = get_assignment_for_order(t, o["id"])
    t.request("POST", f"/api/assignments/{a['id']}/accept", user_id=rider, role="Rider")
    t.request("POST", f"/api/assignments/{a['id']}/cancel", user_id=rider, role="Rider")
    fine = next(f for f in t.store.fines.values() if f["reason"] == "RIDER_NO_SHOW")
    t.cs("POST", f"/api/fines/{fine['id']}/waive")
    code, body = t.cs("POST", f"/api/fines/{fine['id']}/waive")
    expect_eq(body["data"]["error_id"], "ERR_INVALID_STATE")


@test("3.11 Fines")
def fine_listing_scoped_by_role(t):
    # Two riders, each with a fine. r1 should see only theirs.
    rid = setup_active_restaurant(t)
    mid = add_menu_item(t, rid)
    cid = register_customer(t)
    r1 = register_rider(t, phone="a")
    r2 = register_rider(t, phone="b")
    for rdr in (r1, r2):
        go_online(t, rdr)
    # r1 takes order 1 and cancels (fine).
    o1 = place_order(t, cid, rid, mid)
    t.request("POST", f"/api/orders/{o1['id']}/accept", user_id=rid, role="Restaurant")
    t.request("POST", f"/api/orders/{o1['id']}/start-preparing", user_id=rid, role="Restaurant")
    a1 = get_assignment_for_order(t, o1["id"])
    # Make sure r1 is the one targeted.
    if a1["rider_id"] != r1:
        # Reject and dispatch again.
        t.request("POST", f"/api/assignments/{a1['id']}/reject", user_id=a1["rider_id"], role="Rider")
        a1 = get_assignment_for_order(t, o1["id"], status_in=("OFFERED",))
    if a1["rider_id"] != r1:
        # Force it by setting r2 offline.
        t.store.riders[r2]["status"] = "OFFLINE"
        t.request("POST", f"/api/assignments/{a1['id']}/reject", user_id=a1["rider_id"], role="Rider")
        a1 = get_assignment_for_order(t, o1["id"], status_in=("OFFERED",))
    t.request("POST", f"/api/assignments/{a1['id']}/accept", user_id=r1, role="Rider")
    t.request("POST", f"/api/assignments/{a1['id']}/cancel", user_id=r1, role="Rider")
    # r1 lists fines: 1 entry
    code, body = t.request("GET", "/api/fines", user_id=r1, role="Rider")
    expect_eq(body["meta"]["total_count"], 1)
    # r2 lists: 0 entries
    code, body = t.request("GET", "/api/fines", user_id=r2, role="Rider")
    expect_eq(body["meta"]["total_count"], 0)


# =============================================================== clock advance / dispatch sweep


@test("clock")
def clock_advance_sweeps_offer(t):
    rid = setup_active_restaurant(t)
    mid = add_menu_item(t, rid)
    cid = register_customer(t)
    r1 = register_rider(t, phone="a")
    r2 = register_rider(t, phone="b")
    go_online(t, r1)
    go_online(t, r2)
    o = place_order(t, cid, rid, mid)
    t.request("POST", f"/api/orders/{o['id']}/accept", user_id=rid, role="Restaurant")
    t.request("POST", f"/api/orders/{o['id']}/start-preparing", user_id=rid, role="Restaurant")
    a = get_assignment_for_order(t, o["id"], status_in=("OFFERED",))
    expect(a is not None)
    # Advance 60 seconds.
    t.admin("POST", "/api/_clock/advance", json_body={"seconds": 60})
    refreshed = t.store.assignments[a["id"]]
    expect_eq(refreshed["status"], "REJECTED")
    # A redispatch should have created another OFFERED for the order.
    others = [
        x for x in t.store.assignments.values()
        if x["order_id"] == o["id"] and x["status"] == "OFFERED"
    ]
    expect_eq(len(others), 1)


# =============================================================== Section 2.9 monetary


@test("2.9 Monetary")
def tiered_commission_rounding(t):
    from server.fees import tiered_commission_cents
    # 20001 cents subtotal: 20000*0.15=3000, 1*0.18=0.18 -> sum 3000.18 -> 3000
    expect_eq(tiered_commission_cents(20001), 3000)
    # 50001: 3000 + 30000*0.18=5400 + 1*0.22=0.22 -> 8400.22 -> 8400
    expect_eq(tiered_commission_cents(50001), 8400)
    # Boundary where half-up matters: subtotal that yields .5 -> rounds up.
    # 10 cents at 5% would yield 0.5; not applicable to tier rates 15/18/22. Just check 0 maps to 0.
    expect_eq(tiered_commission_cents(0), 0)


@test("2.9 Monetary")
def flat_commission_rounding_half_up(t):
    from server.fees import flat_commission_cents
    # 5 * 0.15 = 0.75 -> rounds up to 1
    expect_eq(flat_commission_cents(5, 0.15), 1)
    # 6 * 0.15 = 0.90 -> 1
    expect_eq(flat_commission_cents(6, 0.15), 1)


# =============================================================== gap-fill audit


@test("2.1 RBAC")
def rider_identity_mismatch_go_online(t):
    # A rider cannot go-online on another rider's record.
    r1 = register_rider(t, phone="px1")
    r2 = register_rider(t, phone="px2")
    code, b = t.request("POST", f"/api/riders/{r2}/go-online", user_id=r1, role="Rider")
    expect_err((code, b), "ERR_FORBIDDEN", http=403)


@test("2.2 Envelope")
def success_envelope_request_id_prefix_and_ts(t):
    import re
    code, b = t.admin("GET", "/api/restaurants")
    expect_eq(code, 200)
    rid = b["meta"]["api_request_id"]
    expect(rid.startswith("req_"), f"want req_ prefix, got {rid}")
    ts = b["meta"]["api_request_timestamp"]
    expect(re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$", ts), f"bad ts {ts}")


@test("2.3 Pagination")
def pagination_negative_offset_rejected(t):
    code, b = t.admin("GET", "/api/restaurants", params={"offset": "-1"})
    expect_err((code, b), "ERR_VALIDATION", http=422)


@test("2.3 Pagination")
def list_sorted_by_created_at_ascending(t):
    a = register_restaurant(t, name="A")
    # Advance the clock so b is strictly later than a.
    t.admin("POST", "/api/_clock/advance", json_body={"seconds": 1})
    b_id = register_restaurant(t, name="B")
    t.admin("POST", "/api/_clock/advance", json_body={"seconds": 1})
    c = register_restaurant(t, name="C")
    code, body = t.admin("GET", "/api/restaurants")
    ids = [r["id"] for r in body["data"]]
    expect_eq(ids[:3], [a, b_id, c], "expected ascending created_at order")


@test("2.4 Audit")
def fine_no_version_field(t):
    # Trigger a fine via no-show.
    rid = setup_active_restaurant(t)
    mid = add_menu_item(t, rid)
    cid = register_customer(t)
    rider = register_rider(t)
    go_online(t, rider)
    o = place_order(t, cid, rid, mid)
    t.request("POST", f"/api/orders/{o['id']}/accept", user_id=rid, role="Restaurant")
    t.request("POST", f"/api/orders/{o['id']}/start-preparing", user_id=rid, role="Restaurant")
    a = get_assignment_for_order(t, o["id"])
    t.request("POST", f"/api/assignments/{a['id']}/accept", user_id=rider, role="Rider")
    t.request("POST", f"/api/assignments/{a['id']}/cancel", user_id=rider, role="Rider")
    # Find the fine and ensure no version/updated_at.
    fine = next(iter(t.store.fines.values()))
    code, body = t.admin("GET", f"/api/fines/{fine['id']}")
    expect_eq(code, 200)
    expect("version" not in body["data"], "fine must not expose version")
    expect("updated_at" not in body["data"], "fine must not expose updated_at")


@test("2.6 Pipeline")
def pipeline_state_before_domain(t):
    # An expired-state precondition (state) fires before domain (e.g., menu-item availability).
    # Approve a non-PENDING restaurant: the state check (ERR_INVALID_STATE) should fire even
    # when other domain conditions would also apply.
    rid = register_restaurant(t)
    approve_restaurant(t, rid)
    code, b = t.admin("POST", f"/api/restaurants/{rid}/approve")
    expect_err((code, b), "ERR_INVALID_STATE", http=409)


@test("2.6 Pipeline")
def pipeline_fk_missing_returns_not_found(t):
    # Step 4: foreign-key id existence — missing customer_id/restaurant_id/menu_item_id → ERR_NOT_FOUND.
    rid = setup_active_restaurant(t)
    mid = add_menu_item(t, rid)
    cid = register_customer(t)
    # bogus restaurant_id
    code, b = t.request(
        "POST", "/api/orders", user_id=cid, role="Customer",
        json_body={"customer_id": cid, "restaurant_id": "no-such",
                   "items": [{"menu_item_id": mid, "quantity": 1}]})
    expect_err((code, b), "ERR_NOT_FOUND", http=404)
    # bogus menu_item_id
    code, b = t.request(
        "POST", "/api/orders", user_id=cid, role="Customer",
        json_body={"customer_id": cid, "restaurant_id": rid,
                   "items": [{"menu_item_id": "no-mi", "quantity": 1}]})
    expect_err((code, b), "ERR_NOT_FOUND", http=404)


@test("2.7 Nested")
def nested_left_to_right_validation(t):
    # /api/restaurants/{bogus}/menu-items resolves restaurant first → ERR_NOT_FOUND.
    code, b = t.admin(
        "POST", "/api/restaurants/no-such/menu-items",
        json_body={"name": "x", "price_cents": 100},
    )
    expect_err((code, b), "ERR_NOT_FOUND", http=404)


@test("3.1 Restaurant")
def restaurant_name_uniqueness_among_non_closed(t):
    register_restaurant(t, name="Dup")
    code, b = t.admin(
        "POST", "/api/restaurants",
        json_body={"name": "Dup", "address": "x", "lat": 1.0, "lng": 1.0},
    )
    expect_err((code, b), "ERR_VALIDATION", http=422)


@test("3.3 Rider")
def rider_phone_unique(t):
    register_rider(t, phone="+1-PP")
    code, b = t.admin("POST", "/api/riders", json_body={"name": "Z", "phone": "+1-PP"})
    expect_err((code, b), "ERR_VALIDATION", http=422)


@test("3.4 Placement")
def payment_status_authorized_at_placement(t):
    rid = setup_active_restaurant(t)
    mid = add_menu_item(t, rid)
    cid = register_customer(t)
    o = place_order(t, cid, rid, mid)
    expect_eq(o["payment_status"], "AUTHORIZED")


@test("3.4 Placement")
def menu_item_from_different_restaurant_unavailable(t):
    r1 = setup_active_restaurant(t, name="R1")
    r2 = setup_active_restaurant(t, name="R2", lat=41.0)
    m1 = add_menu_item(t, r1)  # belongs to r1
    cid = register_customer(t)
    code, b = t.request(
        "POST", "/api/orders", user_id=cid, role="Customer",
        json_body={"customer_id": cid, "restaurant_id": r2,
                   "items": [{"menu_item_id": m1, "quantity": 1}]})
    expect_err((code, b), "ERR_RESTAURANT_UNAVAILABLE", http=422)


@test("3.6 Dispatch")
def dispatch_empty_pool_returns_409(t):
    # No online riders → /dispatch must return 409 ERR_INVALID_STATE.
    rid = setup_active_restaurant(t)
    mid = add_menu_item(t, rid)
    cid = register_customer(t)
    o = place_order(t, cid, rid, mid)
    t.request("POST", f"/api/orders/{o['id']}/accept", user_id=rid, role="Restaurant")
    code, b = t.admin("POST", f"/api/orders/{o['id']}/dispatch")
    expect_err((code, b), "ERR_INVALID_STATE", http=409)


@test("3.7 Delivery")
def payment_status_captured_on_deliver(t):
    rid = setup_active_restaurant(t)
    mid = add_menu_item(t, rid)
    cid = register_customer(t)
    rider = register_rider(t)
    go_online(t, rider)
    o = place_order(t, cid, rid, mid)
    t.request("POST", f"/api/orders/{o['id']}/accept", user_id=rid, role="Restaurant")
    t.request("POST", f"/api/orders/{o['id']}/start-preparing", user_id=rid, role="Restaurant")
    a = get_assignment_for_order(t, o["id"])
    t.request("POST", f"/api/assignments/{a['id']}/accept", user_id=rider, role="Rider")
    t.request("POST", f"/api/orders/{o['id']}/ready", user_id=rid, role="Restaurant")
    t.request("POST", f"/api/assignments/{a['id']}/pickup", user_id=rider, role="Rider")
    t.request("POST", f"/api/assignments/{a['id']}/deliver", user_id=rider, role="Rider")
    order = t.store.orders[o["id"]]
    expect_eq(order["payment_status"], "CAPTURED")


@test("3.7 Delivery")
def rider_wallet_credited_with_delivery_fee(t):
    rid = setup_active_restaurant(t)
    mid = add_menu_item(t, rid)
    cid = register_customer(t)
    rider = register_rider(t)
    go_online(t, rider)
    o = place_order(t, cid, rid, mid)
    t.request("POST", f"/api/orders/{o['id']}/accept", user_id=rid, role="Restaurant")
    t.request("POST", f"/api/orders/{o['id']}/start-preparing", user_id=rid, role="Restaurant")
    a = get_assignment_for_order(t, o["id"])
    t.request("POST", f"/api/assignments/{a['id']}/accept", user_id=rider, role="Rider")
    t.request("POST", f"/api/orders/{o['id']}/ready", user_id=rid, role="Restaurant")
    t.request("POST", f"/api/assignments/{a['id']}/pickup", user_id=rider, role="Rider")
    t.request("POST", f"/api/assignments/{a['id']}/deliver", user_id=rider, role="Rider")
    order = t.store.orders[o["id"]]
    fee = order["final_delivery_fee_cents"]
    # On-time delivery → no fine, wallet = +fee.
    expect_eq(t.store.riders[rider]["wallet_balance_cents"], fee,
              "rider wallet should equal final_delivery_fee on on-time delivery")


@test("3.7 Delivery")
def route_group_completes_when_all_delivered(t):
    # Driver scenario: two orders from the same restaurant; second leg merges into a group.
    rid = setup_active_restaurant(t)
    mid = add_menu_item(t, rid)
    c1 = register_customer(t, phone="+1-A")
    c2 = register_customer(t, phone="+1-B")
    rider = register_rider(t)
    go_online(t, rider)
    o1 = place_order(t, c1, rid, mid)
    t.request("POST", f"/api/orders/{o1['id']}/accept", user_id=rid, role="Restaurant")
    t.request("POST", f"/api/orders/{o1['id']}/start-preparing", user_id=rid, role="Restaurant")
    a1 = get_assignment_for_order(t, o1["id"])
    t.request("POST", f"/api/assignments/{a1['id']}/accept", user_id=rider, role="Rider")
    o2 = place_order(t, c2, rid, mid)
    t.request("POST", f"/api/orders/{o2['id']}/accept", user_id=rid, role="Restaurant")
    t.request("POST", f"/api/orders/{o2['id']}/start-preparing", user_id=rid, role="Restaurant")
    a2 = get_assignment_for_order(t, o2["id"])
    t.request("POST", f"/api/assignments/{a2['id']}/accept", user_id=rider, role="Rider")
    # Both assignments should share a route group.
    a1 = t.store.assignments[a1["id"]]
    a2 = t.store.assignments[a2["id"]]
    expect(a1["route_group_id"] is not None, "first leg should anchor a route group on merge")
    expect_eq(a1["route_group_id"], a2["route_group_id"], "both legs share a route group")
    group_id = a1["route_group_id"]
    t.request("POST", f"/api/orders/{o1['id']}/ready", user_id=rid, role="Restaurant")
    t.request("POST", f"/api/orders/{o2['id']}/ready", user_id=rid, role="Restaurant")
    t.request("POST", f"/api/assignments/{a1['id']}/pickup", user_id=rider, role="Rider")
    t.request("POST", f"/api/assignments/{a1['id']}/deliver", user_id=rider, role="Rider")
    # Group still ACTIVE while a2 not yet delivered.
    expect_eq(t.store.route_groups[group_id]["status"], "ACTIVE")
    t.request("POST", f"/api/assignments/{a2['id']}/pickup", user_id=rider, role="Rider")
    t.request("POST", f"/api/assignments/{a2['id']}/deliver", user_id=rider, role="Rider")
    expect_eq(t.store.route_groups[group_id]["status"], "COMPLETED")


@test("3.9 Returns")
def reject_reverts_order_to_delivered(t):
    rid = setup_active_restaurant(t)
    mid = add_menu_item(t, rid)
    cid = register_customer(t)
    rider = register_rider(t)
    go_online(t, rider)
    o = place_order(t, cid, rid, mid)
    t.request("POST", f"/api/orders/{o['id']}/accept", user_id=rid, role="Restaurant")
    t.request("POST", f"/api/orders/{o['id']}/start-preparing", user_id=rid, role="Restaurant")
    a = get_assignment_for_order(t, o["id"])
    t.request("POST", f"/api/assignments/{a['id']}/accept", user_id=rider, role="Rider")
    t.request("POST", f"/api/orders/{o['id']}/ready", user_id=rid, role="Restaurant")
    t.request("POST", f"/api/assignments/{a['id']}/pickup", user_id=rider, role="Rider")
    t.request("POST", f"/api/assignments/{a['id']}/deliver", user_id=rider, role="Rider")
    code, b = t.request(
        "POST", f"/api/orders/{o['id']}/returns", user_id=cid, role="Customer",
        json_body={"reason": "WRONG_ITEM", "requested_refund_cents": 100},
    )
    expect_eq(code, 201, b)
    ret_id = b["data"]["id"]
    code, b = t.cs("POST", f"/api/returns/{ret_id}/reject")
    expect_eq(code, 200, b)
    expect_eq(t.store.orders[o["id"]]["status"], "DELIVERED")


@test("3.9 Returns")
def reopen_only_from_escalated(t):
    # Open a non-escalated return and confirm reopen rejects with INVALID_STATE.
    rid = setup_active_restaurant(t)
    mid = add_menu_item(t, rid)
    cid = register_customer(t)
    rider = register_rider(t)
    go_online(t, rider)
    o = place_order(t, cid, rid, mid)
    t.request("POST", f"/api/orders/{o['id']}/accept", user_id=rid, role="Restaurant")
    t.request("POST", f"/api/orders/{o['id']}/start-preparing", user_id=rid, role="Restaurant")
    a = get_assignment_for_order(t, o["id"])
    t.request("POST", f"/api/assignments/{a['id']}/accept", user_id=rider, role="Rider")
    t.request("POST", f"/api/orders/{o['id']}/ready", user_id=rid, role="Restaurant")
    t.request("POST", f"/api/assignments/{a['id']}/pickup", user_id=rider, role="Rider")
    t.request("POST", f"/api/assignments/{a['id']}/deliver", user_id=rider, role="Rider")
    code, b = t.request(
        "POST", f"/api/orders/{o['id']}/returns", user_id=cid, role="Customer",
        json_body={"reason": "OTHER", "requested_refund_cents": 200},
    )
    expect_eq(code, 201, b)
    ret_id = b["data"]["id"]
    code, b = t.cs("POST", f"/api/returns/{ret_id}/reopen")
    expect_err((code, b), "ERR_INVALID_STATE", http=409)


@test("3.9 Returns")
def approve_refund_below_one_invalid(t):
    rid = setup_active_restaurant(t)
    mid = add_menu_item(t, rid)
    cid = register_customer(t)
    rider = register_rider(t)
    go_online(t, rider)
    o = place_order(t, cid, rid, mid)
    t.request("POST", f"/api/orders/{o['id']}/accept", user_id=rid, role="Restaurant")
    t.request("POST", f"/api/orders/{o['id']}/start-preparing", user_id=rid, role="Restaurant")
    a = get_assignment_for_order(t, o["id"])
    t.request("POST", f"/api/assignments/{a['id']}/accept", user_id=rider, role="Rider")
    t.request("POST", f"/api/orders/{o['id']}/ready", user_id=rid, role="Restaurant")
    t.request("POST", f"/api/assignments/{a['id']}/pickup", user_id=rider, role="Rider")
    t.request("POST", f"/api/assignments/{a['id']}/deliver", user_id=rider, role="Rider")
    code, b = t.request(
        "POST", f"/api/orders/{o['id']}/returns", user_id=cid, role="Customer",
        json_body={"reason": "OTHER", "requested_refund_cents": 200},
    )
    ret_id = b["data"]["id"]
    code, b = t.cs("POST", f"/api/returns/{ret_id}/approve",
                   json_body={"approved_refund_cents": 0})
    expect_err((code, b), "ERR_REFUND_AMOUNT_INVALID", http=422)


@test("3.10 WorkOrder")
def resolve_requires_assigned_cs(t):
    code, b = t.request(
        "POST", "/api/work-orders", user_id="c-unknown", role="CustomerService",
        json_body={"category": "OTHER"},
    )
    expect_eq(code, 201)
    wid = b["data"]["id"]
    # Not assigned yet — resolve must fail with INVALID_STATE because status is OPEN.
    code, b = t.cs("POST", f"/api/work-orders/{wid}/resolve",
                   json_body={"resolution_notes": "ok"})
    expect_err((code, b), "ERR_INVALID_STATE", http=409)


@test("3.11 Fines")
def waive_restaurant_fine_restores_settlement(t):
    # No endpoint creates a RESTAURANT_STOCKOUT fine in the modelled surface,
    # so we set up the post-fine state directly and verify only the waive arm.
    from server.services.delivery import _create_fine
    rid = setup_active_restaurant(t)
    rest = t.store.restaurants[rid]
    rest["pending_settlement_cents"] = 500
    # Simulate the debit that the (hypothetical) stockout flow would apply.
    rest["pending_settlement_cents"] -= 200
    f = _create_fine(t.store, subject_type="RESTAURANT", subject_id=rid,
                     reason="RESTAURANT_STOCKOUT", amount_cents=200, order_id=None)
    expect_eq(t.store.restaurants[rid]["pending_settlement_cents"], 300)
    code, b = t.cs("POST", f"/api/fines/{f['id']}/waive")
    expect_eq(code, 200, b)
    expect_eq(t.store.restaurants[rid]["pending_settlement_cents"], 500,
              "waive should reverse the restaurant settlement deduction")


@test("3.11 Fines")
def waive_customer_fine_restores_credit(t):
    from server.services.delivery import _create_fine
    cid = register_customer(t)
    t.store.customers[cid]["credit_balance_cents"] = 1000
    # Simulate the debit that the abusive-return flow applies in returns_.py.
    t.store.customers[cid]["credit_balance_cents"] -= 200
    f = _create_fine(t.store, subject_type="CUSTOMER", subject_id=cid,
                     reason="ABUSIVE_RETURN", amount_cents=200, order_id=None)
    expect_eq(t.store.customers[cid]["credit_balance_cents"], 800)
    code, b = t.cs("POST", f"/api/fines/{f['id']}/waive")
    expect_eq(code, 200, b)
    expect_eq(t.store.customers[cid]["credit_balance_cents"], 1000,
              "waive should restore the customer credit deduction")


# =============================================================== runner


if __name__ == "__main__":
    import sys

    sys.exit(run_all())
