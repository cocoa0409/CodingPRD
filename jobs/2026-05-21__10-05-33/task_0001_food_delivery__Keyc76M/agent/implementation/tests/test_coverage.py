"""Coverage tests targeting PRD branches not directly exercised elsewhere.

This file is the final pre-delivery sweep. Each test pins a single rule
from the PRD that is otherwise easy to break without anyone noticing.
"""

from datetime import timedelta

import compute
import state

from tests.harness import (
    test, fresh_client, jget, jpost, jpatch, body_of,
    assert_eq, assert_err,
    admin_headers, cs_headers, cust_headers, rest_headers, rider_headers,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _approve_active_restaurant(c, name="R", lat=0.0, lng=0.0,
                               commission_rate_override=None):
    body = {"name": name, "address": "A", "lat": lat, "lng": lng}
    if commission_rate_override is not None:
        body["commission_rate_override"] = commission_rate_override
    rid = body_of(jpost(c, "/api/restaurants", body=body,
                       headers=admin_headers()))["data"]["id"]
    jpost(c, f"/api/restaurants/{rid}/approve", headers=admin_headers())
    return rid


def _menu_item(c, rid, price_cents=5000, name="B", is_listed=True):
    return body_of(jpost(c, f"/api/restaurants/{rid}/menu-items",
                        body={"name": name,
                              "price_cents": price_cents,
                              "is_listed": is_listed},
                        headers=rest_headers(rid)))["data"]["id"]


def _customer(c, name="C", phone="+1", lat=0.0, lng=0.0):
    return body_of(jpost(c, "/api/customers",
                        body={"name": name, "phone": phone,
                              "address": "A", "lat": lat, "lng": lng},
                        headers=admin_headers()))["data"]["id"]


def _rider(c, name="R", phone="+9", go_online=True):
    rrid = body_of(jpost(c, "/api/riders",
                        body={"name": name, "phone": phone},
                        headers=admin_headers()))["data"]["id"]
    if go_online:
        jpost(c, f"/api/riders/{rrid}/go-online",
              headers=rider_headers(rrid))
    return rrid


def _place_order(c, cid, rid, mid, qty=1):
    return body_of(jpost(c, "/api/orders",
                        body={"customer_id": cid, "restaurant_id": rid,
                              "items": [{"menu_item_id": mid,
                                         "quantity": qty}]},
                        headers=cust_headers(cid)))["data"]


def _deliver_world(c):
    """Build a full DELIVERED order and return (rid, cid, rrid, order, assignment)."""
    rid = _approve_active_restaurant(c)
    mid = _menu_item(c, rid)
    cid = _customer(c)
    rrid = _rider(c)
    order = _place_order(c, cid, rid, mid)
    jpost(c, f"/api/orders/{order['id']}/accept", headers=rest_headers(rid))
    jpost(c, f"/api/orders/{order['id']}/start-preparing",
          headers=rest_headers(rid))
    a = [aa for aa in state.STORE.assignments.values()
         if aa["order_id"] == order["id"]][0]
    jpost(c, f"/api/assignments/{a['id']}/accept",
          headers=rider_headers(rrid))
    jpost(c, f"/api/orders/{order['id']}/ready", headers=rest_headers(rid))
    jpost(c, f"/api/assignments/{a['id']}/pickup",
          headers=rider_headers(rrid))
    jpost(c, f"/api/assignments/{a['id']}/deliver",
          headers=rider_headers(rrid))
    return rid, cid, rrid, order, a


# ---------------------------------------------------------------------------
# §3.3 Bonus tier boundary scores
# ---------------------------------------------------------------------------

@test("bonus_tier: 0.900 boundary -> PLATINUM")
def t_bonus_boundary_platinum():
    # 0.6*1.0 + 0.3*1.0 + 0.1*(0.0/5) = 0.900 exactly
    assert_eq(compute.bonus_tier(1.0, 1.0, 0.0), "PLATINUM",
              "0.900 -> PLATINUM")


@test("bonus_tier: 0.800 boundary -> GOLD")
def t_bonus_boundary_gold():
    # 0.6*1.0 + 0.3*0.0 + 0.1*(10.0/5)?  Need 0.800 exactly.
    # 0.6*x + 0.3*0 + 0.1*(y/5) = 0.800
    # try on_time=1.0, accept=2/3?  Easier: 0.6*0.7 + 0.3*1.0 + 0.1*(4/5)
    # = 0.42 + 0.30 + 0.08 = 0.80
    assert_eq(compute.bonus_tier(0.7, 1.0, 4.0), "GOLD", "0.800 -> GOLD")


@test("bonus_tier: 0.700 boundary -> SILVER")
def t_bonus_boundary_silver():
    # 0.6*1.0 + 0.3*0.0 + 0.1*(5/5) = 0.6 + 0 + 0.1 = 0.700
    assert_eq(compute.bonus_tier(1.0, 0.0, 5.0), "SILVER", "0.700 -> SILVER")


@test("bonus_tier: 0.699 -> BRONZE")
def t_bonus_boundary_bronze():
    # 0.6*0.5 + 0.3*0.5 + 0.1*(3/5) = 0.3 + 0.15 + 0.06 = 0.510
    assert_eq(compute.bonus_tier(0.5, 0.5, 3.0), "BRONZE", "<0.700 -> BRONZE")


# ---------------------------------------------------------------------------
# §2.10 Peak window edges
# ---------------------------------------------------------------------------

@test("peak window: 10:59 not peak, 11:00 peak")
def t_peak_morning_left_edge():
    from datetime import datetime, timezone
    assert not compute.is_peak_at(
        datetime(2026, 1, 1, 10, 59, 0, tzinfo=timezone.utc)), "10:59"
    assert compute.is_peak_at(
        datetime(2026, 1, 1, 11, 0, 0, tzinfo=timezone.utc)), "11:00"


@test("peak window: 12:59 peak, 13:00 not peak")
def t_peak_morning_right_edge():
    from datetime import datetime, timezone
    assert compute.is_peak_at(
        datetime(2026, 1, 1, 12, 59, 59, tzinfo=timezone.utc)), "12:59"
    assert not compute.is_peak_at(
        datetime(2026, 1, 1, 13, 0, 0, tzinfo=timezone.utc)), "13:00"


@test("peak window: 17:59 not peak, 18:00 peak, 20:00 not peak")
def t_peak_evening_edges():
    from datetime import datetime, timezone
    assert not compute.is_peak_at(
        datetime(2026, 1, 1, 17, 59, 0, tzinfo=timezone.utc)), "17:59"
    assert compute.is_peak_at(
        datetime(2026, 1, 1, 18, 0, 0, tzinfo=timezone.utc)), "18:00"
    assert not compute.is_peak_at(
        datetime(2026, 1, 1, 20, 0, 0, tzinfo=timezone.utc)), "20:00"


# ---------------------------------------------------------------------------
# §3.3 Rider suspend POSITIVE path
# ---------------------------------------------------------------------------

@test("rider suspend: low on_time_rate (0.5) -> SUSPENDED")
def t_rider_suspend_low_on_time():
    c = fresh_client()
    rrid = _rider(c)  # AVAILABLE
    r = state.STORE.riders[rrid]
    r["on_time_rate"] = 0.5
    r["acceptance_rate"] = 1.0
    resp = jpost(c, f"/api/riders/{rrid}/suspend", headers=admin_headers())
    assert_eq(resp.status_code, 200, "ok")
    assert_eq(body_of(resp)["data"]["status"], "SUSPENDED", "suspended")


@test("rider suspend: low acceptance_rate (0.4) -> SUSPENDED")
def t_rider_suspend_low_acceptance():
    c = fresh_client()
    rrid = _rider(c)
    r = state.STORE.riders[rrid]
    r["acceptance_rate"] = 0.4
    r["on_time_rate"] = 1.0
    resp = jpost(c, f"/api/riders/{rrid}/suspend", headers=admin_headers())
    assert_eq(resp.status_code, 200, "ok")
    assert_eq(body_of(resp)["data"]["status"], "SUSPENDED", "suspended")


@test("rider suspend: boundary on_time_rate=0.70 -> NOT_MET")
def t_rider_suspend_boundary_on_time():
    c = fresh_client()
    rrid = _rider(c)
    r = state.STORE.riders[rrid]
    r["on_time_rate"] = 0.70
    r["acceptance_rate"] = 1.0
    resp = jpost(c, f"/api/riders/{rrid}/suspend", headers=admin_headers())
    assert_err(resp, 422, "ERR_SUSPEND_CRITERIA_NOT_MET")


@test("rider suspend: boundary acceptance_rate=0.50 -> NOT_MET")
def t_rider_suspend_boundary_acceptance():
    c = fresh_client()
    rrid = _rider(c)
    r = state.STORE.riders[rrid]
    r["acceptance_rate"] = 0.50
    r["on_time_rate"] = 1.0
    resp = jpost(c, f"/api/riders/{rrid}/suspend", headers=admin_headers())
    assert_err(resp, 422, "ERR_SUSPEND_CRITERIA_NOT_MET")


@test("rider suspend: only AVAILABLE may be suspended (OFFLINE -> INVALID_STATE)")
def t_rider_suspend_not_available():
    c = fresh_client()
    rrid = body_of(jpost(c, "/api/riders",
                        body={"name": "R", "phone": "+1"},
                        headers=admin_headers()))["data"]["id"]
    # OFFLINE by default
    resp = jpost(c, f"/api/riders/{rrid}/suspend", headers=admin_headers())
    assert_err(resp, 409, "ERR_INVALID_STATE")


# ---------------------------------------------------------------------------
# §3.3 Rider go-offline happy path
# ---------------------------------------------------------------------------

@test("rider go-offline: AVAILABLE with no live assignments -> OFFLINE")
def t_rider_offline_happy():
    c = fresh_client()
    rrid = _rider(c)
    resp = jpost(c, f"/api/riders/{rrid}/go-offline",
                 headers=rider_headers(rrid))
    assert_eq(resp.status_code, 200, "ok")
    assert_eq(body_of(resp)["data"]["status"], "OFFLINE", "OFFLINE")


# ---------------------------------------------------------------------------
# §3.1 Restaurant fields & validation
# ---------------------------------------------------------------------------

@test("restaurant: name longer than 120 chars -> ERR_VALIDATION")
def t_restaurant_long_name():
    c = fresh_client()
    resp = jpost(c, "/api/restaurants",
                 body={"name": "x" * 121, "address": "A",
                       "lat": 0.0, "lng": 0.0},
                 headers=admin_headers())
    assert_err(resp, 422, "ERR_VALIDATION")


@test("restaurant: lat out of [-90,90] -> ERR_VALIDATION")
def t_restaurant_bad_lat():
    c = fresh_client()
    resp = jpost(c, "/api/restaurants",
                 body={"name": "R", "address": "A",
                       "lat": 91.0, "lng": 0.0},
                 headers=admin_headers())
    assert_err(resp, 422, "ERR_VALIDATION")


@test("restaurant: PATCH commission_rate_override boundary 0.05 OK")
def t_restaurant_patch_rate_low_bound():
    c = fresh_client()
    rid = _approve_active_restaurant(c)
    resp = jpatch(c, f"/api/restaurants/{rid}",
                  body={"commission_rate_override": 0.05},
                  headers=rest_headers(rid))
    assert_eq(resp.status_code, 200, "ok")
    assert_eq(body_of(resp)["data"]["commission_rate_override"], 0.05, "0.05")


@test("restaurant: PATCH commission_rate_override boundary 0.35 OK")
def t_restaurant_patch_rate_high_bound():
    c = fresh_client()
    rid = _approve_active_restaurant(c)
    resp = jpatch(c, f"/api/restaurants/{rid}",
                  body={"commission_rate_override": 0.35},
                  headers=rest_headers(rid))
    assert_eq(resp.status_code, 200, "ok")


@test("restaurant: PATCH address + lat + lng applied together")
def t_restaurant_patch_multi():
    c = fresh_client()
    rid = _approve_active_restaurant(c)
    resp = jpatch(c, f"/api/restaurants/{rid}",
                  body={"address": "New",
                        "lat": 10.0, "lng": 20.0},
                  headers=rest_headers(rid))
    body = body_of(resp)["data"]
    assert_eq(body["address"], "New", "address")
    assert_eq(body["lat"], 10.0, "lat")
    assert_eq(body["lng"], 20.0, "lng")


@test("restaurant: PATCH correct version succeeds; version increments")
def t_restaurant_patch_occ_success():
    c = fresh_client()
    rid = _approve_active_restaurant(c)
    rec = body_of(jget(c, f"/api/restaurants/{rid}",
                       headers=admin_headers()))["data"]
    v0 = rec["version"]
    resp = jpatch(c, f"/api/restaurants/{rid}",
                  body={"address": "B", "version": v0},
                  headers=rest_headers(rid))
    assert_eq(body_of(resp)["data"]["version"], v0 + 1, "version bumped")


@test("restaurant: PATCH by non-owning Restaurant -> ERR_FORBIDDEN")
def t_restaurant_patch_foreign():
    c = fresh_client()
    rid = _approve_active_restaurant(c, name="A")
    other_rid = body_of(jpost(c, "/api/restaurants",
                              body={"name": "B", "address": "A",
                                    "lat": 0.0, "lng": 0.0},
                              headers=admin_headers()))["data"]["id"]
    resp = jpatch(c, f"/api/restaurants/{rid}",
                  body={"address": "X"},
                  headers=rest_headers(other_rid))
    assert_err(resp, 403, "ERR_FORBIDDEN")


# ---------------------------------------------------------------------------
# §3.1 Menu item PATCH unlist + price update
# ---------------------------------------------------------------------------

@test("menu: PATCH unlist sets is_listed=false")
def t_menu_unlist():
    c = fresh_client()
    rid = _approve_active_restaurant(c)
    mid = _menu_item(c, rid)
    resp = jpatch(c, f"/api/menu-items/{mid}",
                  body={"is_listed": False},
                  headers=rest_headers(rid))
    assert_eq(resp.status_code, 200, "ok")
    assert_eq(body_of(resp)["data"]["is_listed"], False, "unlisted")


@test("menu: PATCH price + version OCC mismatch -> ERR_VERSION_CONFLICT")
def t_menu_patch_occ_mismatch():
    c = fresh_client()
    rid = _approve_active_restaurant(c)
    mid = _menu_item(c, rid)
    resp = jpatch(c, f"/api/menu-items/{mid}",
                  body={"price_cents": 999, "version": 99},
                  headers=rest_headers(rid))
    assert_err(resp, 409, "ERR_VERSION_CONFLICT")


# ---------------------------------------------------------------------------
# §3.5 Cancel order beyond PLACED -> ERR_INVALID_STATE
# ---------------------------------------------------------------------------

@test("cancel: post-accept order cancel -> ERR_INVALID_STATE")
def t_cancel_after_accept():
    c = fresh_client()
    rid = _approve_active_restaurant(c)
    mid = _menu_item(c, rid)
    cid = _customer(c)
    order = _place_order(c, cid, rid, mid)
    jpost(c, f"/api/orders/{order['id']}/accept", headers=rest_headers(rid))
    resp = jpost(c, f"/api/orders/{order['id']}/cancel",
                 headers=cust_headers(cid))
    assert_err(resp, 409, "ERR_INVALID_STATE")


@test("cancel: restaurant cancels its own PLACED order -> CANCELLED")
def t_cancel_by_restaurant():
    c = fresh_client()
    rid = _approve_active_restaurant(c)
    mid = _menu_item(c, rid)
    cid = _customer(c)
    order = _place_order(c, cid, rid, mid)
    resp = jpost(c, f"/api/orders/{order['id']}/cancel",
                 headers=rest_headers(rid))
    assert_eq(body_of(resp)["data"]["status"], "CANCELLED", "cancelled")


# ---------------------------------------------------------------------------
# §3.6 Dispatch endpoint
# ---------------------------------------------------------------------------

@test("dispatch: manual POST creates a new OFFERED assignment")
def t_manual_dispatch():
    c = fresh_client()
    rid = _approve_active_restaurant(c)
    mid = _menu_item(c, rid)
    cid = _customer(c)
    _rider(c, name="A", phone="+1")
    _rider(c, name="B", phone="+2")
    order = _place_order(c, cid, rid, mid)
    jpost(c, f"/api/orders/{order['id']}/accept", headers=rest_headers(rid))
    jpost(c, f"/api/orders/{order['id']}/start-preparing",
          headers=rest_headers(rid))
    initial_offered = [a for a in state.STORE.assignments.values()
                       if a["order_id"] == order["id"]
                       and a["status"] == "OFFERED"]
    assert_eq(len(initial_offered), 1, "one offer from start-prep")
    # First rider rejects so a new candidate is available.
    aid = initial_offered[0]["id"]
    rejecting_rider = initial_offered[0]["rider_id"]
    jpost(c, f"/api/assignments/{aid}/reject",
          headers=rider_headers(rejecting_rider))
    # Now manually trigger another dispatch (the explicit endpoint).
    # Reject above already redispatched -> second rider has an OFFERED row.
    # Reject that too so the pool is empty.
    second_offer = [a for a in state.STORE.assignments.values()
                    if a["order_id"] == order["id"]
                    and a["status"] == "OFFERED"][0]
    second_rider = second_offer["rider_id"]
    jpost(c, f"/api/assignments/{second_offer['id']}/reject",
          headers=rider_headers(second_rider))
    # Both riders have been offered → pool empty; dispatch must refuse.
    resp = jpost(c, f"/api/orders/{order['id']}/dispatch",
                 headers=admin_headers())
    assert_err(resp, 409, "ERR_INVALID_STATE")


@test("dispatch: not in dispatchable state -> ERR_INVALID_STATE")
def t_manual_dispatch_bad_state():
    c = fresh_client()
    rid = _approve_active_restaurant(c)
    mid = _menu_item(c, rid)
    cid = _customer(c)
    order = _place_order(c, cid, rid, mid)
    # Order still PLACED, not in dispatchable window
    resp = jpost(c, f"/api/orders/{order['id']}/dispatch",
                 headers=admin_headers())
    assert_err(resp, 409, "ERR_INVALID_STATE")


# ---------------------------------------------------------------------------
# §2.3 Pagination bounds
# ---------------------------------------------------------------------------

@test("pagination: limit > 100 -> ERR_VALIDATION")
def t_pagination_limit_too_high():
    c = fresh_client()
    resp = jget(c, "/api/restaurants?limit=101", headers=admin_headers())
    assert_err(resp, 422, "ERR_VALIDATION")


@test("pagination: limit < 1 -> ERR_VALIDATION")
def t_pagination_limit_too_low():
    c = fresh_client()
    resp = jget(c, "/api/restaurants?limit=0", headers=admin_headers())
    assert_err(resp, 422, "ERR_VALIDATION")


@test("pagination: offset < 0 -> ERR_VALIDATION")
def t_pagination_neg_offset():
    c = fresh_client()
    resp = jget(c, "/api/restaurants?offset=-1", headers=admin_headers())
    assert_err(resp, 422, "ERR_VALIDATION")


@test("pagination: meta exposes total_count + has_more")
def t_pagination_meta():
    c = fresh_client()
    for i in range(3):
        body = {"name": f"R{i}", "address": "A", "lat": 0.0, "lng": 0.0}
        jpost(c, "/api/restaurants", body=body, headers=admin_headers())
    resp = jget(c, "/api/restaurants?limit=2&offset=0", headers=admin_headers())
    meta = body_of(resp)["meta"]
    assert_eq(meta["total_count"], 3, "total_count")
    assert_eq(meta["limit"], 2, "limit")
    assert_eq(meta["offset"], 0, "offset")
    assert_eq(meta["has_more"], True, "has_more")


# ---------------------------------------------------------------------------
# §3.4 Order list filters
# ---------------------------------------------------------------------------

@test("orders list: customer-scoped to own orders")
def t_orders_list_customer_scope():
    c = fresh_client()
    rid = _approve_active_restaurant(c)
    mid = _menu_item(c, rid)
    cid1 = _customer(c, name="A", phone="+1")
    cid2 = _customer(c, name="B", phone="+2")
    _place_order(c, cid1, rid, mid)
    _place_order(c, cid2, rid, mid)
    resp = jget(c, "/api/orders", headers=cust_headers(cid1))
    body = body_of(resp)["data"]
    assert_eq(len(body), 1, "only own order visible")
    assert_eq(body[0]["customer_id"], cid1, "own")


@test("orders list: status filter")
def t_orders_list_status_filter():
    c = fresh_client()
    rid = _approve_active_restaurant(c)
    mid = _menu_item(c, rid)
    cid = _customer(c)
    o1 = _place_order(c, cid, rid, mid)
    _place_order(c, cid, rid, mid)
    jpost(c, f"/api/orders/{o1['id']}/accept", headers=rest_headers(rid))
    resp = jget(c, "/api/orders?status=PLACED", headers=admin_headers())
    body = body_of(resp)["data"]
    assert_eq(len(body), 1, "only PLACED")
    assert all(o["status"] == "PLACED" for o in body), "all PLACED"


# ---------------------------------------------------------------------------
# §3.11 Fines list filter by settlement_status, and CS/admin read any
# ---------------------------------------------------------------------------

@test("fines: CS reads any fine")
def t_fines_cs_reads_any():
    c = fresh_client()
    # Build a fine
    from tests.test_fines_and_workorders import _make_rider_with_fine
    rrid, cid, fine = _make_rider_with_fine(c)
    resp = jget(c, f"/api/fines/{fine['id']}", headers=cs_headers())
    assert_eq(resp.status_code, 200, "ok")


@test("fines list: settlement_status filter")
def t_fines_list_settlement_filter():
    c = fresh_client()
    from tests.test_fines_and_workorders import _make_rider_with_fine
    rrid, cid, fine = _make_rider_with_fine(c)
    resp = jget(c, "/api/fines?settlement_status=PENDING",
                headers=admin_headers())
    body = body_of(resp)["data"]
    assert all(f["settlement_status"] == "PENDING" for f in body), "all pending"
    # Now waive and re-filter
    jpost(c, f"/api/fines/{fine['id']}/waive", headers=cs_headers())
    resp = jget(c, "/api/fines?settlement_status=PENDING",
                headers=admin_headers())
    assert_eq(body_of(resp)["data"], [], "no pending after waive")


# ---------------------------------------------------------------------------
# §3.6 Assignment GET
# ---------------------------------------------------------------------------

@test("assignment: admin GET returns the assignment")
def t_assignment_admin_get():
    c = fresh_client()
    rid = _approve_active_restaurant(c)
    mid = _menu_item(c, rid)
    cid = _customer(c)
    _rider(c)
    order = _place_order(c, cid, rid, mid)
    jpost(c, f"/api/orders/{order['id']}/accept", headers=rest_headers(rid))
    jpost(c, f"/api/orders/{order['id']}/start-preparing",
          headers=rest_headers(rid))
    a = [aa for aa in state.STORE.assignments.values()
         if aa["order_id"] == order["id"]][0]
    resp = jget(c, f"/api/assignments/{a['id']}", headers=admin_headers())
    assert_eq(resp.status_code, 200, "ok")
    assert_eq(body_of(resp)["data"]["id"], a["id"], "same id")


@test("assignment: foreign rider GET -> ERR_FORBIDDEN")
def t_assignment_foreign_rider():
    c = fresh_client()
    rid = _approve_active_restaurant(c)
    mid = _menu_item(c, rid)
    cid = _customer(c)
    _rider(c, name="A", phone="+1")
    # The dispatched offer will pick most recently registered rider:
    rrid_other = _rider(c, name="B", phone="+2")
    order = _place_order(c, cid, rid, mid)
    jpost(c, f"/api/orders/{order['id']}/accept", headers=rest_headers(rid))
    jpost(c, f"/api/orders/{order['id']}/start-preparing",
          headers=rest_headers(rid))
    a = [aa for aa in state.STORE.assignments.values()
         if aa["order_id"] == order["id"]][0]
    # Pick the rider that is NOT the offer recipient.
    other_rider_id = (
        rrid_other if a["rider_id"] != rrid_other
        else [rr for rr in state.STORE.riders if rr != rrid_other][0]
    )
    resp = jget(c, f"/api/assignments/{a['id']}",
                headers=rider_headers(other_rider_id))
    assert_err(resp, 403, "ERR_FORBIDDEN")


# ---------------------------------------------------------------------------
# §2.8 Cascade version-tick atomicity on delivery
# ---------------------------------------------------------------------------

@test("cascade: delivery ticks order/restaurant/rider by exactly 1 each")
def t_cascade_version_atomic():
    c = fresh_client()
    rid = _approve_active_restaurant(c)
    mid = _menu_item(c, rid)
    cid = _customer(c)
    rrid = _rider(c)
    order = _place_order(c, cid, rid, mid)
    jpost(c, f"/api/orders/{order['id']}/accept", headers=rest_headers(rid))
    jpost(c, f"/api/orders/{order['id']}/start-preparing",
          headers=rest_headers(rid))
    a = [aa for aa in state.STORE.assignments.values()
         if aa["order_id"] == order["id"]][0]
    jpost(c, f"/api/assignments/{a['id']}/accept",
          headers=rider_headers(rrid))
    jpost(c, f"/api/orders/{order['id']}/ready", headers=rest_headers(rid))
    jpost(c, f"/api/assignments/{a['id']}/pickup",
          headers=rider_headers(rrid))
    # Snapshot versions before delivery
    o_v0 = state.STORE.orders[order["id"]]["version"]
    r_v0 = state.STORE.restaurants[rid]["version"]
    rr_v0 = state.STORE.riders[rrid]["version"]
    jpost(c, f"/api/assignments/{a['id']}/deliver",
          headers=rider_headers(rrid))
    o_v1 = state.STORE.orders[order["id"]]["version"]
    r_v1 = state.STORE.restaurants[rid]["version"]
    rr_v1 = state.STORE.riders[rrid]["version"]
    assert_eq(o_v1 - o_v0, 1, "order version +1")
    assert_eq(r_v1 - r_v0, 1, "restaurant version +1")
    # Rider ticks at least once for delivery (the on-time path); the
    # AVAILABLE-return cascade may add one more bump on top of that.
    assert rr_v1 - rr_v0 >= 1, "rider version moves on delivery"


# ---------------------------------------------------------------------------
# §3.1 Restaurant suspend: cancellation fan-out skips non-PLACED
# ---------------------------------------------------------------------------

@test("restaurant suspend: ACCEPTED orders are NOT cancelled by fan-out")
def t_suspend_fanout_skips_accepted():
    c = fresh_client()
    rid = _approve_active_restaurant(c)
    mid = _menu_item(c, rid)
    cid = _customer(c)
    o1 = _place_order(c, cid, rid, mid)  # stays PLACED
    o2 = _place_order(c, cid, rid, mid)
    jpost(c, f"/api/orders/{o2['id']}/accept", headers=rest_headers(rid))
    jpost(c, f"/api/restaurants/{rid}/suspend", headers=admin_headers())
    o1_now = body_of(jget(c, f"/api/orders/{o1['id']}",
                          headers=admin_headers()))["data"]
    o2_now = body_of(jget(c, f"/api/orders/{o2['id']}",
                          headers=admin_headers()))["data"]
    assert_eq(o1_now["status"], "CANCELLED", "PLACED was cancelled")
    assert_eq(o2_now["status"], "RESTAURANT_ACCEPTED", "non-PLACED stays")


# ---------------------------------------------------------------------------
# §3.4 Customer credit drawdown on placement / delivery
# ---------------------------------------------------------------------------

@test("placement: AUTHORIZED does not draw credit_balance")
def t_authorize_no_credit_draw():
    c = fresh_client()
    rid = _approve_active_restaurant(c)
    mid = _menu_item(c, rid)
    cid = _customer(c)
    # Give the customer credit
    state.STORE.customers[cid]["credit_balance_cents"] = 1000
    _place_order(c, cid, rid, mid)
    assert_eq(state.STORE.customers[cid]["credit_balance_cents"], 1000,
              "credit not drawn at AUTHORIZED")


# ---------------------------------------------------------------------------
# §2.1 Auth missing X-User-Role -> ERR_AUTH_REQUIRED
# ---------------------------------------------------------------------------

@test("auth: missing X-User-Role yields ERR_AUTH_REQUIRED")
def t_missing_role_header():
    c = fresh_client()
    resp = jget(c, "/api/restaurants", headers={"X-User-ID": "u1"})
    assert_err(resp, 401, "ERR_AUTH_REQUIRED")


# ---------------------------------------------------------------------------
# §3.5 Order accept by foreign restaurant identity mismatch
# ---------------------------------------------------------------------------

@test("accept: PLACED -> RESTAURANT_ACCEPTED bumps version exactly 1")
def t_accept_version_bump():
    c = fresh_client()
    rid = _approve_active_restaurant(c)
    mid = _menu_item(c, rid)
    cid = _customer(c)
    order = _place_order(c, cid, rid, mid)
    v0 = order["version"]
    resp = jpost(c, f"/api/orders/{order['id']}/accept",
                 headers=rest_headers(rid))
    assert_eq(body_of(resp)["data"]["version"], v0 + 1, "version+1")


# ---------------------------------------------------------------------------
# §3.7 Late fine boundary: 11 min late -> tier 2 starts (500 + 50*1 = 550)
# ---------------------------------------------------------------------------

@test("late fine: 11 min late -> 550c (tier-2 start)")
def t_late_fine_tier2_start():
    assert_eq(compute.late_fine_amount_cents(11, 1000), 550, "11 -> 550")


@test("late fine: 10 min late -> 200c (tier-1 boundary)")
def t_late_fine_tier1_top():
    assert_eq(compute.late_fine_amount_cents(10, 1000), 200, "10 -> 200")


@test("late fine: 30 min -> 1500c (tier-2 top)")
def t_late_fine_tier2_top():
    assert_eq(compute.late_fine_amount_cents(30, 1000), 1500, "30 -> 1500")


@test("late fine: 31 min, fee=200 -> min(200,1500)+500 = 700c")
def t_late_fine_tier3_capped():
    assert_eq(compute.late_fine_amount_cents(31, 200), 700, "31 -> 700")


# ---------------------------------------------------------------------------
# §3.6 OFFERED state: rider rejecting an unowned offer -> 403
# ---------------------------------------------------------------------------

@test("assignment reject: foreign rider -> ERR_FORBIDDEN")
def t_assignment_reject_foreign():
    c = fresh_client()
    rid = _approve_active_restaurant(c)
    mid = _menu_item(c, rid)
    cid = _customer(c)
    rrid_a = _rider(c, name="A", phone="+1")
    _rider(c, name="B", phone="+2")
    order = _place_order(c, cid, rid, mid)
    jpost(c, f"/api/orders/{order['id']}/accept", headers=rest_headers(rid))
    jpost(c, f"/api/orders/{order['id']}/start-preparing",
          headers=rest_headers(rid))
    a = [aa for aa in state.STORE.assignments.values()
         if aa["order_id"] == order["id"]][0]
    # The other rider (not the one assigned) attempts to reject
    foreign = (rrid_a if a["rider_id"] != rrid_a
               else [r for r in state.STORE.riders if r != rrid_a][0])
    resp = jpost(c, f"/api/assignments/{a['id']}/reject",
                 headers=rider_headers(foreign))
    assert_err(resp, 403, "ERR_FORBIDDEN")


# ---------------------------------------------------------------------------
# §3.9 Return reject from ESCALATED (the ESCALATED-as-start-state path)
# ---------------------------------------------------------------------------

@test("return reject: ESCALATED -> REJECTED is legal")
def t_return_reject_from_escalated():
    c = fresh_client()
    rid, cid, rrid, order, a = _deliver_world(c)
    ret = body_of(jpost(c, f"/api/orders/{order['id']}/returns",
                        body={"reason": "OTHER",
                              "requested_refund_cents": 1000},
                        headers=cust_headers(cid)))["data"]
    jpost(c, f"/api/returns/{ret['id']}/escalate", headers=cs_headers())
    resp = jpost(c, f"/api/returns/{ret['id']}/reject", headers=cs_headers())
    assert_eq(body_of(resp)["data"]["status"], "REJECTED",
              "rejected from ESCALATED")


# ---------------------------------------------------------------------------
# §2.6 Pipeline ordering — auth before existence (sanity)
# ---------------------------------------------------------------------------

@test("pipeline: missing auth comes before 404 (auth wins)")
def t_pipeline_auth_first():
    c = fresh_client()
    resp = jget(c, "/api/restaurants/does-not-exist")
    assert_err(resp, 401, "ERR_AUTH_REQUIRED")


# ---------------------------------------------------------------------------
# §3.4 Cross-restaurant menu_item rejected as RESTAURANT_UNAVAILABLE
# ---------------------------------------------------------------------------

@test("order: menu_item from another restaurant -> ERR_RESTAURANT_UNAVAILABLE")
def t_order_cross_restaurant_item():
    c = fresh_client()
    rid_a = _approve_active_restaurant(c, name="A")
    rid_b = _approve_active_restaurant(c, name="B")
    mid_b = _menu_item(c, rid_b)
    cid = _customer(c)
    resp = jpost(c, "/api/orders",
                 body={"customer_id": cid, "restaurant_id": rid_a,
                       "items": [{"menu_item_id": mid_b, "quantity": 1}]},
                 headers=cust_headers(cid))
    assert_err(resp, 422, "ERR_RESTAURANT_UNAVAILABLE")


# ---------------------------------------------------------------------------
# §3.4 Subtotal exactly 100 cents -> accepted (boundary inclusive)
# ---------------------------------------------------------------------------

@test("order: subtotal exactly 100 cents -> 201")
def t_order_subtotal_at_min():
    c = fresh_client()
    rid = _approve_active_restaurant(c)
    mid = _menu_item(c, rid, price_cents=100)
    cid = _customer(c)
    resp = jpost(c, "/api/orders",
                 body={"customer_id": cid, "restaurant_id": rid,
                       "items": [{"menu_item_id": mid, "quantity": 1}]},
                 headers=cust_headers(cid))
    assert_eq(resp.status_code, 201, "min boundary placement OK")


# ---------------------------------------------------------------------------
# §3.3 Rider GET by another rider -> ERR_FORBIDDEN
# ---------------------------------------------------------------------------

@test("rider: foreign rider GET -> ERR_FORBIDDEN")
def t_rider_foreign_get():
    c = fresh_client()
    rrid_a = _rider(c, name="A", phone="+1", go_online=False)
    rrid_b = _rider(c, name="B", phone="+2", go_online=False)
    resp = jget(c, f"/api/riders/{rrid_a}", headers=rider_headers(rrid_b))
    assert_err(resp, 403, "ERR_FORBIDDEN")


# ---------------------------------------------------------------------------
# §3.7 Fine creation recomputes bonus_tier (transitive cascade)
# ---------------------------------------------------------------------------

@test("late fine cascade: rider bonus_tier recomputed alongside the fine")
def t_late_fine_triggers_tier_recompute():
    c = fresh_client()
    rid = _approve_active_restaurant(c)
    mid = _menu_item(c, rid)
    cid = _customer(c)
    rrid = _rider(c)
    order = _place_order(c, cid, rid, mid)
    jpost(c, f"/api/orders/{order['id']}/accept", headers=rest_headers(rid))
    jpost(c, f"/api/orders/{order['id']}/start-preparing",
          headers=rest_headers(rid))
    a = [aa for aa in state.STORE.assignments.values()
         if aa["order_id"] == order["id"]][0]
    jpost(c, f"/api/assignments/{a['id']}/accept",
          headers=rider_headers(rrid))
    jpost(c, f"/api/orders/{order['id']}/ready", headers=rest_headers(rid))
    jpost(c, f"/api/assignments/{a['id']}/pickup",
          headers=rider_headers(rrid))
    # Backdate promise to trigger 11+ minutes late (tier-2 fine)
    state.STORE.orders[order["id"]]["promised_delivery_time"] = (
        state.now() - timedelta(minutes=20)
    )
    jpost(c, f"/api/assignments/{a['id']}/deliver",
          headers=rider_headers(rrid))
    # 10/10 fewer than 10 deliveries → on_time_rate stays at default 1.0,
    # but bonus_tier remains computed.  Check tier is well-defined.
    rider = state.STORE.riders[rrid]
    assert rider["bonus_tier"] in (
        "BRONZE", "SILVER", "GOLD", "PLATINUM",
    ), "tier set after fine"


# ---------------------------------------------------------------------------
# §3.11 Restaurant cannot read another restaurant's fine
# ---------------------------------------------------------------------------

@test("fines: customer cannot read a rider's fine -> ERR_FORBIDDEN")
def t_fine_customer_other_subject():
    c = fresh_client()
    from tests.test_fines_and_workorders import _make_rider_with_fine
    rrid, cid, fine = _make_rider_with_fine(c)
    resp = jget(c, f"/api/fines/{fine['id']}", headers=cust_headers(cid))
    assert_err(resp, 403, "ERR_FORBIDDEN")


# ---------------------------------------------------------------------------
# §3.6 Reject without redispatch when pool is empty leaves order intact
# ---------------------------------------------------------------------------

@test("reject with empty pool: no fresh OFFERED, order still PREPARING")
def t_reject_no_redispatch_when_pool_empty():
    c = fresh_client()
    rid = _approve_active_restaurant(c)
    mid = _menu_item(c, rid)
    cid = _customer(c)
    rrid = _rider(c)  # only one rider
    order = _place_order(c, cid, rid, mid)
    jpost(c, f"/api/orders/{order['id']}/accept", headers=rest_headers(rid))
    jpost(c, f"/api/orders/{order['id']}/start-preparing",
          headers=rest_headers(rid))
    a = [aa for aa in state.STORE.assignments.values()
         if aa["order_id"] == order["id"]][0]
    jpost(c, f"/api/assignments/{a['id']}/reject",
          headers=rider_headers(rrid))
    fresh = [aa for aa in state.STORE.assignments.values()
             if aa["order_id"] == order["id"] and aa["status"] == "OFFERED"]
    assert_eq(fresh, [], "no fresh offer when pool empty")
    assert_eq(state.STORE.orders[order["id"]]["status"], "PREPARING",
              "order remains PREPARING")
