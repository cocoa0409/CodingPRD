"""Transportation requests, approval, cancellation."""
from flask import Blueprint, request

from core import (
    DB, ALL_ROLES, auth, own, body, ok, ok_list, fail, req_str, req_int,
    opt_str, opt_int, new_record, touch, now, pagination, paginate,
    get_school, get_contest, get_transport, ser_transport,
)
import calc

bp = Blueprint("transport", __name__)


@bp.post("/athletics/transport-requests")
def create_transport():
    p = auth(["SchoolAthleticDirector"])
    b = body()
    raw_school = b.get("requesting_school_id")
    if isinstance(raw_school, str):
        own(p, raw_school)
    if isinstance(b.get("contest_id"), str):
        get_contest(b["contest_id"])
    if isinstance(raw_school, str):
        get_school(raw_school)
    contest_id = req_str(b, "contest_id")
    school_id = req_str(b, "requesting_school_id")
    travel_minutes = req_int(b, "travel_minutes", minimum=0)
    bus_count = opt_int(b, "bus_count", 1, minimum=1)

    contest = DB.contests[contest_id]
    school = DB.schools[school_id]
    depart_at, return_at, release_minutes = calc.transport_release_window(
        contest, school, travel_minutes)
    if depart_at <= now():
        fail("ERR_TRANSPORT_DEPARTURE_IN_PAST",
             "the computed departure falls at or before the logical clock")
    if release_minutes > school["max_release_minutes_per_request"]:
        fail("ERR_RELEASE_TIME_EXCEEDED",
             "the computed release minutes exceed the school's per-request ceiling")

    rec = new_record({
        "contest_id": contest_id,
        "requesting_school_id": school_id,
        "bus_count": bus_count,
        "travel_minutes": travel_minutes,
        "depart_at": depart_at,
        "return_at": return_at,
        "release_minutes": release_minutes,
        "status": "REQUESTED",
        "cancelled_reason": None,
    })
    DB.transports[rec["id"]] = rec
    return ok(ser_transport(rec), 201)


@bp.post("/athletics/transport-requests/<tid>/approve")
def approve_transport(tid):
    auth(["AssociationAdmin"])
    trip = get_transport(tid)
    if trip["status"] != "REQUESTED":
        fail("ERR_INVALID_STATE", "only a REQUESTED trip may be approved")
    contest = DB.contests.get(trip["contest_id"])
    if contest is None or contest["status"] not in ("OFFICIALS_ASSIGNED", "CONFIRMED"):
        fail("ERR_CONTEST_NOT_SCHEDULED_FOR_TRANSPORT",
             "the parent contest is not in a state that admits transport approval")
    school = DB.schools.get(trip["requesting_school_id"])
    if school is not None and not calc.fleet_capacity_overlap(trip, school):
        fail("ERR_FLEET_CAPACITY_EXCEEDED",
             "the school's fleet cannot cover this trip's window")
    trip["status"] = "APPROVED"
    touch(trip)
    if school is not None:
        school["release_minutes_used"] += trip["release_minutes"]
        touch(school)
    return ok(ser_transport(trip))


@bp.post("/athletics/transport-requests/<tid>/cancel")
def cancel_transport(tid):
    p = auth(["SchoolAthleticDirector"])
    trip = get_transport(tid)
    own(p, trip["requesting_school_id"])
    b = body()
    opt_str(b, "cancel_note", None)
    if trip["status"] not in ("REQUESTED", "APPROVED"):
        fail("ERR_INVALID_STATE", "a trip in %s may not be cancelled" % trip["status"])
    was_approved = trip["status"] == "APPROVED"
    trip["status"] = "CANCELLED"
    trip["cancelled_reason"] = "SCHOOL_REQUEST"
    touch(trip)
    if was_approved:
        school = DB.schools.get(trip["requesting_school_id"])
        if school is not None:
            school["release_minutes_used"] -= trip["release_minutes"]
            touch(school)
    return ok(ser_transport(trip))


@bp.get("/athletics/transport-requests/<tid>")
def read_transport(tid):
    auth(ALL_ROLES)
    return ok(ser_transport(get_transport(tid)))


@bp.get("/athletics/transport-requests")
def list_transport():
    auth(ALL_ROLES)
    limit, offset = pagination()
    rows = list(DB.transports.values())
    for key in ("contest_id", "requesting_school_id", "status"):
        val = request.args.get(key)
        if val is not None:
            rows = [t for t in rows if t[key] == val]
    rows.sort(key=lambda t: (t["depart_at"], t["created_at"], t["_seq"]))
    page, total = paginate(rows, limit, offset)
    return ok_list([ser_transport(t) for t in page], limit, offset, total)
