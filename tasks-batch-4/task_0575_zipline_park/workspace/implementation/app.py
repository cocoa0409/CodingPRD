"""Aerial Adventure & Zipline Park API (task_0575) — Flask reference implementation."""
import os
from datetime import timedelta
from decimal import Decimal

from flask import Flask, jsonify, request

from helpers import (
    ApiError, ALL_ROLES, ROLE_OPERATOR, ROLE_CUSTOMER, ROLE_GUIDE,
    gen_request_id, wall_now, fmt_dt, parse_dt, round_half_up,
)
from store import store
import logic
from logic import (
    ACTIVE_BOOKING, WAIVER_VALID_DAYS, CLEANING_BUFFER_MINUTES,
    VOLUNTARY_FULL_REFUND_HOURS, VOLUNTARY_LATE_REFUND_PCT,
    serialize_course, serialize_time_slot, serialize_guide, serialize_participant,
    serialize_season_pass, serialize_group, serialize_booking,
    serialize_guide_assignment, serialize_gear_item, serialize_gear_checkout,
    serialize_incident_report,
)

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def _meta(extra=None):
    m = {"api_request_id": gen_request_id(),
         "api_request_timestamp": fmt_dt(wall_now())}
    if extra:
        m.update(extra)
    return m


def ok(data, code=200, response_type="object", extra_meta=None):
    return jsonify({"meta": _meta(extra_meta),
                    "response_type": response_type,
                    "data": data}), code


def ok_list(items, serializer):
    limit, offset = _pagination()
    total = len(items)
    page = items[offset:offset + limit]
    data = [serializer(x) for x in page]
    extra = {"limit": limit, "offset": offset,
             "total_count": total, "has_more": offset + limit < total}
    return ok(data, 200, "array", extra)


@app.errorhandler(ApiError)
def _handle_api_error(e):
    return jsonify({"meta": _meta(),
                    "response_type": "error",
                    "data": {"error_id": e.error_id, "message": e.message}}), e.http_status


@app.errorhandler(404)
def _handle_404(e):
    return jsonify({"meta": _meta(), "response_type": "error",
                    "data": {"error_id": "ERR_NOT_FOUND", "message": "Not found"}}), 404


@app.errorhandler(405)
def _handle_405(e):
    return jsonify({"meta": _meta(), "response_type": "error",
                    "data": {"error_id": "ERR_NOT_FOUND", "message": "Method not allowed"}}), 404


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------
def require_auth():
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if not role or not uid or role not in ALL_ROLES:
        raise ApiError(401, "ERR_UNAUTHENTICATED", "Missing or malformed auth headers")
    return uid, role


def authorize(role, allowed):
    if role not in allowed:
        raise ApiError(403, "ERR_UNAUTHORIZED", "Role not permitted for this operation")


# ---------------------------------------------------------------------------
# Body / query helpers
# ---------------------------------------------------------------------------
def get_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError(400, "ERR_VALIDATION", "Request body must be a JSON object")
    return body


def _pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        try:
            limit = int(args["limit"])
        except (ValueError, TypeError):
            limit = 10
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if "offset" in args:
        try:
            offset = int(args["offset"])
        except (ValueError, TypeError):
            offset = 0
    if offset < 0:
        offset = 0
    return limit, offset


