"""ClassSession and Booking endpoints (PRD §3.5)."""
from flask import Blueprint, request

import db
import errors
import lookups
import models
from middleware import authenticate, require_role, require_owner
from response import success
from services import member_ops
from util import (require_str, require_int, parse_dt, parse_pagination, paginate)

bp = Blueprint("classes", __name__)


# --------------------------------------------------------------------------
# ClassSession
# --------------------------------------------------------------------------

@bp.route("/class-sessions", methods=["POST"])
def create_session():
    caller = authenticate()
    require_role(caller, ["StaffManager"])
    body = request.get_json(silent=True) or {}

    location_id = require_str(body, "location_id")
    title = require_str(body, "title")
    starts_raw = _required(body, "starts_at")
    ends_raw = _required(body, "ends_at")
    capacity = require_int(body, "capacity", minimum=1)
    waitlist_cap = require_int(body, "waitlist_cap", minimum=0)

    # Existence (priority 3) before well-formedness temporal check (priority 4).
    location = lookups.get_location(location_id)

    starts_at = parse_dt(starts_raw, "starts_at")
    ends_at = parse_dt(ends_raw, "ends_at")
    if ends_at <= starts_at:
        errors.raise_error(errors.ERR_INVALID_REQUEST, "ends_at must be after starts_at")

    rec = models.stamp_new({
        "location_id": location_id,
        "title": title,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "capacity": capacity,
        "waitlist_cap": waitlist_cap,
        "status": "SCHEDULED",
    })
    db.store.class_sessions[rec["id"]] = rec
    return success(models.serialize_class_session(rec), status=201)


@bp.route("/class-sessions/<session_id>", methods=["GET"])
def get_session(session_id):
    caller = authenticate()
    require_role(caller, ["StaffManager", "Member"])
    rec = lookups.get_class_session(session_id)
    return success(models.serialize_class_session(rec), status=200)


