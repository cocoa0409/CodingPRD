"""Telematics, coaching holds and the route bid board -- PRD §3.9.

Plus the administrative logical-clock surface of PRD §2.5.
"""

from flask import Blueprint, g

import calc
from core import (
    ALL_ROLES, D, apply_filters, auth, by_created, bump, clock_now, fail,
    fmt_instant, must_exist, new_row, out, page, parse_instant, respond,
    unique_code, db,
)
import validate as v

bp = Blueprint("board", __name__)

READ_ROLES = ALL_ROLES
POSTING_STATUSES = ("OPEN", "AWARDED", "VACANT", "CANCELLED")
BID_STATUSES = ("SUBMITTED", "AWARDED", "PASSED_OVER", "WITHDRAWN")
EVENT_TYPES = ("HARD_BRAKE", "SPEEDING", "FOLLOWING_DISTANCE", "SEATBELT")


def _release_bids(driver_id):
    """§3.9 / §3.3: every SUBMITTED bid of the driver is passed over, and each
    such bid lowers its posting's bid_count by one."""
    for bid in by_created([b for b in db.bids.values() if b["driver_id"] == driver_id]):
        if bid["status"] != "SUBMITTED":
            continue
        bid["status"] = "PASSED_OVER"
        bump(bid)
        posting = db.postings.get(bid["route_posting_id"])
        if posting is not None:
            posting["bid_count"] = int(posting["bid_count"]) - 1
            bump(posting)


def coaching_hold_cascade(driver):
    """§3.9: fired the instant coaching_hold flips false -> true."""
    for trip in by_created(list(db.trips.values())):
        if trip.get("driver_id") != driver["id"]:
            continue
        if trip["plan_status"] not in ("DRAFT", "PLANNED"):
            continue
        tractor = db.tractors.get(trip.get("tractor_id")) if trip.get("tractor_id") else None
        trailer = db.trailers.get(trip.get("trailer_id")) if trip.get("trailer_id") else None
        trip["driver_id"] = None
        trip["tractor_id"] = None
        trip["trailer_id"] = None
        trip["pinned_pay_plan_id"] = None
        trip["pinned_pay_plan_version"] = None
        trip["_pinned_plan_snapshot"] = None
        trip["planned_pay_cents"] = 0
        if trip["plan_status"] == "PLANNED":
            trip["plan_status"] = "DRAFT"
        if tractor is not None and tractor["status"] == "ASSIGNED":
            tractor["status"] = "AVAILABLE"
            bump(tractor)
        if trailer is not None and trailer["status"] == "ASSIGNED":
            trailer["status"] = "AVAILABLE"
            bump(trailer)
        for stop in calc.trip_stops(trip["id"]):
            if stop["stop_type"] != "DELIVERY":
                continue
            order = db.orders.get(stop.get("replenishment_order_id"))
            if order is not None and order["status"] == "SCHEDULED":
                order["status"] = "UNSCHEDULED"
                bump(order)
                store = db.stores.get(order["store_id"])
                if store is not None:
                    store["open_scheduled_cases"] = int(store["open_scheduled_cases"]) - int(
                        order["cases"]
                    )
                    bump(store)
            stop["status"] = "SKIPPED"
            bump(stop)
        bump(trip)
    _release_bids(driver["id"])


# ===========================================================================
# Route postings
# ===========================================================================
@bp.post("/route-postings")
def create_posting():
    auth(["TransportManager"])
    data = v.body()
    v.fk(data, "domicile_id", "domiciles")
    route_code = v.rstr(data, "route_code", 1, 16)
    domicile_id = v.rref(data, "domicile_id")
    weekly_miles = v.rint(data, "weekly_miles", 0)
    weekly_stops = v.rint(data, "weekly_stops", 0)
    start_effective_date = v.rdate(data, "start_effective_date")
    bid_close_at = v.rinstant(data, "bid_close_at")
    unique_code(db.postings, "route_code", route_code)
    row = new_row({
        "route_code": route_code,
        "domicile_id": domicile_id,
        "weekly_miles": weekly_miles,
        "weekly_stops": weekly_stops,
        "start_effective_date": start_effective_date,
        "bid_close_at": bid_close_at,
        "status": "OPEN",
        "awarded_driver_id": None,
        "bid_count": 0,
        "created_by_user_id": g.user_id,
    })
    db.postings[row["id"]] = row
    return respond(out(row), 201)


@bp.get("/route-postings/<posting_id>")
def get_posting(posting_id):
    auth(READ_ROLES)
    return respond(out(must_exist("postings", posting_id)))