def require_present(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise ApiError(400, "ERR_VALIDATION", "Missing required field: %s" % f)


def is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def parse_dt_or_400(v, field):
    try:
        return parse_dt(v)
    except ValueError:
        raise ApiError(400, "ERR_VALIDATION", "Invalid datetime for %s" % field)


# ---------------------------------------------------------------------------
# Existence helpers
# ---------------------------------------------------------------------------
def get_or_404(coll, rid):
    rec = coll.get(rid)
    if rec is None:
        raise ApiError(404, "ERR_NOT_FOUND", "Resource not found")
    return rec


def sorted_records(coll, predicate=None):
    recs = [r for r in coll.values() if (predicate is None or predicate(r))]
    recs.sort(key=lambda r: r["_seq"])
    return recs


# ---------------------------------------------------------------------------
# Cascade helpers
# ---------------------------------------------------------------------------
def return_booking_gear(booking):
    for c in store.gear_checkouts.values():
        if c["booking_id"] == booking["id"] and c["status"] == "OUT":
            c["status"] = "RETURNED"
            c["returned_at"] = store.clock
            store.touch(c)


def voluntary_credit(booking):
    slot = store.time_slots[booking["time_slot_id"]]
    lead_seconds = (slot["start_at"] - store.clock).total_seconds()
    lead_hours = lead_seconds / 3600.0
    price = booking["price_cents"]
    if lead_hours >= VOLUNTARY_FULL_REFUND_HOURS:
        return price
    return round_half_up(Decimal(price) * VOLUNTARY_LATE_REFUND_PCT)


# ===========================================================================
# Logical clock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _uid, role = require_auth()
    authorize(role, {ROLE_OPERATOR})
    body = get_body()
    require_present(body, ["to_iso8601"])
    store.clock = parse_dt_or_400(body["to_iso8601"], "to_iso8601")
    return ok({}, 200)


# ===========================================================================
# Course
# ===========================================================================
@app.route("/courses", methods=["POST"])
def create_course():
    _uid, role = require_auth()
    authorize(role, {ROLE_OPERATOR})
    body = get_body()
    require_present(body, ["name", "difficulty_level", "min_weight_kg", "max_weight_kg",
                           "min_age_years", "base_price_cents", "duration_minutes",
                           "default_capacity", "max_participants_per_guide",
                           "weekend_surcharge_pct"])
    dl = body["difficulty_level"]
    if not is_int(dl) or dl < 1 or dl > 5:
        raise ApiError(400, "ERR_VALIDATION", "difficulty_level must be an integer 1..5")
    for f in ("min_weight_kg", "max_weight_kg", "base_price_cents", "duration_minutes",
              "default_capacity", "max_participants_per_guide", "weekend_surcharge_pct",
              "min_age_years"):
        if not is_number(body[f]):
            raise ApiError(400, "ERR_VALIDATION", "%s must be numeric" % f)
    rec = store.new_record()
    rec.update({
        "name": body["name"],
        "difficulty_level": dl,
        "min_weight_kg": body["min_weight_kg"],
        "max_weight_kg": body["max_weight_kg"],
        "min_age_years": body["min_age_years"],
        "base_price_cents": body["base_price_cents"],
        "duration_minutes": body["duration_minutes"],
        "default_capacity": body["default_capacity"],
        "max_participants_per_guide": body["max_participants_per_guide"],
        "weekend_surcharge_pct": body["weekend_surcharge_pct"],
    })
    store.courses[rec["id"]] = rec
    return ok(serialize_course(rec), 201)


@app.route("/courses/<cid>", methods=["GET"])
def get_course(cid):
    _uid, role = require_auth()
    authorize(role, ALL_ROLES)
    c = get_or_404(store.courses, cid)
    return ok(serialize_course(c))


@app.route("/courses/<cid>/time-slots", methods=["GET"])
def list_course_time_slots(cid):
    _uid, role = require_auth()
    authorize(role, ALL_ROLES)
    get_or_404(store.courses, cid)
    recs = sorted_records(store.time_slots, lambda s: s["course_id"] == cid)
    return ok_list(recs, serialize_time_slot)


# ===========================================================================
# TimeSlot
# ===========================================================================
@app.route("/time-slots", methods=["POST"])
def create_time_slot():
    _uid, role = require_auth()
    authorize(role, {ROLE_OPERATOR})
    body = get_body()
    # existence of course FK (priority 3) before body well-formedness of other fields
    if body.get("course_id") is not None:
        course = store.courses.get(body["course_id"])
        if course is None:
            raise ApiError(404, "ERR_NOT_FOUND", "Course not found")
    require_present(body, ["course_id", "start_at"])
    course = store.courses[body["course_id"]]
    start_at = parse_dt_or_400(body["start_at"], "start_at")
    if "capacity" in body and body["capacity"] is not None:
        if not is_int(body["capacity"]):
            raise ApiError(400, "ERR_VALIDATION", "capacity must be an integer")
        capacity = body["capacity"]
    else:
        capacity = course["default_capacity"]
    rec = store.new_record()
    rec.update({
        "course_id": course["id"],
        "start_at": start_at,
        "end_at": start_at + timedelta(minutes=course["duration_minutes"]),
        "capacity": capacity,
        "status": "SCHEDULED",
        "closure_reason": None,
    })
    store.time_slots[rec["id"]] = rec
    return ok(serialize_time_slot(rec), 201)


@app.route("/time-slots/<sid>", methods=["GET"])
def get_time_slot(sid):
    _uid, role = require_auth()
    authorize(role, ALL_ROLES)
    s = get_or_404(store.time_slots, sid)
    return ok(serialize_time_slot(s))


@app.route("/time-slots/<sid>/open", methods=["POST"])
def open_time_slot(sid):
    _uid, role = require_auth()
    authorize(role, {ROLE_OPERATOR})
    s = get_or_404(store.time_slots, sid)
    if s["status"] not in ("SCHEDULED", "CLOSED"):
        raise ApiError(409, "ERR_INVALID_STATE", "Slot cannot be opened from %s" % s["status"])
    if logic.slot_assigned_guide_count(sid) < 1:
        raise ApiError(409, "ERR_NO_GUIDE_ASSIGNED", "Slot has no assigned guide")
    s["status"] = "OPEN"
    s["closure_reason"] = None
    store.touch(s)
    return ok(serialize_time_slot(s))


@app.route("/time-slots/<sid>/close", methods=["POST"])
def close_time_slot(sid):
    _uid, role = require_auth()
    authorize(role, {ROLE_OPERATOR})
    s = get_or_404(store.time_slots, sid)
    if s["status"] not in ("SCHEDULED", "OPEN"):
        raise ApiError(409, "ERR_INVALID_STATE", "Slot cannot be closed from %s" % s["status"])
    body = get_body()
    reason = body.get("reason")
    s["status"] = "CLOSED"
    s["closure_reason"] = reason
    store.touch(s)
    # Cascade: active bookings -> RAINCHECKED with full weather credit
    for b in list(store.bookings.values()):
        if b["time_slot_id"] == sid and b["status"] in ACTIVE_BOOKING:
            b["status"] = "RAINCHECKED"
            b["raincheck_credit_cents"] = b["price_cents"]
            store.touch(b)
            return_booking_gear(b)
    return ok(serialize_time_slot(s))


@app.route("/time-slots/<sid>/complete", methods=["POST"])
def complete_time_slot(sid):
    _uid, role = require_auth()
    authorize(role, {ROLE_OPERATOR})
    s = get_or_404(store.time_slots, sid)
    if s["status"] != "OPEN":
        raise ApiError(409, "ERR_INVALID_STATE", "Slot cannot be completed from %s" % s["status"])
    s["status"] = "COMPLETED"
    store.touch(s)
    for b in list(store.bookings.values()):
        if b["time_slot_id"] == sid and b["status"] in ACTIVE_BOOKING:
            b["status"] = "NO_SHOW"
            store.touch(b)
            return_booking_gear(b)
    return ok(serialize_time_slot(s))


@app.route("/time-slots/<sid>/groups", methods=["GET"])
def list_slot_groups(sid):
    _uid, role = require_auth()
    authorize(role, ALL_ROLES)
    get_or_404(store.time_slots, sid)
    recs = sorted_records(store.groups, lambda g: g["time_slot_id"] == sid)
    return ok_list(recs, serialize_group)


# ===========================================================================
# Guide
# ===========================================================================
@app.route("/guides", methods=["POST"])
def create_guide():
    _uid, role = require_auth()
    authorize(role, {ROLE_OPERATOR})
    body = get_body()
    require_present(body, ["name", "certification_level"])
    cl = body["certification_level"]
    if not is_int(cl) or cl < 1 or cl > 5:
        raise ApiError(400, "ERR_VALIDATION", "certification_level must be an integer 1..5")
    rec = store.new_record()
    rec.update({"name": body["name"], "certification_level": cl})
    store.guides[rec["id"]] = rec
    return ok(serialize_guide(rec), 201)


@app.route("/guides/<gid>", methods=["GET"])
def get_guide(gid):
    _uid, role = require_auth()
    authorize(role, ALL_ROLES)
    g = get_or_404(store.guides, gid)
    return ok(serialize_guide(g))


# ===========================================================================
# GuideAssignment
# ===========================================================================
@app.route("/guide-assignments", methods=["POST"])
def create_guide_assignment():
    _uid, role = require_auth()
    authorize(role, {ROLE_OPERATOR})
    body = get_body()
    # existence (left-to-right: guide, slot)
    if body.get("guide_id") is not None and body["guide_id"] not in store.guides:
        raise ApiError(404, "ERR_NOT_FOUND", "Guide not found")
    if body.get("time_slot_id") is not None and body["time_slot_id"] not in store.time_slots:
        raise ApiError(404, "ERR_NOT_FOUND", "TimeSlot not found")
    require_present(body, ["guide_id", "time_slot_id"])
    guide = store.guides[body["guide_id"]]
    slot = store.time_slots[body["time_slot_id"]]
    course = store.courses[slot["course_id"]]
    # safety: certification
    if guide["certification_level"] < course["difficulty_level"]:
        raise ApiError(422, "ERR_GUIDE_UNCERTIFIED", "Guide not certified for this course")
    # operational: no double-booking (half-open overlap)
    for a in store.guide_assignments.values():
        if a["guide_id"] == guide["id"] and a["status"] == "ASSIGNED":
            other = store.time_slots[a["time_slot_id"]]
            if slot["start_at"] < other["end_at"] and other["start_at"] < slot["end_at"]:
                raise ApiError(409, "ERR_GUIDE_DOUBLE_BOOKED", "Guide already assigned to an overlapping slot")
    rec = store.new_record()
    rec.update({"guide_id": guide["id"], "time_slot_id": slot["id"], "status": "ASSIGNED"})
    store.guide_assignments[rec["id"]] = rec
    return ok(serialize_guide_assignment(rec), 201)


@app.route("/guide-assignments/<aid>", methods=["GET"])
def get_guide_assignment(aid):
    _uid, role = require_auth()
    authorize(role, ALL_ROLES)
    a = get_or_404(store.guide_assignments, aid)
    return ok(serialize_guide_assignment(a))


@app.route("/guide-assignments", methods=["GET"])
def list_guide_assignments():
    _uid, role = require_auth()
    authorize(role, ALL_ROLES)
    guide_id = request.args.get("guide_id")
    time_slot_id = request.args.get("time_slot_id")

    def pred(a):
        if guide_id is not None and a["guide_id"] != guide_id:
            return False
        if time_slot_id is not None and a["time_slot_id"] != time_slot_id:
            return False
        return True

    return ok_list(sorted_records(store.guide_assignments, pred), serialize_guide_assignment)


@app.route("/guide-assignments/<aid>/cancel", methods=["POST"])
def cancel_guide_assignment(aid):
    _uid, role = require_auth()
    authorize(role, {ROLE_OPERATOR})
    a = get_or_404(store.guide_assignments, aid)
    if a["status"] != "ASSIGNED":
        raise ApiError(409, "ERR_INVALID_STATE", "Assignment is not ASSIGNED")
    slot = store.time_slots[a["time_slot_id"]]
    course = store.courses[slot["course_id"]]
    assigned_count = logic.slot_assigned_guide_count(slot["id"])
    remaining_capacity = (assigned_count - 1) * course["max_participants_per_guide"]
    if remaining_capacity < logic.slot_booked_count(slot["id"]):
        raise ApiError(409, "ERR_UNDERSTAFFED", "Cancelling would understaff the slot")
    a["status"] = "CANCELLED"
    store.touch(a)
    return ok(serialize_guide_assignment(a))


# ===========================================================================
# Participant
# ===========================================================================
@app.route("/participants", methods=["POST"])
def create_participant():
    _uid, role = require_auth()
    authorize(role, {ROLE_OPERATOR, ROLE_CUSTOMER})
    body = get_body()
    require_present(body, ["full_name", "weight_kg", "birthdate"])
    if not is_number(body["weight_kg"]):
        raise ApiError(400, "ERR_VALIDATION", "weight_kg must be numeric")
    birthdate = parse_dt_or_400(body["birthdate"], "birthdate")
    rec = store.new_record()
    rec.update({
        "full_name": body["full_name"],
        "weight_kg": body["weight_kg"],
        "birthdate": birthdate,
        "waiver_signed_at": None,
        "waiver_expires_at": None,
    })
    store.participants[rec["id"]] = rec
    return ok(serialize_participant(rec), 201)


@app.route("/participants/<pid>", methods=["GET"])
def get_participant(pid):
    _uid, role = require_auth()
    authorize(role, ALL_ROLES)
    p = get_or_404(store.participants, pid)
    return ok(serialize_participant(p))


@app.route("/participants/<pid>/waiver", methods=["POST"])
def sign_waiver(pid):
    uid, role = require_auth()
    authorize(role, {ROLE_OPERATOR, ROLE_CUSTOMER})
    p = get_or_404(store.participants, pid)
    body = get_body()
    require_present(body, ["signature_name"])
    if role == ROLE_CUSTOMER and uid != pid:
        raise ApiError(403, "ERR_UNAUTHORIZED", "Customer may only sign their own waiver")
    p["waiver_signed_at"] = store.clock
    p["waiver_expires_at"] = store.clock + timedelta(days=WAIVER_VALID_DAYS)
    store.touch(p)
    return ok(serialize_participant(p))


@app.route("/participants/<pid>/season-passes", methods=["POST"])
def create_season_pass(pid):
    _uid, role = require_auth()
    authorize(role, {ROLE_OPERATOR})
    p = get_or_404(store.participants, pid)
    body = get_body()
    require_present(body, ["tier", "valid_from", "valid_until", "total_uses",
                           "expected_participant_version"])
    if body["tier"] not in ("STANDARD", "PREMIUM"):
        raise ApiError(400, "ERR_VALIDATION", "tier must be STANDARD or PREMIUM")
    if not is_int(body["total_uses"]):
        raise ApiError(400, "ERR_VALIDATION", "total_uses must be an integer")
    if not is_int(body["expected_participant_version"]):
        raise ApiError(400, "ERR_VALIDATION", "expected_participant_version must be an integer")
    valid_from = parse_dt_or_400(body["valid_from"], "valid_from")
    valid_until = parse_dt_or_400(body["valid_until"], "valid_until")
    if not (valid_until > valid_from):
        raise ApiError(400, "ERR_VALIDATION", "valid_until must be after valid_from")
    # concurrency (last)
    if body["expected_participant_version"] != p["version"]:
        raise ApiError(412, "ERR_STALE_VERSION", "Stale participant version")
    # supersede prior ACTIVE pass
    for sp in store.season_passes.values():
        if sp["participant_id"] == pid and sp["status"] == "ACTIVE":
            sp["status"] = "SUPERSEDED"
            store.touch(sp)
    rec = store.new_record()
    rec.update({
        "participant_id": pid,
        "tier": body["tier"],
        "valid_from": valid_from,
        "valid_until": valid_until,
        "total_uses": body["total_uses"],
        "status": "ACTIVE",
    })
    store.season_passes[rec["id"]] = rec
    store.touch(p)  # participant version += 1
    return ok(serialize_season_pass(rec), 201)


@app.route("/participants/<pid>/season-passes", methods=["GET"])
def list_season_passes(pid):
    _uid, role = require_auth()
    authorize(role, ALL_ROLES)
    get_or_404(store.participants, pid)
    recs = sorted_records(store.season_passes, lambda s: s["participant_id"] == pid)
    return ok_list(recs, serialize_season_pass)


# ===========================================================================
# GearItem
# ===========================================================================
@app.route("/gear-items", methods=["POST"])
def create_gear_item():
    _uid, role = require_auth()
    authorize(role, {ROLE_OPERATOR})
    body = get_body()
    require_present(body, ["gear_type", "size"])
    if body["gear_type"] not in ("HARNESS", "HELMET"):
        raise ApiError(400, "ERR_VALIDATION", "gear_type must be HARNESS or HELMET")
    if body["size"] not in ("S", "M", "L"):
        raise ApiError(400, "ERR_VALIDATION", "size must be S, M, or L")
    rec = store.new_record()
    rec.update({"gear_type": body["gear_type"], "size": body["size"]})
    store.gear_items[rec["id"]] = rec
    return ok(serialize_gear_item(rec), 201)


@app.route("/gear-items/<gid>", methods=["GET"])
def get_gear_item(gid):
    _uid, role = require_auth()
    authorize(role, ALL_ROLES)
    g = get_or_404(store.gear_items, gid)
    return ok(serialize_gear_item(g))


# ===========================================================================
# Group
# ===========================================================================
@app.route("/groups", methods=["POST"])
def create_group():
    _uid, role = require_auth()
    authorize(role, {ROLE_OPERATOR, ROLE_CUSTOMER})
    body = get_body()
    if body.get("time_slot_id") is not None and body["time_slot_id"] not in store.time_slots:
        raise ApiError(404, "ERR_NOT_FOUND", "TimeSlot not found")
    require_present(body, ["name", "time_slot_id", "expected_size", "organizer_name"])
    if not is_int(body["expected_size"]):
        raise ApiError(400, "ERR_VALIDATION", "expected_size must be an integer")
    rec = store.new_record()
    rec.update({
        "name": body["name"],
        "time_slot_id": body["time_slot_id"],
        "expected_size": body["expected_size"],
        "organizer_name": body["organizer_name"],
        "organizer_participant_id": body.get("organizer_participant_id"),
        "status": "OPEN",
    })
    store.groups[rec["id"]] = rec
    return ok(serialize_group(rec), 201)


@app.route("/groups/<gid>", methods=["GET"])
def get_group(gid):
    _uid, role = require_auth()
    authorize(role, ALL_ROLES)
    g = get_or_404(store.groups, gid)
    return ok(serialize_group(g))


@app.route("/groups/<gid>/cancel", methods=["POST"])
def cancel_group(gid):
    _uid, role = require_auth()
    authorize(role, {ROLE_OPERATOR, ROLE_CUSTOMER})
    g = get_or_404(store.groups, gid)
    if g["status"] != "OPEN":
        raise ApiError(409, "ERR_INVALID_STATE", "Group is not OPEN")
    g["status"] = "CANCELLED"
    store.touch(g)
    for b in list(store.bookings.values()):
        if b.get("group_id") == gid and b["status"] in ACTIVE_BOOKING:
            b["raincheck_credit_cents"] = voluntary_credit(b)
            b["status"] = "CANCELLED"
            store.touch(b)
            return_booking_gear(b)
    return ok(serialize_group(g))


# ===========================================================================
# Booking
# ===========================================================================
@app.route("/bookings", methods=["POST"])
def create_booking():
    _uid, role = require_auth()
    authorize(role, {ROLE_OPERATOR, ROLE_CUSTOMER})
    body = get_body()
    # existence (left-to-right: time_slot, participant, group)
    if body.get("time_slot_id") is not None and body["time_slot_id"] not in store.time_slots:
        raise ApiError(404, "ERR_NOT_FOUND", "TimeSlot not found")
    if body.get("participant_id") is not None and body["participant_id"] not in store.participants:
        raise ApiError(404, "ERR_NOT_FOUND", "Participant not found")
    if body.get("group_id") is not None and body["group_id"] not in store.groups:
        raise ApiError(404, "ERR_NOT_FOUND", "Group not found")
    require_present(body, ["time_slot_id", "participant_id"])
    use_pass = body.get("use_season_pass", False)
    if not isinstance(use_pass, bool):
        raise ApiError(400, "ERR_VALIDATION", "use_season_pass must be a boolean")
    slot = store.time_slots[body["time_slot_id"]]
    participant = store.participants[body["participant_id"]]
    course = store.courses[slot["course_id"]]
    group = store.groups[body["group_id"]] if body.get("group_id") else None
    # safety: weight, age
    if not (course["min_weight_kg"] <= participant["weight_kg"] <= course["max_weight_kg"]):
        raise ApiError(422, "ERR_WEIGHT_OUT_OF_RANGE", "Participant weight out of range")
    if logic.participant_age_years(participant) < course["min_age_years"]:
        raise ApiError(422, "ERR_AGE_BELOW_MINIMUM", "Participant below minimum age")
    # operational: group/slot agreement
    if group is not None and group["time_slot_id"] != slot["id"]:
        raise ApiError(422, "ERR_GROUP_SLOT_MISMATCH", "Group is on a different slot")
    # fiscal: capacity
    booked = logic.slot_booked_count(slot["id"])
    ceiling = min(slot["capacity"], logic.slot_assigned_capacity(slot))
    if logic.slot_remaining_capacity(slot) < 1 or booked + 1 > ceiling:
        raise ApiError(409, "ERR_SLOT_FULL", "Slot is full")
    # fiscal: season pass
    chosen_pass = None
    if use_pass:
        chosen_pass = logic.find_active_pass(participant["id"])
        if chosen_pass is None or not (chosen_pass["valid_from"] <= store.clock <= chosen_pass["valid_until"]):
            raise ApiError(422, "ERR_SEASON_PASS_INVALID", "Season pass not usable")
        if logic.pass_uses_remaining(chosen_pass) < 1:
            raise ApiError(422, "ERR_SEASON_PASS_EXHAUSTED", "Season pass exhausted")
    # pricing
    if chosen_pass is not None:
        price = 0
        season_pass_id = chosen_pass["id"]
    else:
        price = logic.compute_booking_price(course, slot, group)
        season_pass_id = None
    rec = store.new_record()
    rec.update({
        "time_slot_id": slot["id"],
        "participant_id": participant["id"],
        "group_id": body.get("group_id"),
        "season_pass_id": season_pass_id,
        "use_season_pass": use_pass,
        "status": "CONFIRMED",
        "price_cents": price,
        "raincheck_credit_cents": 0,
        "redeemed_from_booking_id": None,
    })
    store.bookings[rec["id"]] = rec
    return ok(serialize_booking(rec), 201)


@app.route("/bookings/<bid>", methods=["GET"])
def get_booking(bid):
    _uid, role = require_auth()
    authorize(role, ALL_ROLES)
    b = get_or_404(store.bookings, bid)
    return ok(serialize_booking(b))


@app.route("/bookings", methods=["GET"])
def list_bookings():
    _uid, role = require_auth()
    authorize(role, ALL_ROLES)
    time_slot_id = request.args.get("time_slot_id")
    participant_id = request.args.get("participant_id")
    group_id = request.args.get("group_id")
    season_pass_id = request.args.get("season_pass_id")

    def pred(b):
        if time_slot_id is not None and b["time_slot_id"] != time_slot_id:
            return False
        if participant_id is not None and b["participant_id"] != participant_id:
            return False
        if group_id is not None and b.get("group_id") != group_id:
            return False
        if season_pass_id is not None and b.get("season_pass_id") != season_pass_id:
            return False
        return True

    return ok_list(sorted_records(store.bookings, pred), serialize_booking)


@app.route("/bookings/<bid>/check-in", methods=["POST"])
def check_in_booking(bid):
    _uid, role = require_auth()
    authorize(role, {ROLE_OPERATOR, ROLE_GUIDE})
    b = get_or_404(store.bookings, bid)
    if b["status"] != "CONFIRMED":
        raise ApiError(409, "ERR_INVALID_STATE", "Booking is not CONFIRMED")
    slot = store.time_slots[b["time_slot_id"]]
    if slot["status"] != "OPEN":
        raise ApiError(409, "ERR_SLOT_NOT_OPEN", "Slot is not OPEN")
    participant = store.participants[b["participant_id"]]
    if logic.participant_waiver_status(participant) != "SIGNED":
        raise ApiError(422, "ERR_WAIVER_REQUIRED", "Waiver required")
    b["status"] = "CHECKED_IN"
    store.touch(b)
    return ok(serialize_booking(b))


@app.route("/bookings/<bid>/brief", methods=["POST"])
def brief_booking(bid):
    _uid, role = require_auth()
    authorize(role, {ROLE_OPERATOR, ROLE_GUIDE})
    b = get_or_404(store.bookings, bid)
    if b["status"] != "CHECKED_IN":
        raise ApiError(409, "ERR_INVALID_STATE", "Booking is not CHECKED_IN")
    slot = store.time_slots[b["time_slot_id"]]
    if logic.slot_assigned_guide_count(slot["id"]) < 1:
        raise ApiError(409, "ERR_NO_GUIDE_ASSIGNED", "Slot has no assigned guide")
    b["status"] = "BRIEFED"
    store.touch(b)
    return ok(serialize_booking(b))


@app.route("/bookings/<bid>/complete", methods=["POST"])
def complete_booking(bid):
    _uid, role = require_auth()
    authorize(role, {ROLE_OPERATOR, ROLE_GUIDE})
    b = get_or_404(store.bookings, bid)
    if b["status"] != "BRIEFED":
        raise ApiError(409, "ERR_INVALID_STATE", "Booking is not BRIEFED")
    slot = store.time_slots[b["time_slot_id"]]
    if slot["status"] != "OPEN":
        raise ApiError(409, "ERR_SLOT_NOT_OPEN", "Slot is not OPEN")
    b["status"] = "COMPLETED"
    store.touch(b)
    return_booking_gear(b)
    return ok(serialize_booking(b))


@app.route("/bookings/<bid>/cancel", methods=["POST"])
def cancel_booking(bid):
    uid, role = require_auth()
    authorize(role, {ROLE_OPERATOR, ROLE_CUSTOMER})
    b = get_or_404(store.bookings, bid)
    if role == ROLE_CUSTOMER and b["participant_id"] != uid:
        raise ApiError(403, "ERR_UNAUTHORIZED", "Customer may only cancel their own booking")
    if b["status"] not in ACTIVE_BOOKING:
        raise ApiError(409, "ERR_INVALID_STATE", "Booking cannot be cancelled from %s" % b["status"])
    b["raincheck_credit_cents"] = voluntary_credit(b)
    b["status"] = "CANCELLED"
    store.touch(b)
    return_booking_gear(b)
    return ok(serialize_booking(b))


@app.route("/bookings/<bid>/redeem", methods=["POST"])
def redeem_booking(bid):
    uid, role = require_auth()
    authorize(role, {ROLE_OPERATOR, ROLE_CUSTOMER})
    b = get_or_404(store.bookings, bid)
    body = get_body()
    if body.get("time_slot_id") is not None and body["time_slot_id"] not in store.time_slots:
        raise ApiError(404, "ERR_NOT_FOUND", "TimeSlot not found")
    require_present(body, ["time_slot_id"])
    if role == ROLE_CUSTOMER and b["participant_id"] != uid:
        raise ApiError(403, "ERR_UNAUTHORIZED", "Customer may only redeem their own booking")
    if b["status"] != "RAINCHECKED":
        raise ApiError(409, "ERR_INVALID_STATE", "Booking is not RAINCHECKED")
    target = store.time_slots[body["time_slot_id"]]
    course = store.courses[target["course_id"]]
    participant = store.participants[b["participant_id"]]
    # safety: weight, age (before fiscal capacity)
    if not (course["min_weight_kg"] <= participant["weight_kg"] <= course["max_weight_kg"]):
        raise ApiError(422, "ERR_WEIGHT_OUT_OF_RANGE", "Participant weight out of range")
    if logic.participant_age_years(participant) < course["min_age_years"]:
        raise ApiError(422, "ERR_AGE_BELOW_MINIMUM", "Participant below minimum age")
    # fiscal: target slot must be SCHEDULED/OPEN with a free seat
    if target["status"] not in ("SCHEDULED", "OPEN") or logic.slot_remaining_capacity(target) < 1:
        raise ApiError(409, "ERR_SLOT_FULL", "Target slot not available")
    # original -> REDEEMED
    b["status"] = "REDEEMED"
    store.touch(b)
    new_price = max(0, logic.compute_booking_price(course, target, None) - b["raincheck_credit_cents"])
    rec = store.new_record()
    rec.update({
        "time_slot_id": target["id"],
        "participant_id": participant["id"],
        "group_id": None,
        "season_pass_id": None,
        "use_season_pass": False,
        "status": "CONFIRMED",
        "price_cents": new_price,
        "raincheck_credit_cents": 0,
        "redeemed_from_booking_id": b["id"],
    })
    store.bookings[rec["id"]] = rec
    return ok(serialize_booking(rec), 201)


@app.route("/bookings/<bid>/incident-reports", methods=["GET"])
def list_booking_incidents(bid):
    _uid, role = require_auth()
    authorize(role, ALL_ROLES)
    get_or_404(store.bookings, bid)
    recs = sorted_records(store.incident_reports, lambda r: r["booking_id"] == bid)
    return ok_list(recs, serialize_incident_report)


# ===========================================================================
# GearCheckout
# ===========================================================================
@app.route("/gear-checkouts", methods=["POST"])
def create_gear_checkout():
    _uid, role = require_auth()
    authorize(role, {ROLE_OPERATOR, ROLE_GUIDE})
    body = get_body()
    if body.get("gear_item_id") is not None and body["gear_item_id"] not in store.gear_items:
        raise ApiError(404, "ERR_NOT_FOUND", "GearItem not found")
    if body.get("booking_id") is not None and body["booking_id"] not in store.bookings:
        raise ApiError(404, "ERR_NOT_FOUND", "Booking not found")
    require_present(body, ["gear_item_id", "booking_id"])
    item = store.gear_items[body["gear_item_id"]]
    booking = store.bookings[body["booking_id"]]
    slot = store.time_slots[booking["time_slot_id"]]
    window_start = slot["start_at"]
    window_end = slot["end_at"] + timedelta(minutes=CLEANING_BUFFER_MINUTES)
    # operational: no overlapping OUT checkout on this item (half-open windows)
    for c in store.gear_checkouts.values():
        if c["gear_item_id"] == item["id"] and c["status"] == "OUT":
            if window_start < c["window_end"] and c["window_start"] < window_end:
                raise ApiError(409, "ERR_GEAR_UNAVAILABLE", "Gear window overlaps an existing checkout")
    rec = store.new_record()
    rec.update({
        "gear_item_id": item["id"],
        "booking_id": booking["id"],
        "window_start": window_start,
        "window_end": window_end,
        "checked_out_at": store.clock,
        "returned_at": None,
        "status": "OUT",
    })
    store.gear_checkouts[rec["id"]] = rec
    return ok(serialize_gear_checkout(rec), 201)


@app.route("/gear-checkouts/<cid>", methods=["GET"])
def get_gear_checkout(cid):
    _uid, role = require_auth()
    authorize(role, ALL_ROLES)
    c = get_or_404(store.gear_checkouts, cid)
    return ok(serialize_gear_checkout(c))


@app.route("/gear-checkouts", methods=["GET"])
def list_gear_checkouts():
    _uid, role = require_auth()
    authorize(role, ALL_ROLES)
    gear_item_id = request.args.get("gear_item_id")
    booking_id = request.args.get("booking_id")

    def pred(c):
        if gear_item_id is not None and c["gear_item_id"] != gear_item_id:
            return False
        if booking_id is not None and c["booking_id"] != booking_id:
            return False
        return True

    return ok_list(sorted_records(store.gear_checkouts, pred), serialize_gear_checkout)


@app.route("/gear-checkouts/<cid>/return", methods=["POST"])
def return_gear_checkout(cid):
    _uid, role = require_auth()
    authorize(role, {ROLE_OPERATOR, ROLE_GUIDE})
    c = get_or_404(store.gear_checkouts, cid)
    if c["status"] != "OUT":
        raise ApiError(409, "ERR_INVALID_STATE", "Checkout is not OUT")
    c["status"] = "RETURNED"
    c["returned_at"] = store.clock
    store.touch(c)
    return ok(serialize_gear_checkout(c))


# ===========================================================================
# IncidentReport
# ===========================================================================
@app.route("/incident-reports", methods=["POST"])
def create_incident_report():
    _uid, role = require_auth()
    authorize(role, {ROLE_OPERATOR, ROLE_GUIDE})
    body = get_body()
    if body.get("booking_id") is not None and body["booking_id"] not in store.bookings:
        raise ApiError(404, "ERR_NOT_FOUND", "Booking not found")
    require_present(body, ["booking_id", "severity", "description", "reported_by_guide_id"])
    if body["severity"] not in ("MINOR", "MODERATE", "SEVERE"):
        raise ApiError(400, "ERR_VALIDATION", "severity must be MINOR, MODERATE, or SEVERE")
    rec = store.new_record(versioned=False)
    rec.update({
        "booking_id": body["booking_id"],
        "severity": body["severity"],
        "description": body["description"],
        "reported_by_guide_id": body["reported_by_guide_id"],
        "occurred_at": store.clock,
    })
    store.incident_reports[rec["id"]] = rec
    return ok(serialize_incident_report(rec), 201)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
