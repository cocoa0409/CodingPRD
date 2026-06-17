"""Music & Arts Lesson Studio API — Flask entry point.

Storage is purely in-memory (see db.py); starts empty on every boot. No seeding.
"""
import os

from flask import Flask, request

import db
import errors
import helpers
import services
from middleware import require_auth, require_role
from response import success, error

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
@app.errorhandler(errors.ApiError)
def handle_api_error(exc):
    return error(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(404)
def handle_404(exc):
    return error("ERR_STUDIO_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_405(exc):
    return error("ERR_INVALID_REQUEST", "Method not allowed", 422)


@app.errorhandler(Exception)
def handle_unexpected(exc):
    if isinstance(exc, errors.ApiError):
        return error(exc.error_id, exc.message, exc.http_status)
    return error("ERR_INVALID_REQUEST", "Unexpected error: %s" % exc, 422)


# ===========================================================================
# Studio
# ===========================================================================
DEFAULT_TIERS = [
    {"min_active_enrollments": 1, "discount_pct": 0},
    {"min_active_enrollments": 2, "discount_pct": 0.05},
    {"min_active_enrollments": 3, "discount_pct": 0.10},
    {"min_active_enrollments": 4, "discount_pct": 0.15},
]


def _validate_tiers(value):
    if not isinstance(value, list) or not value:
        errors.raise_error(errors.ERR_INVALID_REQUEST, "family_discount_tiers must be a non-empty array")
    out = []
    for t in value:
        if not isinstance(t, dict):
            errors.raise_error(errors.ERR_INVALID_REQUEST, "tier must be an object")
        mae = t.get("min_active_enrollments")
        dp = t.get("discount_pct")
        if isinstance(mae, bool) or not isinstance(mae, int):
            errors.raise_error(errors.ERR_INVALID_REQUEST, "min_active_enrollments must be int")
        if isinstance(dp, bool) or not isinstance(dp, (int, float)):
            errors.raise_error(errors.ERR_INVALID_REQUEST, "discount_pct must be a number")
        out.append({"min_active_enrollments": mae, "discount_pct": dp})
    out.sort(key=lambda t: t["min_active_enrollments"])
    return out


@app.route("/studios", methods=["POST"])
def create_studio():
    _, role = require_auth()
    require_role(role, {"StudioAdmin"})
    body = helpers.get_json_body()
    helpers.require_fields(body, ["name"])
    name = helpers.require_str(body, "name")
    tiers = DEFAULT_TIERS
    if "family_discount_tiers" in body and body["family_discount_tiers"] is not None:
        tiers = _validate_tiers(body["family_discount_tiers"])
    cap = 3
    if "makeup_credit_cap_per_enrollment" in body and body["makeup_credit_cap_per_enrollment"] is not None:
        cap = helpers.require_int(body, "makeup_credit_cap_per_enrollment", minimum=0)
    notice = 24
    if "cancellation_notice_hours" in body and body["cancellation_notice_hours"] is not None:
        notice = helpers.require_int(body, "cancellation_notice_hours", minimum=0)
    valid_days = 30
    if "makeup_credit_valid_days" in body and body["makeup_credit_valid_days"] is not None:
        valid_days = helpers.require_int(body, "makeup_credit_valid_days", minimum=0)
    rec = db.init_record({
        "name": name,
        "current_utc": "2026-01-01T00:00:00.000Z",
        "family_discount_tiers": tiers,
        "makeup_credit_cap_per_enrollment": cap,
        "cancellation_notice_hours": notice,
        "makeup_credit_valid_days": valid_days,
        "status": "OPEN",
    })
    db.studios[rec["id"]] = rec
    return success(helpers.serialize(rec), status=201)


@app.route("/studios", methods=["GET"])
def list_studios():
    _, role = require_auth()
    require_role(role, {"StudioAdmin", "Instructor", "ParentGuardian", "BillingClerk"})
    rows = list(db.studios.values())
    page, pg = helpers.paginate(rows)
    return success([helpers.serialize(r) for r in page], status=200, is_array=True, pagination=pg)


@app.route("/studios/<studio_id>", methods=["GET"])
def get_studio_ep(studio_id):
    _, role = require_auth()
    require_role(role, {"StudioAdmin", "Instructor", "ParentGuardian", "BillingClerk"})
    s = helpers.get_studio(studio_id)
    return success(helpers.serialize(s), status=200)


@app.route("/studios/<studio_id>/_clock/set_current_utc", methods=["POST"])
def set_clock(studio_id):
    _, role = require_auth()
    require_role(role, {"StudioAdmin"})
    s = helpers.get_studio(studio_id)
    body = helpers.get_json_body()
    helpers.require_fields(body, ["to_iso8601"])
    target_ms = helpers.parse_iso_ms(body["to_iso8601"])
    s["current_utc"] = helpers.ms_to_iso(target_ms)
    db.touch(s)
    return success(helpers.serialize(s), status=200)


# ===========================================================================
# Family
# ===========================================================================
@app.route("/studios/<studio_id>/families", methods=["POST"])
def create_family(studio_id):
    _, role = require_auth()
    require_role(role, {"StudioAdmin"})
    helpers.get_studio(studio_id)
    body = helpers.get_json_body()
    helpers.require_fields(body, ["household_name"])
    household_name = helpers.require_str(body, "household_name")
    autopay = False
    if "autopay_enabled" in body and body["autopay_enabled"] is not None:
        autopay = helpers.require_bool(body, "autopay_enabled")
    rec = db.init_record({
        "studio_id": studio_id,
        "household_name": household_name,
        "autopay_enabled": autopay,
        "wallet_balance_cents": 0,
        "active_enrollment_count": 0,
        "family_discount_pct": 0,
        "status": "ACTIVE",
    })
    db.families[rec["id"]] = rec
    return success(helpers.serialize(rec), status=201)


@app.route("/studios/<studio_id>/families", methods=["GET"])
def list_families(studio_id):
    _, role = require_auth()
    require_role(role, {"StudioAdmin", "BillingClerk"})
    helpers.get_studio(studio_id)
    rows = [f for f in db.families.values() if f["studio_id"] == studio_id]
    filt = request.args.get("studio_id")
    if filt is not None:
        rows = [f for f in rows if f["studio_id"] == filt]
    page, pg = helpers.paginate(rows)
    return success([helpers.serialize(r) for r in page], status=200, is_array=True, pagination=pg)


@app.route("/studios/<studio_id>/families/<family_id>", methods=["GET"])
def get_family_ep(studio_id, family_id):
    _, role = require_auth()
    require_role(role, {"StudioAdmin", "BillingClerk", "ParentGuardian"})
    helpers.get_studio(studio_id)
    f = helpers.get_family(studio_id, family_id)
    return success(helpers.serialize(f), status=200)


@app.route("/studios/<studio_id>/families/<family_id>", methods=["PATCH"])
def update_family(studio_id, family_id):
    _, role = require_auth()
    require_role(role, {"StudioAdmin", "ParentGuardian"})
    helpers.get_studio(studio_id)
    f = helpers.get_family(studio_id, family_id)
    body = helpers.get_json_body()
    changed = False
    if "autopay_enabled" in body and body["autopay_enabled"] is not None:
        f["autopay_enabled"] = helpers.require_bool(body, "autopay_enabled")
        changed = True
    if "status" in body and body["status"] is not None:
        f["status"] = helpers.require_enum(body, "status", {"ACTIVE", "SUSPENDED"})
        changed = True
    if changed:
        db.touch(f)
    return success(helpers.serialize(f), status=200)


@app.route("/studios/<studio_id>/families/<family_id>/wallet/credits", methods=["POST"])
def credit_wallet(studio_id, family_id):
    _, role = require_auth()
    require_role(role, {"StudioAdmin", "BillingClerk"})
    helpers.get_studio(studio_id)
    f = helpers.get_family(studio_id, family_id)
    body = helpers.get_json_body()
    helpers.require_fields(body, ["amount_cents"])
    amount = helpers.require_int(body, "amount_cents", minimum=0)
    f["wallet_balance_cents"] += amount
    db.touch(f)
    return success(helpers.serialize(f), status=201)


# ===========================================================================
# Student
# ===========================================================================
@app.route("/studios/<studio_id>/students", methods=["POST"])
def create_student(studio_id):
    _, role = require_auth()
    require_role(role, {"StudioAdmin", "ParentGuardian"})
    helpers.get_studio(studio_id)
    body = helpers.get_json_body()
    helpers.require_fields(body, ["family_id", "full_name"])
    family_id = helpers.require_str(body, "family_id")
    full_name = helpers.require_str(body, "full_name")
    skill = "BEGINNER"
    if "skill_level" in body and body["skill_level"] is not None:
        skill = helpers.require_enum(body, "skill_level", helpers.SKILL_LEVELS)
    # referential scope: family must belong to this studio
    fam = db.families.get(family_id)
    if fam is None or fam["studio_id"] != studio_id:
        errors.raise_error(errors.ERR_CROSS_STUDIO_REFERENCE, "family_id not in this studio")
    rec = db.init_record({
        "family_id": family_id,
        "full_name": full_name,
        "skill_level": skill,
        "total_practice_minutes": 0,
        "weighted_progress_score": 0,
    })
    db.students[rec["id"]] = rec
    return success(helpers.serialize(rec), status=201)


@app.route("/studios/<studio_id>/students", methods=["GET"])
def list_students(studio_id):
    _, role = require_auth()
    require_role(role, {"StudioAdmin", "Instructor", "ParentGuardian"})
    helpers.get_studio(studio_id)
    fam_ids = {f["id"] for f in db.families.values() if f["studio_id"] == studio_id}
    rows = [s for s in db.students.values() if s["family_id"] in fam_ids]
    fam_filter = request.args.get("family_id")
    if fam_filter is not None:
        rows = [s for s in rows if s["family_id"] == fam_filter]
    page, pg = helpers.paginate(rows)
    return success([helpers.serialize(r) for r in page], status=200, is_array=True, pagination=pg)


@app.route("/studios/<studio_id>/students/<student_id>", methods=["GET"])
def get_student_ep(studio_id, student_id):
    _, role = require_auth()
    require_role(role, {"StudioAdmin", "Instructor", "ParentGuardian"})
    helpers.get_studio(studio_id)
    s = helpers.get_student(studio_id, student_id)
    return success(helpers.serialize(s), status=200)


@app.route("/studios/<studio_id>/students/<student_id>/practice-logs", methods=["POST"])
def create_practice_log(studio_id, student_id):
    _, role = require_auth()
    require_role(role, {"Instructor", "ParentGuardian"})
    studio = helpers.get_studio(studio_id)
    student = helpers.get_student(studio_id, student_id)
    body = helpers.get_json_body()
    helpers.require_fields(body, ["minutes"])
    minutes = helpers.require_int(body, "minutes", minimum=0)
    logged_utc = studio["current_utc"]
    if "logged_utc" in body and body["logged_utc"] is not None:
        logged_utc = helpers.ms_to_iso(helpers.parse_iso_ms(body["logged_utc"]))
    note = None
    if "note" in body and body["note"] is not None:
        if not isinstance(body["note"], str):
            errors.raise_error(errors.ERR_INVALID_REQUEST, "note must be a string")
        note = body["note"]
    log = db.init_record({
        "student_id": student_id,
        "minutes": minutes,
        "logged_utc": logged_utc,
        "note": note,
    })
    db.practice_logs[log["id"]] = log
    services.recompute_practice(student, studio)
    return success(helpers.serialize(student), status=201)


# ===========================================================================
# Instructor
# ===========================================================================
def _validate_availability(value):
    if not isinstance(value, list):
        errors.raise_error(errors.ERR_INVALID_REQUEST, "weekly_availability must be an array")
    out = []
    for w in value:
        if not isinstance(w, dict):
            errors.raise_error(errors.ERR_INVALID_REQUEST, "availability window must be an object")
        wd = w.get("weekday")
        sm = w.get("start_min")
        em = w.get("end_min")
        for v, nm in ((wd, "weekday"), (sm, "start_min"), (em, "end_min")):
            if isinstance(v, bool) or not isinstance(v, int):
                errors.raise_error(errors.ERR_INVALID_REQUEST, "availability %s must be int" % nm)
        if not (0 <= wd <= 6):
            errors.raise_error(errors.ERR_INVALID_REQUEST, "weekday out of range")
        if em <= sm:
            errors.raise_error(errors.ERR_INVALID_REQUEST, "availability end_min must be > start_min")
        out.append({"weekday": wd, "start_min": sm, "end_min": em})
    return out


def _validate_instruments(value):
    if not isinstance(value, list) or not value:
        errors.raise_error(errors.ERR_INVALID_REQUEST, "instruments must be a non-empty array")
    for i in value:
        if i not in helpers.INSTRUMENTS:
            errors.raise_error(errors.ERR_INVALID_REQUEST, "invalid instrument: %s" % i)
    return list(value)


@app.route("/studios/<studio_id>/instructors", methods=["POST"])
def create_instructor(studio_id):
    _, role = require_auth()
    require_role(role, {"StudioAdmin"})
    helpers.get_studio(studio_id)
    body = helpers.get_json_body()
    helpers.require_fields(body, ["full_name", "instruments", "weekly_availability", "hourly_rate_cents"])
    full_name = helpers.require_str(body, "full_name")
    instruments = _validate_instruments(body["instruments"])
    availability = _validate_availability(body["weekly_availability"])
    rate = helpers.require_int(body, "hourly_rate_cents", minimum=0)
    rec = db.init_record({
        "studio_id": studio_id,
        "full_name": full_name,
        "instruments": instruments,
        "weekly_availability": availability,
        "hourly_rate_cents": rate,
        "status": "ACTIVE",
    })
    db.instructors[rec["id"]] = rec
    return success(helpers.serialize(rec), status=201)


@app.route("/studios/<studio_id>/instructors", methods=["GET"])
def list_instructors(studio_id):
    _, role = require_auth()
    require_role(role, {"StudioAdmin", "Instructor", "ParentGuardian"})
    helpers.get_studio(studio_id)
    rows = [i for i in db.instructors.values() if i["studio_id"] == studio_id]
    page, pg = helpers.paginate(rows)
    return success([helpers.serialize(r) for r in page], status=200, is_array=True, pagination=pg)


@app.route("/studios/<studio_id>/instructors/<instructor_id>", methods=["GET"])
def get_instructor_ep(studio_id, instructor_id):
    _, role = require_auth()
    require_role(role, {"StudioAdmin", "Instructor", "ParentGuardian"})
    helpers.get_studio(studio_id)
    i = helpers.get_instructor(studio_id, instructor_id)
    return success(helpers.serialize(i), status=200)


@app.route("/studios/<studio_id>/instructors/<instructor_id>", methods=["PATCH"])
def update_instructor(studio_id, instructor_id):
    _, role = require_auth()
    require_role(role, {"StudioAdmin"})
    helpers.get_studio(studio_id)
    i = helpers.get_instructor(studio_id, instructor_id)
    body = helpers.get_json_body()
    if "status" in body and body["status"] is not None:
        i["status"] = helpers.require_enum(body, "status", {"ACTIVE", "INACTIVE"})
        db.touch(i)
    return success(helpers.serialize(i), status=200)


# ===========================================================================
# Room
# ===========================================================================
@app.route("/studios/<studio_id>/rooms", methods=["POST"])
def create_room(studio_id):
    _, role = require_auth()
    require_role(role, {"StudioAdmin"})
    helpers.get_studio(studio_id)
    body = helpers.get_json_body()
    helpers.require_fields(body, ["room_name", "supported_instruments"])
    room_name = helpers.require_str(body, "room_name")
    supported = _validate_instruments(body["supported_instruments"])
    buffer_min = 10
    if "turnover_buffer_min" in body and body["turnover_buffer_min"] is not None:
        buffer_min = helpers.require_int(body, "turnover_buffer_min", minimum=0)
    rec = db.init_record({
        "studio_id": studio_id,
        "room_name": room_name,
        "supported_instruments": supported,
        "turnover_buffer_min": buffer_min,
    })
    db.rooms[rec["id"]] = rec
    return success(helpers.serialize(rec), status=201)


@app.route("/studios/<studio_id>/rooms", methods=["GET"])
def list_rooms(studio_id):
    _, role = require_auth()
    require_role(role, {"StudioAdmin", "Instructor", "ParentGuardian"})
    helpers.get_studio(studio_id)
    rows = [r for r in db.rooms.values() if r["studio_id"] == studio_id]
    page, pg = helpers.paginate(rows)
    return success([helpers.serialize(r) for r in page], status=200, is_array=True, pagination=pg)


@app.route("/studios/<studio_id>/rooms/<room_id>", methods=["GET"])
def get_room_ep(studio_id, room_id):
    _, role = require_auth()
    require_role(role, {"StudioAdmin", "Instructor", "ParentGuardian"})
    helpers.get_studio(studio_id)
    r = helpers.get_room(studio_id, room_id)
    return success(helpers.serialize(r), status=200)


# ===========================================================================
# Enrollment
# ===========================================================================
@app.route("/studios/<studio_id>/enrollments", methods=["POST"])
def create_enrollment(studio_id):
    _, role = require_auth()
    require_role(role, {"StudioAdmin", "ParentGuardian"})
    helpers.get_studio(studio_id)
    body = helpers.get_json_body()
    helpers.require_fields(body, ["student_id", "instructor_id", "room_id", "instrument",
                                  "weekday", "start_min", "duration_min"])
    student_id = helpers.require_str(body, "student_id")
    instructor_id = helpers.require_str(body, "instructor_id")
    room_id = helpers.require_str(body, "room_id")
    instrument = helpers.require_enum(body, "instrument", helpers.INSTRUMENTS)
    weekday = helpers.require_int(body, "weekday")
    if not (0 <= weekday <= 6):
        errors.raise_error(errors.ERR_INVALID_REQUEST, "weekday out of range")
    start_min = helpers.require_int(body, "start_min", minimum=0)
    duration_min = helpers.require_int(body, "duration_min", minimum=1)
    # referential scope (priority 5): student's family in this studio; instructor/room in studio
    student = db.students.get(student_id)
    if student is None:
        errors.raise_error(errors.ERR_CROSS_STUDIO_REFERENCE, "student_id not in this studio")
    family = db.families.get(student["family_id"])
    if family is None or family["studio_id"] != studio_id:
        errors.raise_error(errors.ERR_CROSS_STUDIO_REFERENCE, "student_id not in this studio")
    instructor = db.instructors.get(instructor_id)
    if instructor is None or instructor["studio_id"] != studio_id:
        errors.raise_error(errors.ERR_CROSS_STUDIO_REFERENCE, "instructor_id not in this studio")
    room = db.rooms.get(room_id)
    if room is None or room["studio_id"] != studio_id:
        errors.raise_error(errors.ERR_CROSS_STUDIO_REFERENCE, "room_id not in this studio")
    monthly = services.compute_monthly_tuition(instructor, duration_min)
    rec = db.init_record({
        "studio_id": studio_id,
        "family_id": student["family_id"],
        "student_id": student_id,
        "instructor_id": instructor_id,
        "room_id": room_id,
        "instrument": instrument,
        "weekday": weekday,
        "start_min": start_min,
        "duration_min": duration_min,
        "lifecycle_status": "PENDING_MATCH",
        "billing_status": "UNBILLED",
        "monthly_tuition_cents": monthly,
    })
    db.enrollments[rec["id"]] = rec
    return success(helpers.serialize(rec), status=201)


@app.route("/studios/<studio_id>/enrollments", methods=["GET"])
def list_enrollments(studio_id):
    _, role = require_auth()
    require_role(role, {"StudioAdmin", "Instructor", "ParentGuardian", "BillingClerk"})
    helpers.get_studio(studio_id)
    rows = [e for e in db.enrollments.values() if e["studio_id"] == studio_id]
    for key in ("family_id", "student_id", "instructor_id", "room_id"):
        val = request.args.get(key)
        if val is not None:
            rows = [e for e in rows if e[key] == val]
    page, pg = helpers.paginate(rows)
    return success([helpers.serialize(r) for r in page], status=200, is_array=True, pagination=pg)


@app.route("/studios/<studio_id>/enrollments/<enrollment_id>", methods=["GET"])
def get_enrollment_ep(studio_id, enrollment_id):
    _, role = require_auth()
    require_role(role, {"StudioAdmin", "Instructor", "ParentGuardian", "BillingClerk"})
    helpers.get_studio(studio_id)
    e = helpers.get_enrollment(studio_id, enrollment_id)
    return success(helpers.serialize(e), status=200)


def _check_match_and_slot(studio, enrollment, instructor, room):
    """Run the activation/resume capability + temporal precondition battery.
    Order pinned per PRD §3.2: family suspension is checked by caller; here we run
    instrument/room capability, availability, instructor double-book, room double-book."""
    if instructor["status"] != "ACTIVE" or enrollment["instrument"] not in instructor["instruments"]:
        errors.raise_error(errors.ERR_INSTRUCTOR_INSTRUMENT_MISMATCH,
                           "Instructor inactive or does not teach instrument")
    if enrollment["instrument"] not in room["supported_instruments"]:
        errors.raise_error(errors.ERR_ROOM_INSTRUMENT_MISMATCH, "Room does not support instrument")
    end_min = enrollment["start_min"] + enrollment["duration_min"]
    if not services.window_inside_availability(instructor, enrollment["weekday"],
                                               enrollment["start_min"], end_min):
        errors.raise_error(errors.ERR_OUTSIDE_AVAILABILITY,
                           "Recurring window outside instructor availability")
    if services.instructor_recurring_conflict(studio["id"], enrollment):
        errors.raise_error(errors.ERR_INSTRUCTOR_DOUBLE_BOOKED, "Instructor double-booked")
    if services.room_recurring_conflict(studio["id"], enrollment, room):
        errors.raise_error(errors.ERR_ROOM_DOUBLE_BOOKED, "Room double-booked")


@app.route("/studios/<studio_id>/enrollments/<enrollment_id>/activate", methods=["POST"])
def activate_enrollment(studio_id, enrollment_id):
    _, role = require_auth()
    require_role(role, {"StudioAdmin"})
    studio = helpers.get_studio(studio_id)
    enr = helpers.get_enrollment(studio_id, enrollment_id)
    body = helpers.get_json_body()
    helpers.require_fields(body, ["expected_enrollment_version"])
    expected = helpers.require_int(body, "expected_enrollment_version")
    # State (priority 6): must be PENDING_MATCH (only valid source for activate)
    if enr["lifecycle_status"] != "PENDING_MATCH":
        errors.raise_error(errors.ERR_INVALID_STATE, "Enrollment not in PENDING_MATCH")
    family = db.families.get(enr["family_id"])
    # Family suspended (priority 8)
    if family["status"] != "ACTIVE":
        errors.raise_error(errors.ERR_FAMILY_SUSPENDED, "Family is suspended")
    instructor = db.instructors.get(enr["instructor_id"])
    room = db.rooms.get(enr["room_id"])
    _check_match_and_slot(studio, enr, instructor, room)
    # OCC last, guarding the commit (PRD §2.7/§3.2)
    if expected != enr["version"]:
        errors.raise_error(errors.ERR_STALE_VERSION, "expected_enrollment_version mismatch")
    enr["lifecycle_status"] = "ACTIVE"
    db.touch(enr)
    services.recompute_family_discount(studio, family)
    return success(helpers.serialize(enr), status=200)


@app.route("/studios/<studio_id>/enrollments/<enrollment_id>/freeze", methods=["POST"])
def freeze_enrollment(studio_id, enrollment_id):
    _, role = require_auth()
    require_role(role, {"StudioAdmin"})
    studio = helpers.get_studio(studio_id)
    enr = helpers.get_enrollment(studio_id, enrollment_id)
    if enr["lifecycle_status"] != "ACTIVE":
        errors.raise_error(errors.ERR_INVALID_STATE, "Enrollment not ACTIVE")
    enr["lifecycle_status"] = "FROZEN"
    db.touch(enr)
    # cascade hop 1+2: cancel future SCHEDULED occurrences, mint credits under cap
    current_ms = helpers.parse_iso_ms(studio["current_utc"])
    occs = [o for o in db.lesson_occurrences.values()
            if o["enrollment_id"] == enrollment_id and o["status"] == "SCHEDULED"
            and helpers.parse_iso_ms(o["scheduled_start_utc"]) >= current_ms]
    occs.sort(key=lambda o: (o["created_at"], o["_seq"]))
    for occ in occs:
        occ["status"] = "CANCELLED_NOTICE"
        db.touch(occ)
        if services.outstanding_credit_count(enrollment_id, current_ms) < studio["makeup_credit_cap_per_enrollment"]:
            services.mint_credit(enr, studio, occ["id"])
    # cascade hop 3: recompute discount (FROZEN no longer ACTIVE)
    family = db.families.get(enr["family_id"])
    services.recompute_family_discount(studio, family)
    return success(helpers.serialize(enr), status=200)


@app.route("/studios/<studio_id>/enrollments/<enrollment_id>/resume", methods=["POST"])
def resume_enrollment(studio_id, enrollment_id):
    _, role = require_auth()
    require_role(role, {"StudioAdmin"})
    studio = helpers.get_studio(studio_id)
    enr = helpers.get_enrollment(studio_id, enrollment_id)
    body = helpers.get_json_body()
    helpers.require_fields(body, ["expected_enrollment_version"])
    expected = helpers.require_int(body, "expected_enrollment_version")
    if enr["lifecycle_status"] != "FROZEN":
        errors.raise_error(errors.ERR_INVALID_STATE, "Enrollment not FROZEN")
    instructor = db.instructors.get(enr["instructor_id"])
    room = db.rooms.get(enr["room_id"])
    # re-validate slot against current ACTIVE bookings (instructor + room overlap)
    if services.instructor_recurring_conflict(studio_id, enr):
        errors.raise_error(errors.ERR_INSTRUCTOR_DOUBLE_BOOKED, "Instructor double-booked")
    if services.room_recurring_conflict(studio_id, enr, room):
        errors.raise_error(errors.ERR_ROOM_DOUBLE_BOOKED, "Room double-booked")
    if expected != enr["version"]:
        errors.raise_error(errors.ERR_STALE_VERSION, "expected_enrollment_version mismatch")
    enr["lifecycle_status"] = "ACTIVE"
    db.touch(enr)
    family = db.families.get(enr["family_id"])
    services.recompute_family_discount(studio, family)
    return success(helpers.serialize(enr), status=200)


@app.route("/studios/<studio_id>/enrollments/<enrollment_id>/cancel", methods=["POST"])
def cancel_enrollment(studio_id, enrollment_id):
    _, role = require_auth()
    require_role(role, {"StudioAdmin"})
    studio = helpers.get_studio(studio_id)
    enr = helpers.get_enrollment(studio_id, enrollment_id)
    if enr["lifecycle_status"] == "CANCELLED":
        errors.raise_error(errors.ERR_INVALID_STATE, "Enrollment already CANCELLED")
    enr["lifecycle_status"] = "CANCELLED"
    db.touch(enr)
    # cascade: future SCHEDULED -> CANCELLED_NOTICE (no credits)
    current_ms = helpers.parse_iso_ms(studio["current_utc"])
    for occ in db.lesson_occurrences.values():
        if occ["enrollment_id"] != enrollment_id:
            continue
        if occ["status"] == "SCHEDULED" and helpers.parse_iso_ms(occ["scheduled_start_utc"]) >= current_ms:
            occ["status"] = "CANCELLED_NOTICE"
            db.touch(occ)
    # all OUTSTANDING credits -> VOIDED
    for cr in db.makeup_credits.values():
        if cr["enrollment_id"] == enrollment_id and cr["status"] == "OUTSTANDING":
            cr["status"] = "VOIDED"
            db.touch(cr)
    family = db.families.get(enr["family_id"])
    services.recompute_family_discount(studio, family)
    return success(helpers.serialize(enr), status=200)


# ===========================================================================
# LessonOccurrence
# ===========================================================================
@app.route("/studios/<studio_id>/lesson-occurrences", methods=["POST"])
def create_occurrence(studio_id):
    _, role = require_auth()
    require_role(role, {"StudioAdmin"})
    helpers.get_studio(studio_id)
    body = helpers.get_json_body()
    helpers.require_fields(body, ["enrollment_id", "scheduled_start_utc"])
    enrollment_id = helpers.require_str(body, "enrollment_id")
    start_ms = helpers.parse_iso_ms(body["scheduled_start_utc"])
    enr = db.enrollments.get(enrollment_id)
    if enr is None or enr["studio_id"] != studio_id:
        errors.raise_error(errors.ERR_ENROLLMENT_NOT_FOUND, "Enrollment not found")
    if enr["lifecycle_status"] != "ACTIVE":
        errors.raise_error(errors.ERR_ENROLLMENT_NOT_ACTIVE, "Enrollment not ACTIVE")
    end_ms = start_ms + enr["duration_min"] * 60000
    # non-overlap on instructor + room (half-open, no buffer)
    if services.dated_occurrence_conflict(studio_id, start_ms, end_ms,
                                          enr["instructor_id"], enr["room_id"]):
        errors.raise_error(errors.ERR_MAKEUP_SLOT_CONFLICT, "Occurrence overlaps instructor/room")
    rec = db.init_record({
        "enrollment_id": enrollment_id,
        "room_id": enr["room_id"],
        "instructor_id": enr["instructor_id"],
        "scheduled_start_utc": helpers.ms_to_iso(start_ms),
        "scheduled_end_utc": helpers.ms_to_iso(end_ms),
        "is_makeup": False,
        "consumed_credit_id": None,
        "status": "SCHEDULED",
    })
    db.lesson_occurrences[rec["id"]] = rec
    return success(helpers.serialize(rec), status=201)


@app.route("/studios/<studio_id>/lesson-occurrences", methods=["GET"])
def list_occurrences(studio_id):
    _, role = require_auth()
    require_role(role, {"StudioAdmin", "Instructor", "ParentGuardian"})
    helpers.get_studio(studio_id)
    enr_ids = {e["id"] for e in db.enrollments.values() if e["studio_id"] == studio_id}
    rows = [o for o in db.lesson_occurrences.values() if o["enrollment_id"] in enr_ids]
    for key in ("enrollment_id", "room_id", "instructor_id", "consumed_credit_id"):
        val = request.args.get(key)
        if val is not None:
            rows = [o for o in rows if o.get(key) == val]
    page, pg = helpers.paginate(rows)
    return success([helpers.serialize(r) for r in page], status=200, is_array=True, pagination=pg)


@app.route("/studios/<studio_id>/lesson-occurrences/<occ_id>", methods=["GET"])
def get_occurrence_ep(studio_id, occ_id):
    _, role = require_auth()
    require_role(role, {"StudioAdmin", "Instructor", "ParentGuardian"})
    helpers.get_studio(studio_id)
    o = helpers.get_occurrence(studio_id, occ_id)
    return success(helpers.serialize(o), status=200)


@app.route("/studios/<studio_id>/lesson-occurrences/<occ_id>/complete", methods=["POST"])
def complete_occurrence(studio_id, occ_id):
    _, role = require_auth()
    require_role(role, {"Instructor", "StudioAdmin"})
    studio = helpers.get_studio(studio_id)
    occ = helpers.get_occurrence(studio_id, occ_id)
    if occ["status"] != "SCHEDULED":
        errors.raise_error(errors.ERR_INVALID_STATE, "Occurrence not SCHEDULED")
    current_ms = helpers.parse_iso_ms(studio["current_utc"])
    if current_ms < helpers.parse_iso_ms(occ["scheduled_start_utc"]):
        errors.raise_error(errors.ERR_LESSON_NOT_STARTED, "Lesson has not started")
    enr = db.enrollments.get(occ["enrollment_id"])
    if enr["lifecycle_status"] != "ACTIVE":
        errors.raise_error(errors.ERR_ENROLLMENT_NOT_ACTIVE, "Enrollment not ACTIVE")
    occ["status"] = "COMPLETED"
    db.touch(occ)
    return success(helpers.serialize(occ), status=200)


@app.route("/studios/<studio_id>/lesson-occurrences/<occ_id>/cancel", methods=["POST"])
def cancel_occurrence(studio_id, occ_id):
    _, role = require_auth()
    require_role(role, {"StudioAdmin", "ParentGuardian"})
    studio = helpers.get_studio(studio_id)
    occ = helpers.get_occurrence(studio_id, occ_id)
    if occ["status"] != "SCHEDULED":
        errors.raise_error(errors.ERR_INVALID_STATE, "Occurrence not SCHEDULED")
    current_ms = helpers.parse_iso_ms(studio["current_utc"])
    start_ms = helpers.parse_iso_ms(occ["scheduled_start_utc"])
    gap_hours = (start_ms - current_ms) / 3600000.0
    enr = db.enrollments.get(occ["enrollment_id"])
    if gap_hours >= studio["cancellation_notice_hours"]:
        # timely: mint credit if under cap, else reject
        if services.outstanding_credit_count(enr["id"], current_ms) >= studio["makeup_credit_cap_per_enrollment"]:
            errors.raise_error(errors.ERR_MAKEUP_CAP_EXCEEDED, "Makeup credit cap reached")
        occ["status"] = "CANCELLED_NOTICE"
        db.touch(occ)
        services.mint_credit(enr, studio, occ["id"])
    else:
        # late: forfeit, no credit
        occ["status"] = "CANCELLED_LATE"
        db.touch(occ)
    return success(helpers.serialize(occ), status=200)


@app.route("/studios/<studio_id>/lesson-occurrences/<occ_id>/request-makeup", methods=["POST"])
def request_makeup(studio_id, occ_id):
    _, role = require_auth()
    require_role(role, {"StudioAdmin", "ParentGuardian"})
    studio = helpers.get_studio(studio_id)
    occ = helpers.get_occurrence(studio_id, occ_id)
    if occ["status"] != "SCHEDULED":
        errors.raise_error(errors.ERR_INVALID_STATE, "Occurrence not SCHEDULED")
    if occ["is_makeup"]:
        errors.raise_error(errors.ERR_MAKEUP_NOT_ALLOWED, "Makeup occurrence cannot spawn a makeup")
    current_ms = helpers.parse_iso_ms(studio["current_utc"])
    start_ms = helpers.parse_iso_ms(occ["scheduled_start_utc"])
    gap_hours = (start_ms - current_ms) / 3600000.0
    if gap_hours < studio["cancellation_notice_hours"]:
        errors.raise_error(errors.ERR_LATE_CANCELLATION, "Within cancellation notice window")
    enr = db.enrollments.get(occ["enrollment_id"])
    if services.outstanding_credit_count(enr["id"], current_ms) >= studio["makeup_credit_cap_per_enrollment"]:
        errors.raise_error(errors.ERR_MAKEUP_CAP_EXCEEDED, "Makeup credit cap reached")
    occ["status"] = "MAKEUP_PENDING"
    db.touch(occ)
    services.mint_credit(enr, studio, occ["id"])
    return success(helpers.serialize(occ), status=200)


@app.route("/studios/<studio_id>/make-up-occurrences", methods=["POST"])
def create_makeup_occurrence(studio_id):
    _, role = require_auth()
    require_role(role, {"StudioAdmin", "ParentGuardian"})
    studio = helpers.get_studio(studio_id)
    body = helpers.get_json_body()
    helpers.require_fields(body, ["credit_id", "scheduled_start_utc"])
    credit_id = helpers.require_str(body, "credit_id")
    start_ms = helpers.parse_iso_ms(body["scheduled_start_utc"])
    credit = db.makeup_credits.get(credit_id)
    if credit is None:
        errors.raise_error(errors.ERR_CREDIT_NOT_FOUND, "Credit not found")
    enr = db.enrollments.get(credit["enrollment_id"])
    if enr is None or enr["studio_id"] != studio_id:
        errors.raise_error(errors.ERR_CREDIT_NOT_FOUND, "Credit not found")
    current_ms = helpers.parse_iso_ms(studio["current_utc"])
    services.lazy_expire_credit(credit, current_ms)
    # credit must be OUTSTANDING and current_utc <= expires_utc
    if credit["status"] != "OUTSTANDING" or current_ms > helpers.parse_iso_ms(credit["expires_utc"]):
        errors.raise_error(errors.ERR_CREDIT_NOT_USABLE, "Credit not usable")
    room_id = enr["room_id"]
    if "room_id" in body and body["room_id"] is not None:
        room_id = helpers.require_str(body, "room_id")
        room = db.rooms.get(room_id)
        if room is None or room["studio_id"] != studio_id:
            errors.raise_error(errors.ERR_CROSS_STUDIO_REFERENCE, "room_id not in this studio")
    end_ms = start_ms + enr["duration_min"] * 60000
    instructor_id = enr["instructor_id"]
    if services.dated_occurrence_conflict(studio_id, start_ms, end_ms, instructor_id, room_id):
        errors.raise_error(errors.ERR_MAKEUP_SLOT_CONFLICT, "Makeup occurrence overlaps instructor/room")
    rec = db.init_record({
        "enrollment_id": enr["id"],
        "room_id": room_id,
        "instructor_id": instructor_id,
        "scheduled_start_utc": helpers.ms_to_iso(start_ms),
        "scheduled_end_utc": helpers.ms_to_iso(end_ms),
        "is_makeup": True,
        "consumed_credit_id": credit_id,
        "status": "SCHEDULED",
    })
    db.lesson_occurrences[rec["id"]] = rec
    credit["status"] = "CONSUMED"
    db.touch(credit)
    # restore origin occurrence MAKEUP_PENDING -> SCHEDULED
    origin = db.lesson_occurrences.get(credit["origin_occurrence_id"])
    if origin is not None and origin["status"] == "MAKEUP_PENDING":
        origin["status"] = "SCHEDULED"
        db.touch(origin)
    return success(helpers.serialize(rec), status=201)


# ===========================================================================
# MakeupCredit
# ===========================================================================
@app.route("/studios/<studio_id>/makeup-credits", methods=["GET"])
def list_credits(studio_id):
    _, role = require_auth()
    require_role(role, {"StudioAdmin", "ParentGuardian"})
    studio = helpers.get_studio(studio_id)
    enr_ids = {e["id"] for e in db.enrollments.values() if e["studio_id"] == studio_id}
    rows = [c for c in db.makeup_credits.values() if c["enrollment_id"] in enr_ids]
    current_ms = helpers.parse_iso_ms(studio["current_utc"])
    for c in rows:
        services.lazy_expire_credit(c, current_ms)
    for key in ("enrollment_id", "origin_occurrence_id"):
        val = request.args.get(key)
        if val is not None:
            rows = [c for c in rows if c.get(key) == val]
    page, pg = helpers.paginate(rows)
    return success([helpers.serialize(r) for r in page], status=200, is_array=True, pagination=pg)


@app.route("/studios/<studio_id>/makeup-credits/<credit_id>", methods=["GET"])
def get_credit_ep(studio_id, credit_id):
    _, role = require_auth()
    require_role(role, {"StudioAdmin", "ParentGuardian"})
    studio = helpers.get_studio(studio_id)
    c = helpers.get_credit(studio_id, credit_id)
    services.lazy_expire_credit(c, helpers.parse_iso_ms(studio["current_utc"]))
    return success(helpers.serialize(c), status=200)


# ===========================================================================
# TuitionInvoice
# ===========================================================================
def _valid_billing_period(value):
    if not isinstance(value, str):
        errors.raise_error(errors.ERR_INVALID_REQUEST, "billing_period must be a string")
    parts = value.split("-")
    if len(parts) != 2:
        errors.raise_error(errors.ERR_INVALID_REQUEST, "billing_period must be 'YYYY-MM'")
    try:
        y = int(parts[0])
        m = int(parts[1])
    except ValueError:
        errors.raise_error(errors.ERR_INVALID_REQUEST, "billing_period must be 'YYYY-MM'")
    if len(parts[0]) != 4 or len(parts[1]) != 2 or not (1 <= m <= 12):
        errors.raise_error(errors.ERR_INVALID_REQUEST, "billing_period must be 'YYYY-MM'")
    return value


@app.route("/studios/<studio_id>/invoices", methods=["POST"])
def create_invoice(studio_id):
    _, role = require_auth()
    require_role(role, {"BillingClerk", "StudioAdmin"})
    studio = helpers.get_studio(studio_id)
    body = helpers.get_json_body()
    helpers.require_fields(body, ["enrollment_id", "billing_period"])
    enrollment_id = helpers.require_str(body, "enrollment_id")
    billing_period = _valid_billing_period(body["billing_period"])
    enr = db.enrollments.get(enrollment_id)
    if enr is None or enr["studio_id"] != studio_id:
        errors.raise_error(errors.ERR_ENROLLMENT_NOT_FOUND, "Enrollment not found")
    # billing transition precondition: lifecycle ACTIVE or FROZEN
    if enr["lifecycle_status"] not in ("ACTIVE", "FROZEN"):
        errors.raise_error(errors.ERR_INVALID_STATE, "Enrollment lifecycle not ACTIVE/FROZEN")
    family = db.families.get(enr["family_id"])
    current_ms = helpers.parse_iso_ms(studio["current_utc"])
    provisional = services.compute_provisional(enr, family, billing_period, current_ms)
    rec = db.init_record({
        "family_id": enr["family_id"],
        "enrollment_id": enrollment_id,
        "billing_period": billing_period,
        "provisional_amount_cents": provisional,
        "finalized_amount_cents": 0,
        "rental_surcharge_cents": 0,
        "amount_due_cents": provisional,
        "status": "ISSUED",
    })
    db.invoices[rec["id"]] = rec
    # enrollment billing_status UNBILLED -> BILLED
    if enr["billing_status"] == "UNBILLED":
        enr["billing_status"] = "BILLED"
        db.touch(enr)
    return success(helpers.serialize(rec), status=201)


@app.route("/studios/<studio_id>/invoices", methods=["GET"])
def list_invoices(studio_id):
    _, role = require_auth()
    require_role(role, {"BillingClerk", "StudioAdmin", "ParentGuardian"})
    helpers.get_studio(studio_id)
    fam_ids = {f["id"] for f in db.families.values() if f["studio_id"] == studio_id}
    rows = [i for i in db.invoices.values() if i["family_id"] in fam_ids]
    for key in ("family_id", "enrollment_id"):
        val = request.args.get(key)
        if val is not None:
            rows = [i for i in rows if i[key] == val]
    page, pg = helpers.paginate(rows)
    return success([helpers.serialize(r) for r in page], status=200, is_array=True, pagination=pg)


@app.route("/studios/<studio_id>/invoices/<invoice_id>", methods=["GET"])
def get_invoice_ep(studio_id, invoice_id):
    _, role = require_auth()
    require_role(role, {"BillingClerk", "StudioAdmin", "ParentGuardian"})
    helpers.get_studio(studio_id)
    i = helpers.get_invoice(studio_id, invoice_id)
    return success(helpers.serialize(i), status=200)


def _attempt_payment(studio, invoice, enr, family, method):
    """Create a Payment for the invoice's amount_due. Wallet-funded.
    Returns the payment record. Raises ERR_INSUFFICIENT_FUNDS on shortfall for
    manual payments; auto-pay callers catch state via return value."""
    amount = invoice["amount_due_cents"]
    if family["wallet_balance_cents"] >= amount:
        pay = db.init_record({
            "invoice_id": invoice["id"],
            "family_id": family["id"],
            "amount_cents": amount,
            "method": method,
            "status": "SUCCEEDED",
            "failure_reason": "NONE",
        })
        db.payments[pay["id"]] = pay
        family["wallet_balance_cents"] -= amount
        db.touch(family)
        invoice["status"] = "PAID"
        db.touch(invoice)
        if enr is not None and enr["billing_status"] == "PAST_DUE":
            enr["billing_status"] = "BILLED"
            db.touch(enr)
        return pay, True
    else:
        pay = db.init_record({
            "invoice_id": invoice["id"],
            "family_id": family["id"],
            "amount_cents": amount,
            "method": method,
            "status": "FAILED",
            "failure_reason": "INSUFFICIENT_FUNDS",
        })
        db.payments[pay["id"]] = pay
        if enr is not None:
            enr["billing_status"] = "PAST_DUE"
            db.touch(enr)
        return pay, False


@app.route("/studios/<studio_id>/invoices/<invoice_id>/finalize", methods=["POST"])
def finalize_invoice(studio_id, invoice_id):
    _, role = require_auth()
    require_role(role, {"BillingClerk"})
    studio = helpers.get_studio(studio_id)
    inv = helpers.get_invoice(studio_id, invoice_id)
    if inv["status"] != "ISSUED":
        errors.raise_error(errors.ERR_INVALID_STATE, "Invoice not ISSUED")
    # period must have fully elapsed
    _, period_end_ms = services.billing_period_range_ms(inv["billing_period"])
    current_ms = helpers.parse_iso_ms(studio["current_utc"])
    if current_ms < period_end_ms:
        errors.raise_error(errors.ERR_PERIOD_NOT_ENDED, "Billing period not ended")
    enr = db.enrollments.get(inv["enrollment_id"])
    family = db.families.get(inv["family_id"])
    finalized = services.compute_finalized(enr, family, inv["billing_period"])
    surcharge = services.compute_rental_surcharge(inv["family_id"], inv["billing_period"])
    inv["finalized_amount_cents"] = finalized
    inv["rental_surcharge_cents"] = surcharge
    inv["amount_due_cents"] = finalized + surcharge
    inv["status"] = "FINALIZED"
    db.touch(inv)
    # billing_status BILLED -> PAST_DUE (finalized and not yet paid)
    if enr is not None and enr["billing_status"] == "BILLED":
        enr["billing_status"] = "PAST_DUE"
        db.touch(enr)
    # auto-pay cascade
    if family["autopay_enabled"] and family["status"] == "ACTIVE":
        _attempt_payment(studio, inv, enr, family, "AUTOPAY")
    return success(helpers.serialize(inv), status=200)


@app.route("/studios/<studio_id>/invoices/<invoice_id>/void", methods=["POST"])
def void_invoice(studio_id, invoice_id):
    _, role = require_auth()
    require_role(role, {"BillingClerk"})
    helpers.get_studio(studio_id)
    inv = helpers.get_invoice(studio_id, invoice_id)
    if inv["status"] != "ISSUED":
        errors.raise_error(errors.ERR_INVALID_STATE, "Invoice not ISSUED")
    inv["status"] = "VOID"
    db.touch(inv)
    return success(helpers.serialize(inv), status=200)


# ===========================================================================
# Payment
# ===========================================================================
@app.route("/studios/<studio_id>/payments", methods=["POST"])
def create_payment(studio_id):
    _, role = require_auth()
    require_role(role, {"BillingClerk", "ParentGuardian"})
    studio = helpers.get_studio(studio_id)
    body = helpers.get_json_body()
    helpers.require_fields(body, ["invoice_id"])
    invoice_id = helpers.require_str(body, "invoice_id")
    method = "WALLET"
    if "method" in body and body["method"] is not None:
        method = helpers.require_enum(body, "method", {"WALLET", "AUTOPAY"})
    inv = db.invoices.get(invoice_id)
    if inv is None:
        errors.raise_error(errors.ERR_INVOICE_NOT_FOUND, "Invoice not found")
    family = db.families.get(inv["family_id"])
    if family is None or family["studio_id"] != studio_id:
        errors.raise_error(errors.ERR_INVOICE_NOT_FOUND, "Invoice not found")
    if inv["status"] != "FINALIZED":
        errors.raise_error(errors.ERR_INVALID_STATE, "Invoice not FINALIZED")
    enr = db.enrollments.get(inv["enrollment_id"])
    pay, ok = _attempt_payment(studio, inv, enr, family, method)
    if not ok:
        errors.raise_error(errors.ERR_INSUFFICIENT_FUNDS, "Insufficient wallet balance")
    return success(helpers.serialize(pay), status=201)


@app.route("/studios/<studio_id>/payments", methods=["GET"])
def list_payments(studio_id):
    _, role = require_auth()
    require_role(role, {"BillingClerk", "StudioAdmin", "ParentGuardian"})
    helpers.get_studio(studio_id)
    fam_ids = {f["id"] for f in db.families.values() if f["studio_id"] == studio_id}
    rows = [p for p in db.payments.values() if p["family_id"] in fam_ids]
    for key in ("invoice_id", "family_id"):
        val = request.args.get(key)
        if val is not None:
            rows = [p for p in rows if p[key] == val]
    page, pg = helpers.paginate(rows)
    return success([helpers.serialize(r) for r in page], status=200, is_array=True, pagination=pg)


@app.route("/studios/<studio_id>/payments/<payment_id>", methods=["GET"])
def get_payment_ep(studio_id, payment_id):
    _, role = require_auth()
    require_role(role, {"BillingClerk", "StudioAdmin", "ParentGuardian"})
    helpers.get_studio(studio_id)
    p = helpers.get_payment(studio_id, payment_id)
    return success(helpers.serialize(p), status=200)


@app.route("/studios/<studio_id>/payments/<payment_id>/refund", methods=["POST"])
def refund_payment(studio_id, payment_id):
    _, role = require_auth()
    require_role(role, {"BillingClerk"})
    helpers.get_studio(studio_id)
    pay = helpers.get_payment(studio_id, payment_id)
    if pay["status"] != "SUCCEEDED":
        errors.raise_error(errors.ERR_INVALID_STATE, "Payment not SUCCEEDED")
    pay["status"] = "REFUNDED"
    db.touch(pay)
    family = db.families.get(pay["family_id"])
    family["wallet_balance_cents"] += pay["amount_cents"]
    db.touch(family)
    inv = db.invoices.get(pay["invoice_id"])
    if inv is not None and inv["status"] == "PAID":
        inv["status"] = "FINALIZED"
        db.touch(inv)
    return success(helpers.serialize(pay), status=200)


# ===========================================================================
# RecitalEvent
# ===========================================================================
@app.route("/studios/<studio_id>/recital-events", methods=["POST"])
def create_recital_event(studio_id):
    _, role = require_auth()
    require_role(role, {"StudioAdmin"})
    helpers.get_studio(studio_id)
    body = helpers.get_json_body()
    helpers.require_fields(body, ["title", "venue_capacity", "event_start_utc", "registration_deadline_utc"])
    title = helpers.require_str(body, "title")
    capacity = helpers.require_int(body, "venue_capacity", minimum=0)
    event_ms = helpers.parse_iso_ms(body["event_start_utc"])
    deadline_ms = helpers.parse_iso_ms(body["registration_deadline_utc"])
    if not (deadline_ms < event_ms):
        errors.raise_error(errors.ERR_INVALID_REQUEST, "registration_deadline_utc must be < event_start_utc")
    rec = db.init_record({
        "studio_id": studio_id,
        "title": title,
        "venue_capacity": capacity,
        "event_start_utc": helpers.ms_to_iso(event_ms),
        "registration_deadline_utc": helpers.ms_to_iso(deadline_ms),
        "confirmed_count": 0,
        "waitlist_count": 0,
        "status": "REG_OPEN",
    })
    db.recital_events[rec["id"]] = rec
    return success(helpers.serialize(rec), status=201)


@app.route("/studios/<studio_id>/recital-events", methods=["GET"])
def list_recital_events(studio_id):
    _, role = require_auth()
    require_role(role, {"StudioAdmin", "Instructor", "ParentGuardian"})
    helpers.get_studio(studio_id)
    rows = [e for e in db.recital_events.values() if e["studio_id"] == studio_id]
    page, pg = helpers.paginate(rows)
    return success([helpers.serialize(r) for r in page], status=200, is_array=True, pagination=pg)


@app.route("/studios/<studio_id>/recital-events/<event_id>", methods=["GET"])
def get_recital_event_ep(studio_id, event_id):
    _, role = require_auth()
    require_role(role, {"StudioAdmin", "Instructor", "ParentGuardian"})
    helpers.get_studio(studio_id)
    e = helpers.get_event(studio_id, event_id)
    return success(helpers.serialize(e), status=200)


@app.route("/studios/<studio_id>/recital-events/<event_id>/close-registration", methods=["POST"])
def close_registration(studio_id, event_id):
    _, role = require_auth()
    require_role(role, {"StudioAdmin"})
    helpers.get_studio(studio_id)
    ev = helpers.get_event(studio_id, event_id)
    if ev["status"] != "REG_OPEN":
        errors.raise_error(errors.ERR_INVALID_STATE, "Event not REG_OPEN")
    ev["status"] = "REG_CLOSED"
    db.touch(ev)
    services.recompute_performance_order(ev)
    return success(helpers.serialize(ev), status=200)


@app.route("/studios/<studio_id>/recital-events/<event_id>/complete", methods=["POST"])
def complete_recital_event(studio_id, event_id):
    _, role = require_auth()
    require_role(role, {"StudioAdmin"})
    studio = helpers.get_studio(studio_id)
    ev = helpers.get_event(studio_id, event_id)
    if ev["status"] != "REG_CLOSED":
        errors.raise_error(errors.ERR_INVALID_STATE, "Event not REG_CLOSED")
    current_ms = helpers.parse_iso_ms(studio["current_utc"])
    if current_ms < helpers.parse_iso_ms(ev["event_start_utc"]):
        errors.raise_error(errors.ERR_EVENT_NOT_STARTED, "Event has not started")
    ev["status"] = "COMPLETED"
    db.touch(ev)
    return success(helpers.serialize(ev), status=200)


@app.route("/studios/<studio_id>/recital-events/<event_id>/cancel", methods=["POST"])
def cancel_recital_event(studio_id, event_id):
    _, role = require_auth()
    require_role(role, {"StudioAdmin"})
    helpers.get_studio(studio_id)
    ev = helpers.get_event(studio_id, event_id)
    if ev["status"] not in ("REG_OPEN", "REG_CLOSED"):
        errors.raise_error(errors.ERR_INVALID_STATE, "Event not in cancellable state")
    ev["status"] = "CANCELLED"
    db.touch(ev)
    for reg in db.recital_registrations.values():
        if reg["recital_event_id"] == event_id and reg["status"] in ("CONFIRMED", "WAITLISTED"):
            reg["status"] = "WITHDRAWN"
            db.touch(reg)
    services.recompute_event_counts(ev)
    return success(helpers.serialize(ev), status=200)


# ===========================================================================
# RecitalRegistration
# ===========================================================================
@app.route("/studios/<studio_id>/recital-registrations", methods=["POST"])
def create_registration(studio_id):
    _, role = require_auth()
    require_role(role, {"StudioAdmin", "ParentGuardian"})
    studio = helpers.get_studio(studio_id)
    body = helpers.get_json_body()
    helpers.require_fields(body, ["recital_event_id", "student_id"])
    event_id = helpers.require_str(body, "recital_event_id")
    student_id = helpers.require_str(body, "student_id")
    # referential scope
    ev = db.recital_events.get(event_id)
    if ev is None or ev["studio_id"] != studio_id:
        errors.raise_error(errors.ERR_CROSS_STUDIO_REFERENCE, "recital_event_id not in this studio")
    student = db.students.get(student_id)
    if student is None:
        errors.raise_error(errors.ERR_CROSS_STUDIO_REFERENCE, "student_id not in this studio")
    fam = db.families.get(student["family_id"])
    if fam is None or fam["studio_id"] != studio_id:
        errors.raise_error(errors.ERR_CROSS_STUDIO_REFERENCE, "student_id not in this studio")
    # registration open + before deadline
    current_ms = helpers.parse_iso_ms(studio["current_utc"])
    if ev["status"] != "REG_OPEN" or current_ms >= helpers.parse_iso_ms(ev["registration_deadline_utc"]):
        errors.raise_error(errors.ERR_REGISTRATION_CLOSED, "Registration closed")
    # at most one non-WITHDRAWN per event
    for reg in db.recital_registrations.values():
        if reg["recital_event_id"] == event_id and reg["student_id"] == student_id \
                and reg["status"] != "WITHDRAWN":
            errors.raise_error(errors.ERR_DUPLICATE_REGISTRATION, "Duplicate registration")
    status = "CONFIRMED" if ev["confirmed_count"] < ev["venue_capacity"] else "WAITLISTED"
    rec = db.init_record({
        "recital_event_id": event_id,
        "student_id": student_id,
        "registered_utc": studio["current_utc"],
        "performance_order": 0,
        "status": status,
    })
    db.recital_registrations[rec["id"]] = rec
    services.recompute_event_counts(ev)
    services.recompute_performance_order(ev)
    return success(helpers.serialize(rec), status=201)


@app.route("/studios/<studio_id>/recital-registrations", methods=["GET"])
def list_registrations(studio_id):
    _, role = require_auth()
    require_role(role, {"StudioAdmin", "ParentGuardian"})
    helpers.get_studio(studio_id)
    ev_ids = {e["id"] for e in db.recital_events.values() if e["studio_id"] == studio_id}
    rows = [r for r in db.recital_registrations.values() if r["recital_event_id"] in ev_ids]
    for key in ("recital_event_id", "student_id"):
        val = request.args.get(key)
        if val is not None:
            rows = [r for r in rows if r[key] == val]
    page, pg = helpers.paginate(rows)
    return success([helpers.serialize(r) for r in page], status=200, is_array=True, pagination=pg)


@app.route("/studios/<studio_id>/recital-registrations/<reg_id>", methods=["GET"])
def get_registration_ep(studio_id, reg_id):
    _, role = require_auth()
    require_role(role, {"StudioAdmin", "ParentGuardian"})
    helpers.get_studio(studio_id)
    r = helpers.get_registration(studio_id, reg_id)
    return success(helpers.serialize(r), status=200)


@app.route("/studios/<studio_id>/recital-registrations/<reg_id>/withdraw", methods=["POST"])
def withdraw_registration(studio_id, reg_id):
    _, role = require_auth()
    require_role(role, {"StudioAdmin", "ParentGuardian"})
    helpers.get_studio(studio_id)
    reg = helpers.get_registration(studio_id, reg_id)
    if reg["status"] not in ("CONFIRMED", "WAITLISTED"):
        errors.raise_error(errors.ERR_INVALID_STATE, "Registration not active")
    was_confirmed = reg["status"] == "CONFIRMED"
    reg["status"] = "WITHDRAWN"
    db.touch(reg)
    ev = db.recital_events.get(reg["recital_event_id"])
    services.recompute_event_counts(ev)
    if was_confirmed:
        services.promote_waitlist(ev)
    else:
        services.recompute_performance_order(ev)
    return success(helpers.serialize(reg), status=200)


# ===========================================================================
# InstrumentRental
# ===========================================================================
@app.route("/studios/<studio_id>/instrument-rentals", methods=["POST"])
def create_rental(studio_id):
    _, role = require_auth()
    require_role(role, {"StudioAdmin", "ParentGuardian"})
    helpers.get_studio(studio_id)
    body = helpers.get_json_body()
    helpers.require_fields(body, ["family_id", "instrument_unit_code", "period_fee_cents",
                                  "rental_start_utc", "rental_end_utc"])
    family_id = helpers.require_str(body, "family_id")
    unit_code = helpers.require_str(body, "instrument_unit_code")
    fee = helpers.require_int(body, "period_fee_cents", minimum=0)
    start_ms = helpers.parse_iso_ms(body["rental_start_utc"])
    end_ms = helpers.parse_iso_ms(body["rental_end_utc"])
    if not (end_ms > start_ms):
        errors.raise_error(errors.ERR_INVALID_REQUEST, "rental_end_utc must be > rental_start_utc")
    # referential scope: family in this studio
    fam = db.families.get(family_id)
    if fam is None or fam["studio_id"] != studio_id:
        errors.raise_error(errors.ERR_CROSS_STUDIO_REFERENCE, "family_id not in this studio")
    # closed-interval unit overlap
    if services.instrument_unit_conflict(studio_id, unit_code, start_ms, end_ms):
        errors.raise_error(errors.ERR_INSTRUMENT_UNIT_UNAVAILABLE, "Instrument unit unavailable")
    rec = db.init_record({
        "studio_id": studio_id,
        "family_id": family_id,
        "instrument_unit_code": unit_code,
        "period_fee_cents": fee,
        "rental_start_utc": helpers.ms_to_iso(start_ms),
        "rental_end_utc": helpers.ms_to_iso(end_ms),
        "status": "RESERVED",
    })
    db.instrument_rentals[rec["id"]] = rec
    return success(helpers.serialize(rec), status=201)


@app.route("/studios/<studio_id>/instrument-rentals", methods=["GET"])
def list_rentals(studio_id):
    _, role = require_auth()
    require_role(role, {"StudioAdmin", "ParentGuardian", "BillingClerk"})
    helpers.get_studio(studio_id)
    rows = [r for r in db.instrument_rentals.values() if r["studio_id"] == studio_id]
    for key in ("family_id", "instrument_unit_code"):
        val = request.args.get(key)
        if val is not None:
            rows = [r for r in rows if r[key] == val]
    page, pg = helpers.paginate(rows)
    return success([helpers.serialize(r) for r in page], status=200, is_array=True, pagination=pg)


@app.route("/studios/<studio_id>/instrument-rentals/<rental_id>", methods=["GET"])
def get_rental_ep(studio_id, rental_id):
    _, role = require_auth()
    require_role(role, {"StudioAdmin", "ParentGuardian", "BillingClerk"})
    helpers.get_studio(studio_id)
    r = helpers.get_rental(studio_id, rental_id)
    return success(helpers.serialize(r), status=200)


@app.route("/studios/<studio_id>/instrument-rentals/<rental_id>/activate", methods=["POST"])
def activate_rental(studio_id, rental_id):
    _, role = require_auth()
    require_role(role, {"StudioAdmin"})
    studio = helpers.get_studio(studio_id)
    r = helpers.get_rental(studio_id, rental_id)
    if r["status"] != "RESERVED":
        errors.raise_error(errors.ERR_INVALID_STATE, "Rental not RESERVED")
    current_ms = helpers.parse_iso_ms(studio["current_utc"])
    if current_ms < helpers.parse_iso_ms(r["rental_start_utc"]):
        errors.raise_error(errors.ERR_RENTAL_NOT_STARTED, "Rental has not started")
    r["status"] = "ACTIVE"
    db.touch(r)
    return success(helpers.serialize(r), status=200)


@app.route("/studios/<studio_id>/instrument-rentals/<rental_id>/return", methods=["POST"])
def return_rental(studio_id, rental_id):
    _, role = require_auth()
    require_role(role, {"StudioAdmin"})
    helpers.get_studio(studio_id)
    r = helpers.get_rental(studio_id, rental_id)
    if r["status"] not in ("RESERVED", "ACTIVE"):
        errors.raise_error(errors.ERR_INVALID_STATE, "Rental not RESERVED/ACTIVE")
    r["status"] = "RETURNED"
    db.touch(r)
    return success(helpers.serialize(r), status=200)


@app.route("/studios/<studio_id>/instrument-rentals/<rental_id>/cancel", methods=["POST"])
def cancel_rental(studio_id, rental_id):
    _, role = require_auth()
    require_role(role, {"StudioAdmin", "ParentGuardian"})
    helpers.get_studio(studio_id)
    r = helpers.get_rental(studio_id, rental_id)
    if r["status"] != "RESERVED":
        errors.raise_error(errors.ERR_INVALID_STATE, "Rental not RESERVED")
    r["status"] = "CANCELLED"
    db.touch(r)
    return success(helpers.serialize(r), status=200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