@bp.get("/route-postings")
def list_postings():
    auth(READ_ROLES)
    limit, offset = v.page_window()
    rows = apply_filters(list(db.postings.values()), [
        ("domicile_id", v.qstr("domicile_id")),
        ("awarded_driver_id", v.qstr("awarded_driver_id")),
        ("status", v.qenum("status", POSTING_STATUSES)),
    ])
    return page(rows, limit, offset)


@bp.post("/route-postings/<posting_id>/award")
def award_posting(posting_id):
    auth(["TransportManager"])
    posting = must_exist("postings", posting_id)
    # level 3: the manager who published a route may not award it
    if g.user_id == posting["created_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES")
    v.body()
    # level 8
    if posting["status"] != "OPEN":
        fail("ERR_POSTING_NOT_OPEN")
    if not (clock_now() >= D(posting["bid_close_at"])):
        fail("ERR_BID_WINDOW_OPEN")

    submitted = by_created([
        b for b in db.bids.values()
        if b["route_posting_id"] == posting["id"] and b["status"] == "SUBMITTED"
    ])
    candidates = []
    for bid in submitted:
        driver = db.drivers.get(bid["driver_id"])
        if driver is None:
            continue
        # The LIVE driver row governs; the bid's snapshots are audit only.
        if driver["status"] != "ACTIVE":
            continue
        if driver["coaching_hold"]:
            continue
        if int(driver["safety_score"]) < calc.MIN_BID_SAFETY_SCORE:
            continue
        if driver["domicile_id"] != posting["domicile_id"]:
            continue
        candidates.append(bid)

    winner = None
    if candidates:
        def rank(bid):
            driver = db.drivers[bid["driver_id"]]
            return (
                driver["seniority_date"],
                -int(driver["safety_score"]),
                bid["created_at"],
                bid["_seq"],
            )
        winner = min(candidates, key=rank)

    for bid in submitted:
        if winner is not None and bid["id"] == winner["id"]:
            bid["status"] = "AWARDED"
        else:
            bid["status"] = "PASSED_OVER"
        bump(bid)
    if winner is not None:
        posting["awarded_driver_id"] = winner["driver_id"]
        posting["status"] = "AWARDED"
    else:
        posting["status"] = "VACANT"
    posting["bid_count"] = 0
    bump(posting)
    return respond(out(posting))


@bp.post("/route-postings/<posting_id>/cancel")
def cancel_posting(posting_id):
    auth(["TransportManager"])
    posting = must_exist("postings", posting_id)
    data = v.body()
    reason = v.ostr(data, "reason_code")
    if posting["status"] != "OPEN":
        fail("ERR_POSTING_NOT_OPEN")
    for bid in by_created(list(db.bids.values())):
        if bid["route_posting_id"] != posting["id"] or bid["status"] != "SUBMITTED":
            continue
        # No judging occurred, so open bids are withdrawn rather than passed over.
        bid["status"] = "WITHDRAWN"
        bump(bid)
    posting["status"] = "CANCELLED"
    posting["bid_count"] = 0
    posting["_reason_code"] = reason
    bump(posting)
    return respond(out(posting))


# ===========================================================================
# Route bids
# ===========================================================================
@bp.post("/route-bids")
def create_bid():
    auth(["Driver"])
    data = v.body()
    v.fk(data, "route_posting_id", "postings")
    posting_id = v.rref(data, "route_posting_id")
    expected = v.rint(data, "expected_posting_version")
    posting = db.postings[posting_id]
    # The bidder is always the authenticated user, never a body field.
    driver = must_exist("drivers", g.user_id)
    # level 9
    if expected != int(posting["version"]):
        fail("ERR_STALE_POSTING_VERSION")
    # level 10
    if posting["status"] != "OPEN":
        fail("ERR_POSTING_NOT_OPEN")
    if driver["status"] != "ACTIVE":
        fail("ERR_DRIVER_NOT_ACTIVE")
    # level 11, in this exact order
    if driver["coaching_hold"]:
        fail("ERR_DRIVER_COACHING_HOLD")
    if int(driver["safety_score"]) < calc.MIN_BID_SAFETY_SCORE:
        fail("ERR_DRIVER_SAFETY_INELIGIBLE")
    if driver["domicile_id"] != posting["domicile_id"]:
        fail("ERR_DOMICILE_MISMATCH")
    # level 15: one SUBMITTED bid per posting per driver
    for other in db.bids.values():
        if (other["route_posting_id"] == posting["id"]
                and other["driver_id"] == driver["id"]
                and other["status"] == "SUBMITTED"):
            fail("ERR_DUPLICATE_BID")
    row = new_row({
        "route_posting_id": posting["id"],
        "driver_id": driver["id"],
        "seniority_date_snapshot": driver["seniority_date"],
        "safety_score_snapshot": int(driver["safety_score"]),
        "status": "SUBMITTED",
    })
    db.bids[row["id"]] = row
    posting["bid_count"] = int(posting["bid_count"]) + 1
    bump(posting)
    return respond(out(row), 201)


