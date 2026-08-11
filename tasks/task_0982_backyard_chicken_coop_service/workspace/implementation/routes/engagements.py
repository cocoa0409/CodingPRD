"""SittingEngagement endpoints (PRD §3.6)."""
from datetime import timedelta

from flask import Blueprint, request

from db import new_id, now, serialize, stamp_new, store, touch
from errors import fail
from middleware import ALL_ROLES, authenticate, body, require_owner, require_role
from response import list_response, ok
from services.pricing import (
    STOP_DURATION_MINUTES,
    engagement_date_overlap,
    engagement_nights,
    route_assignment_selector,
    sitting_cancellation_fee,
    sitting_final_settlement,
    sitting_quote_price,
)
from util import req_dt, valid_hm

bp = Blueprint("engagements", __name__)

CUSTOMER_OR_ADMIN = {"Customer", "PlatformAdmin"}


def get_engagement(eid):
    e = store.engagements.get(eid)
    if e is None:
        fail("ERR_ENGAGEMENT_NOT_FOUND", f"Sitting engagement {eid} does not exist")
    return e


@bp.route("/coopcare/sitting-engagements", methods=["POST"])
def create_engagement():
    uid, role = authenticate()
    require_role(role, CUSTOMER_OR_ADMIN)
    data = body()
    household_id = data.get("household_id")
    coop_site_id = data.get("coop_site_id")
    require_owner(uid, role, household_id if isinstance(household_id, str) else None)
    if not isinstance(household_id, str) or not household_id.strip():
        fail("ERR_INVALID_REQUEST", "household_id is required")
    if not isinstance(coop_site_id, str) or not coop_site_id.strip():
        fail("ERR_INVALID_REQUEST", "coop_site_id is required")
    h = store.households.get(household_id)
    if h is None:
        fail("ERR_HOUSEHOLD_NOT_FOUND", f"Household {household_id} does not exist")
    c = store.coops.get(coop_site_id)
    if c is None or c["household_id"] != household_id:
        fail("ERR_COOP_SITE_NOT_FOUND", f"Coop site {coop_site_id} does not exist for this household")
    start_date = req_dt(data, "start_date")
    end_date = req_dt(data, "end_date")
    window_start = data.get("daily_window_start")
    if not valid_hm(window_start):
        fail("ERR_INVALID_TIME_RANGE", "daily_window_start must be a well-formed HH:MM string")
    # Temporal (priority 10) precedes the duration constraint (priority 11).
    if start_date < now():
        fail("ERR_SCHEDULE_IN_PAST", "start_date is earlier than the logical clock")
    rec_probe = {"start_date": start_date, "end_date": end_date}
    nights = engagement_nights(rec_probe)
    if nights < 1 or nights > 30:
        fail("ERR_ENGAGEMENT_DURATION_INVALID", "engagement length must be between 1 and 30 nights")
    rec = stamp_new({
        "id": new_id(),
        "household_id": household_id,
        "coop_site_id": coop_site_id,
        "start_date": start_date,
        "end_date": end_date,
        "daily_window_start": window_start,
        "status": "REQUESTED",
        "quoted_price_cents": None,
        "final_price_cents": None,
        "cancellation_fee_cents": 0,
        "cancelled_at": None,
        "settled_at": None,
        "billed_invoice_id": None,
    })
    store.engagements[rec["id"]] = rec
    return ok(serialize(rec), 201)


@bp.route("/coopcare/sitting-engagements", methods=["GET"])
def list_engagements():
    uid, role = authenticate()
    require_role(role, set(ALL_ROLES))
    filters = []
    for key in ("household_id", "coop_site_id", "status"):
        v = request.args.get(key)
        if v is not None:
            filters.append((key, v))
    return list_response(store.engagements.values(), filters)


@bp.route("/coopcare/sitting-engagements/<eid>", methods=["GET"])
def read_engagement(eid):
    uid, role = authenticate()
    require_role(role, set(ALL_ROLES))
    return ok(serialize(get_engagement(eid)), 200)


@bp.route("/coopcare/sitting-engagements/<eid>/quote", methods=["POST"])
def quote(eid):
    uid, role = authenticate()
    require_role(role, {"Dispatcher"})
    e = get_engagement(eid)
    if e["status"] != "REQUESTED":
        fail("ERR_INVALID_STATE", "quote requires engagement status REQUESTED")
    h = store.households[e["household_id"]]
    e["quoted_price_cents"] = sitting_quote_price(e, h)
    e["status"] = "QUOTED"
    touch(e)
    return ok(serialize(e), 200)