@bp.route("/class-sessions", methods=["GET"])
def list_sessions():
    caller = authenticate()
    require_role(caller, ["StaffManager", "Member"])
    items = list(db.store.class_sessions.values())
    location_id = request.args.get("location_id")
    status = request.args.get("status")
    if location_id is not None:
        items = [s for s in items if s["location_id"] == location_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    limit, offset = parse_pagination(request.args)
    page, pagination = paginate(items, limit, offset)
    return success([models.serialize_class_session(s) for s in page], status=200, pagination=pagination)


@bp.route("/class-sessions/<session_id>/cancel", methods=["POST"])
def cancel_session(session_id):
    caller = authenticate()
    require_role(caller, ["StaffManager"])
    session = lookups.get_class_session(session_id)
    body = request.get_json(silent=True) or {}
    expected = _required_version(body, "expected_session_version")

    # OCC (priority 7) before state validity (priority 8).
    _check_session_occ(session, expected)
    if session["status"] != "SCHEDULED":
        errors.raise_error(errors.ERR_INVALID_STATE, "Session is not SCHEDULED")

    session["status"] = "CANCELLED"
    # All BOOKED and WAITLISTED bookings -> CANCELLED; restore credit on charged.
    for b in _session_bookings(session_id):
        if b["status"] in ("BOOKED", "WAITLISTED"):
            b["status"] = "CANCELLED"
            if b["credit_charged"]:
                member = db.store.members.get(b["member_id"])
                if member is not None:
                    member["class_credits_remaining"] += 1
                    models.touch(member)
                b["credit_charged"] = False
            models.touch(b)
    models.touch(session)
    return success(models.serialize_class_session(session), status=200)


@bp.route("/class-sessions/<session_id>/complete", methods=["POST"])
def complete_session(session_id):
    caller = authenticate()
    require_role(caller, ["StaffManager"])
    session = lookups.get_class_session(session_id)
    body = request.get_json(silent=True) or {}
    expected = _required_version(body, "expected_session_version")

    _check_session_occ(session, expected)
    if session["status"] != "SCHEDULED":
        errors.raise_error(errors.ERR_INVALID_STATE, "Session is not SCHEDULED")
    if db.now() < session["ends_at"]:
        errors.raise_error(errors.ERR_INVALID_STATE, "Session has not ended yet")

    session["status"] = "COMPLETED"
    for b in _session_bookings(session_id):
        if b["status"] == "BOOKED":
            # NO_SHOW: credit forfeited (not restored).
            b["status"] = "NO_SHOW"
            models.touch(b)
        elif b["status"] == "WAITLISTED":
            b["status"] = "CANCELLED"
            models.touch(b)
    models.touch(session)
    return success(models.serialize_class_session(session), status=200)


# --------------------------------------------------------------------------
# Booking
# --------------------------------------------------------------------------

@bp.route("/bookings", methods=["POST"])
def create_booking():
    caller = authenticate()
    require_role(caller, ["StaffManager", "Member"])
    body = request.get_json(silent=True) or {}

    session_id = require_str(body, "session_id")
    member_id = require_str(body, "member_id")
    expected = _required_version(body, "expected_session_version")

    # Ownership (priority 2): a Member may only book for self.
    require_owner(caller, member_id)

    # Existence (priority 3) left-to-right: session then member.
    session = lookups.get_class_session(session_id)
    member = lookups.get_member(member_id)

    # OCC (priority 7).
    _check_session_occ(session, expected)

    # State validity (priority 8): session must be SCHEDULED.
    if session["status"] != "SCHEDULED":
        errors.raise_error(errors.ERR_INVALID_STATE, "Session is not SCHEDULED")

    # Member bookable (priority 13).
    if not member_ops.member_bookable(member):
        errors.raise_error(errors.ERR_MEMBER_NOT_BOOKABLE, "Member is not bookable")

    booked = models.booked_count(session_id)
    waitlisted = models.waitlisted_count(session_id)

    # Session full geometry (priority 14): both pools full.
    if booked >= session["capacity"] and waitlisted >= session["waitlist_cap"]:
        errors.raise_error(errors.ERR_SESSION_FULL, "Session and waitlist are full")

    # Time overlap (priority 15): no non-terminal booking on an overlapping session.
    if _has_time_overlap(member_id, session):
        errors.raise_error(errors.ERR_BOOKING_TIME_OVERLAP, "Member has an overlapping booking")

    # Decide initial state by capacity.
    if booked < session["capacity"]:
        # BOOKED path requires a class credit (priority 17).
        if member["class_credits_remaining"] < 1:
            errors.raise_error(errors.ERR_NO_CLASS_CREDITS, "No class credits remaining")
        rec = models.stamp_new({
            "session_id": session_id,
            "member_id": member_id,
            "status": "BOOKED",
            "credit_charged": True,
            "booked_at": db.now(),
        })
        member["class_credits_remaining"] -= 1
        models.touch(member)
    else:
        # WAITLISTED path: no credit, no credit check.
        rec = models.stamp_new({
            "session_id": session_id,
            "member_id": member_id,
            "status": "WAITLISTED",
            "credit_charged": False,
            "booked_at": None,
        })

    db.store.bookings[rec["id"]] = rec
    models.touch(session)  # session version increments to reflect count change.
    return success(models.serialize_booking(rec), status=201)


@bp.route("/bookings/<booking_id>", methods=["GET"])
def get_booking(booking_id):
    caller = authenticate()
    require_role(caller, ["StaffManager", "Member"])
    rec = lookups.get_booking(booking_id)
    require_owner(caller, rec["member_id"])
    return success(models.serialize_booking(rec), status=200)


@bp.route("/bookings", methods=["GET"])
def list_bookings():
    caller = authenticate()
    require_role(caller, ["StaffManager", "Member"])
    items = list(db.store.bookings.values())
    # A Member sees only their own bookings.
    if caller.is_member:
        items = [b for b in items if b["member_id"] == caller.user_id]
    session_id = request.args.get("session_id")
    member_id = request.args.get("member_id")
    status = request.args.get("status")
    if session_id is not None:
        items = [b for b in items if b["session_id"] == session_id]
    if member_id is not None:
        items = [b for b in items if b["member_id"] == member_id]
    if status is not None:
        items = [b for b in items if b["status"] == status]
    limit, offset = parse_pagination(request.args)
    page, pagination = paginate(items, limit, offset)
    return success([models.serialize_booking(b) for b in page], status=200, pagination=pagination)


@bp.route("/bookings/<booking_id>/cancel", methods=["POST"])
def cancel_booking(booking_id):
    caller = authenticate()
    require_role(caller, ["StaffManager", "Member"])
    rec = lookups.get_booking(booking_id)
    require_owner(caller, rec["member_id"])

    if rec["status"] not in ("BOOKED", "WAITLISTED"):
        errors.raise_error(errors.ERR_INVALID_STATE, "Booking is not cancellable")

    member_ops.cancel_booking_internal(rec, run_promotion=True)
    return success(models.serialize_booking(rec), status=200)


@bp.route("/bookings/<booking_id>/attend", methods=["POST"])
def attend_booking(booking_id):
    caller = authenticate()
    require_role(caller, ["StaffManager"])
    rec = lookups.get_booking(booking_id)

    if rec["status"] != "BOOKED":
        errors.raise_error(errors.ERR_INVALID_STATE, "Booking is not BOOKED")
    session = db.store.class_sessions.get(rec["session_id"])
    if session is None or session["status"] != "SCHEDULED":
        errors.raise_error(errors.ERR_INVALID_STATE, "Owning session is not SCHEDULED")
    # Member must hold an OPEN check-in at the session's location.
    if not _has_open_checkin(rec["member_id"], session["location_id"]):
        errors.raise_error(errors.ERR_INVALID_STATE, "Member has no OPEN check-in at the session location")

    rec["status"] = "ATTENDED"
    models.touch(rec)
    return success(models.serialize_booking(rec), status=200)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _required(body, field):
    if not isinstance(body, dict) or field not in body or body[field] is None:
        errors.raise_error(errors.ERR_INVALID_REQUEST, "Missing required field '%s'" % field)
    return body[field]


def _required_version(body, field):
    if not isinstance(body, dict) or field not in body or body[field] is None:
        errors.raise_error(errors.ERR_INVALID_REQUEST, "Missing required field '%s'" % field)
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        errors.raise_error(errors.ERR_INVALID_REQUEST, "Field '%s' must be an integer" % field)
    return v


def _check_session_occ(session, expected):
    if expected != session["version"]:
        errors.raise_error(errors.ERR_STALE_SESSION_VERSION, "Stale session version")


def _session_bookings(session_id):
    items = [b for b in db.store.bookings.values() if b["session_id"] == session_id]
    items.sort(key=lambda b: (b["created_at"], b["_seq"]))
    return items


def _has_time_overlap(member_id, session):
    s1, e1 = session["starts_at"], session["ends_at"]
    for b in db.store.bookings.values():
        if b["member_id"] != member_id:
            continue
        if b["status"] not in ("BOOKED", "WAITLISTED"):
            continue
        other = db.store.class_sessions.get(b["session_id"])
        if other is None:
            continue
        s2, e2 = other["starts_at"], other["ends_at"]
        # Half-open [starts, ends) overlap.
        if s1 < e2 and s2 < e1:
            return True
    return False


def _has_open_checkin(member_id, location_id):
    for c in db.store.check_ins.values():
        if (c["member_id"] == member_id and c["location_id"] == location_id
                and c["status"] == "OPEN"):
            return True
    return False