@bp.get("/route-bids/<bid_id>")
def get_bid(bid_id):
    auth(READ_ROLES)
    return respond(out(must_exist("bids", bid_id)))


@bp.get("/route-bids")
def list_bids():
    auth(READ_ROLES)
    limit, offset = v.page_window()
    rows = apply_filters(list(db.bids.values()), [
        ("route_posting_id", v.qstr("route_posting_id")),
        ("driver_id", v.qstr("driver_id")),
        ("status", v.qenum("status", BID_STATUSES)),
    ])
    return page(rows, limit, offset)


@bp.post("/route-bids/<bid_id>/withdraw")
def withdraw_bid(bid_id):
    auth(["Driver"])
    bid = must_exist("bids", bid_id)
    v.body()
    if bid["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE_TRANSITION")
    if g.user_id != bid["driver_id"]:
        fail("ERR_DRIVER_SCOPE_VIOLATION")
    bid["status"] = "WITHDRAWN"
    bump(bid)
    posting = db.postings.get(bid["route_posting_id"])
    if posting is not None:
        posting["bid_count"] = int(posting["bid_count"]) - 1
        bump(posting)
    return respond(out(bid))


# ===========================================================================
# Telematics events
# ===========================================================================
@bp.post("/telematics-events")
def create_event():
    auth(["SafetyManager"])
    data = v.body()
    v.fk(data, "driver_id", "drivers")
    if data.get("trip_id") is not None:
        v.fk(data, "trip_id", "trips")
    driver_id = v.rref(data, "driver_id")
    trip_id = v.oref(data, "trip_id")
    event_type = v.renum(data, "event_type", EVENT_TYPES)
    severity = v.rint(data, "severity", 1, 3)
    occurred_at = v.rinstant(data, "occurred_at")
    driver = db.drivers[driver_id]
    # penalty_points is fixed at creation and never recomputed afterwards.
    row = new_row({
        "driver_id": driver_id,
        "trip_id": trip_id,
        "event_type": event_type,
        "severity": severity,
        "occurred_at": occurred_at,
        "penalty_points": calc.BASE_POINTS[event_type] * severity,
        "coached": False,
        "coached_at": None,
        "coached_by_user_id": None,
    }, versioned=False)
    db.events[row["id"]] = row
    was_held = bool(driver["coaching_hold"])
    calc.recompute_driver_safety(driver)
    bump(driver)
    if driver["coaching_hold"] and not was_held:
        coaching_hold_cascade(driver)
    return respond(out(row), 201)


@bp.get("/telematics-events/<event_id>")
def get_event(event_id):
    auth(READ_ROLES)
    return respond(out(must_exist("events", event_id)))


@bp.get("/telematics-events")
def list_events():
    auth(READ_ROLES)
    limit, offset = v.page_window()
    rows = apply_filters(list(db.events.values()), [
        ("driver_id", v.qstr("driver_id")),
        ("trip_id", v.qstr("trip_id")),
        ("event_type", v.qenum("event_type", EVENT_TYPES)),
        ("coached", v.qbool("coached")),
    ])
    return page(rows, limit, offset)


@bp.post("/telematics-events/<event_id>/coach")
def coach_event(event_id):
    auth(["SafetyManager"])
    event = must_exist("events", event_id)
    data = v.body()
    note = v.ostr(data, "coaching_note")
    # level 8
    if event["coached"]:
        fail("ERR_ALREADY_COACHED")
    # level 10
    driver = db.drivers.get(event["driver_id"])
    if driver is None or driver["status"] == "TERMINATED":
        fail("ERR_DRIVER_NOT_ACTIVE")
    event["coached"] = True
    event["coached_at"] = fmt_instant(clock_now())
    event["coached_by_user_id"] = g.user_id
    event["_coaching_note"] = note
    # Coaching retires the points; it never restores the released trips or bids.
    calc.recompute_driver_safety(driver)
    bump(driver)
    return respond(out(event))


# ===========================================================================
# The logical clock (PRD §2.5)
# ===========================================================================
@bp.post("/_clock/set_current_utc")
def set_clock():
    auth(READ_ROLES)
    data = v.body()
    current_utc = v.rinstant(data, "current_utc")
    db.clock = parse_instant(current_utc)
    db.clock_raw = current_utc
    return respond({"current_utc": current_utc})