@bp.route("/coopcare/sitting-engagements/<eid>/confirm", methods=["POST"])
def confirm(eid):
    uid, role = authenticate()
    require_role(role, CUSTOMER_OR_ADMIN)
    e = get_engagement(eid)
    require_owner(uid, role, e["household_id"])
    if e["status"] != "QUOTED":
        fail("ERR_ENGAGEMENT_NOT_QUOTED", "confirm requires engagement status QUOTED")
    c = store.coops[e["coop_site_id"]]
    if c["status"] != "INSTALLED":
        fail("ERR_COOP_NOT_INSTALLED", "confirm requires an INSTALLED coop")
    if c["predator_grade"] not in ("B", "A"):
        fail("ERR_PREDATOR_GRADE_INSUFFICIENT", "confirm requires predator grade B or A")
    h = store.households[e["household_id"]]
    if engagement_date_overlap(e["household_id"], e["start_date"], e["end_date"], exclude_id=e["id"]):
        fail("ERR_ENGAGEMENT_DATE_OVERLAP", "closed-interval overlap with another engagement of this household")
    # Route availability, evaluated once per stop date; confirm is atomic.
    hh, mm = int(e["daily_window_start"][:2]), int(e["daily_window_start"][3:5])
    selections = []
    d = e["start_date"]
    while d < e["end_date"]:
        ws = d.replace(hour=hh, minute=mm, second=0, microsecond=0)
        we = ws + timedelta(minutes=STOP_DURATION_MINUTES)
        route = route_assignment_selector(h["zone_code"], d.date(), ws, we)
        if route is None:
            fail("ERR_NO_ROUTE_AVAILABLE", "no eligible route for at least one stop date")
        selections.append((route, ws, we))
        d = d + timedelta(days=1)
    e["status"] = "CONFIRMED"
    touch(e)
    for route, ws, we in selections:
        stop = stamp_new({
            "id": new_id(),
            "route_id": route["id"],
            "engagement_id": e["id"],
            "planned_start": ws,
            "planned_end": we,
            "sequence": route["committed_stops"] + 1,
            "status": "PENDING",
            "skip_reason": None,
        })
        store.stops[stop["id"]] = stop
        route["committed_stops"] += 1
        touch(route)
    return ok(serialize(e), 200)


@bp.route("/coopcare/sitting-engagements/<eid>/cancel", methods=["POST"])
def cancel_engagement(eid):
    uid, role = authenticate()
    require_role(role, {"Customer", "Dispatcher"})
    e = get_engagement(eid)
    require_owner(uid, role, e["household_id"])
    if e["status"] not in ("REQUESTED", "QUOTED", "CONFIRMED"):
        fail("ERR_ENGAGEMENT_NOT_CANCELLABLE", "cancel requires status REQUESTED, QUOTED or CONFIRMED")
    fee = 0
    if e["status"] == "CONFIRMED":
        fee = sitting_cancellation_fee(e, now())
    e["cancellation_fee_cents"] = fee
    e["cancelled_at"] = now()
    e["status"] = "CANCELLED"
    touch(e)
    # Cascade link 1: PENDING stops -> REMOVED.
    stops = sorted(
        (s for s in store.stops.values() if s["engagement_id"] == e["id"] and s["status"] == "PENDING"),
        key=lambda s: s["_seq"],
    )
    for s in stops:
        s["status"] = "REMOVED"
        touch(s)
        # Cascade link 2: owning route decrements, and auto-demotes at zero.
        route = store.routes[s["route_id"]]
        route["committed_stops"] -= 1
        if route["committed_stops"] == 0 and route["status"] == "PUBLISHED":
            route["status"] = "PLANNED"
        touch(route)
    return ok(serialize(e), 200)


@bp.route("/coopcare/sitting-engagements/<eid>/settle", methods=["POST"])
def settle(eid):
    uid, role = authenticate()
    require_role(role, {"BillingAdmin"})
    e = get_engagement(eid)
    if e["status"] != "CONFIRMED":
        fail("ERR_ENGAGEMENT_NOT_CONFIRMED", "settle requires engagement status CONFIRMED")
    for s in store.stops.values():
        if s["engagement_id"] == e["id"] and s["status"] == "PENDING":
            fail("ERR_STOPS_OUTSTANDING", "settle requires every stop to be terminal")
    h = store.households[e["household_id"]]
    e["final_price_cents"] = sitting_final_settlement(e, h)
    e["settled_at"] = now()
    e["status"] = "COMPLETED"
    touch(e)
    return ok(serialize(e), 200)
