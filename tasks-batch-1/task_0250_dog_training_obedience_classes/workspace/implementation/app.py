"""Dog Training & Obedience Classes API — Flask entry point."""
import os

from flask import Flask, request

import domain
import serializers as S
from common import (
    get_user_context, require_role, get_json_body, require_fields,
    check_string, check_enum, check_int, check_bool, check_array,
    parse_pagination, paginate, sorted_by_created, touch,
)
from domain import LEVELS_ORDER, CLASS_LEVELS, PREREQ_LEVELS
from errors import ApiError, err
from response import success, error
from store import db, new_id, now_iso

app = Flask(__name__)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(e):
    return error(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def handle_404(e):
    return error("ERR_INVALID_REQUEST", 400, "Unknown route")


@app.errorhandler(405)
def handle_405(e):
    return error("ERR_INVALID_REQUEST", 400, "Method not allowed")


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return error(e.error_id, e.http_status, e.message)
    return error("ERR_INVALID_REQUEST", 400, "Unexpected error: %s" % str(e))


# ---------------------------------------------------------------------------
# Lookup helpers (existence) — raise the right not-found error
# ---------------------------------------------------------------------------
from lookups import (  # noqa: E402
    get_owner, get_dog, get_trainer, get_series, get_session,
    get_enrollment, get_package, get_attendance, get_makeup,
    get_redemption, get_certificate, list_response,
)


# ---------------------------------------------------------------------------
# Ownership helper
# ---------------------------------------------------------------------------
def assert_owner_owns_dog(user_id, role, dog):
    if role == "Owner" and dog["owner_id"] != user_id:
        raise err("ERR_NOT_DOG_OWNER", "Acting owner does not own this dog")


# ===========================================================================
# OWNERS
# ===========================================================================
@app.route("/owners", methods=["POST"])
def create_owner():
    user_id, role = get_user_context()
    require_role(role, {"FrontDesk", "AdminManager"})
    body = get_json_body()
    full_name = check_string(body, "full_name")
    email = check_string(body, "email")
    phone = check_string(body, "phone")
    for existing in db.owners.values():
        if existing["email"] == email:
            raise err("ERR_DUPLICATE_OWNER_EMAIL", "Owner email already in use")
    oid = new_id()
    ts = now_iso()
    owner = {
        "id": oid, "created_at": ts, "updated_at": ts, "version": 1,
        "full_name": full_name, "email": email, "phone": phone,
    }
    db.owners[oid] = owner
    return success(S.ser_owner(owner), 201)


@app.route("/owners", methods=["GET"])
def list_owners():
    user_id, role = get_user_context()
    require_role(role, {"FrontDesk", "AdminManager"})
    rows = list(db.owners.values())
    email = request.args.get("email")
    if email is not None:
        rows = [o for o in rows if o["email"] == email]
    return list_response(rows, S.ser_owner)


@app.route("/owners/<owner_id>", methods=["GET"])
def get_owner_ep(owner_id):
    user_id, role = get_user_context()
    require_role(role, {"Owner", "FrontDesk", "AdminManager"})
    owner = get_owner(owner_id)
    if role == "Owner" and owner["id"] != user_id:
        raise err("ERR_NOT_DOG_OWNER", "Owner mismatch")
    return success(S.ser_owner(owner), 200)


# ===========================================================================
# DOGS
# ===========================================================================
@app.route("/dogs", methods=["POST"])
def create_dog():
    user_id, role = get_user_context()
    require_role(role, {"Owner", "FrontDesk", "AdminManager"})
    body = get_json_body()
    owner_id = check_string(body, "owner_id")
    name = check_string(body, "name")
    breed = check_string(body, "breed")
    birth_date = check_string(body, "birth_date")
    owner = get_owner(owner_id)
    if role == "Owner" and owner_id != user_id:
        raise err("ERR_NOT_DOG_OWNER", "Owner may only register their own dog")
    did = new_id()
    ts = now_iso()
    dog = {
        "id": did, "created_at": ts, "updated_at": ts, "version": 1,
        "owner_id": owner_id, "name": name, "breed": breed, "birth_date": birth_date,
        "vaccination_posture": "UNKNOWN", "highest_completed_level": "NONE",
        "intake_status": "PENDING",
    }
    db.dogs[did] = dog
    return success(S.ser_dog(dog), 201)


@app.route("/dogs", methods=["GET"])
def list_dogs():
    user_id, role = get_user_context()
    require_role(role, {"Owner", "FrontDesk", "AdminManager"})
    rows = list(db.dogs.values())
    owner_id = request.args.get("owner_id")
    if owner_id is not None:
        rows = [d for d in rows if d["owner_id"] == owner_id]
    if role == "Owner":
        rows = [d for d in rows if d["owner_id"] == user_id]
    return list_response(rows, S.ser_dog)


@app.route("/dogs/<dog_id>", methods=["GET"])
def get_dog_ep(dog_id):
    user_id, role = get_user_context()
    require_role(role, {"Owner", "FrontDesk", "AdminManager"})
    dog = get_dog(dog_id)
    if role == "Owner" and dog["owner_id"] != user_id:
        raise err("ERR_NOT_DOG_OWNER", "Acting owner does not own this dog")
    return success(S.ser_dog(dog, refresh=True), 200)


# ===========================================================================
# VACCINATIONS
# ===========================================================================
@app.route("/dogs/<dog_id>/vaccinations", methods=["POST"])
def create_vaccination(dog_id):
    user_id, role = get_user_context()
    require_role(role, {"Owner", "FrontDesk", "AdminManager"})
    dog = get_dog(dog_id)
    assert_owner_owns_dog(user_id, role, dog)
    body = get_json_body()
    vaccine_type = check_enum(body, "vaccine_type", {"RABIES", "DHPP", "BORDETELLA"})
    administered_on = check_string(body, "administered_on")
    expires_on = check_string(body, "expires_on")
    vid = new_id()
    ts = now_iso()
    rec = {
        "id": vid, "created_at": ts,
        "dog_id": dog_id, "vaccine_type": vaccine_type,
        "administered_on": administered_on, "expires_on": expires_on,
        "voided": False,
    }
    db.vaccinations[vid] = rec
    apply_posture_change(dog)
    return success(S.ser_vaccination(rec), 201)


@app.route("/vaccinations", methods=["GET"])
def list_vaccinations():
    user_id, role = get_user_context()
    require_role(role, {"Owner", "FrontDesk", "AdminManager"})
    rows = list(db.vaccinations.values())
    dog_id = request.args.get("dog_id")
    if dog_id is not None:
        rows = [v for v in rows if v["dog_id"] == dog_id]
    if role == "Owner":
        owned = {d["id"] for d in db.dogs.values() if d["owner_id"] == user_id}
        rows = [v for v in rows if v["dog_id"] in owned]
    return list_response(rows, S.ser_vaccination)


@app.route("/vaccinations/<vaccination_id>", methods=["GET"])
def get_vaccination_ep(vaccination_id):
    user_id, role = get_user_context()
    require_role(role, {"Owner", "FrontDesk", "AdminManager"})
    rec = db.vaccinations.get(vaccination_id)
    if rec is None:
        raise err("ERR_INVALID_REQUEST", "Vaccination not found")
    if role == "Owner":
        dog = db.dogs.get(rec["dog_id"])
        if not dog or dog["owner_id"] != user_id:
            raise err("ERR_NOT_DOG_OWNER", "Not owner")
    return success(S.ser_vaccination(rec), 200)


@app.route("/vaccinations/<vaccination_id>/void", methods=["POST"])
def void_vaccination(vaccination_id):
    user_id, role = get_user_context()
    require_role(role, {"FrontDesk", "AdminManager"})
    rec = db.vaccinations.get(vaccination_id)
    if rec is None:
        raise err("ERR_INVALID_REQUEST", "Vaccination not found")
    rec["voided"] = True
    dog = db.dogs.get(rec["dog_id"])
    if dog:
        apply_posture_change(dog)
    return success(S.ser_vaccination(rec), 200)


def apply_posture_change(dog):
    """After a vaccination filing/void, recompute posture; suspend ACTIVE
    enrollments if posture is NONCOMPLIANT."""
    posture = domain.dog_posture_now(dog["id"])
    if posture == "NONCOMPLIANT":
        for e in db.enrollments.values():
            if e["dog_id"] == dog["id"] and e["status"] == "ACTIVE":
                e["status"] = "SUSPENDED"
                touch(e)
                series = db.class_series.get(e["series_id"])
                if series:
                    domain.recompute_series_seats(series)


# ===========================================================================
# BEHAVIORAL INTAKES
# ===========================================================================
@app.route("/dogs/<dog_id>/behavioral-intakes", methods=["POST"])
def create_intake(dog_id):
    user_id, role = get_user_context()
    require_role(role, {"Trainer", "FrontDesk", "AdminManager"})
    dog = get_dog(dog_id)
    body = get_json_body()
    reactivity_score = check_int(body, "reactivity_score")
    bite_history = check_bool(body, "bite_history", required=False, default=False)
    recommended_level = check_enum(body, "recommended_level", CLASS_LEVELS)
    if reactivity_score < 0 or reactivity_score > 10:
        raise err("ERR_INVALID_REQUEST", "reactivity_score must be 0..10")
    outcome = domain.compute_intake_outcome(reactivity_score, bite_history)
    iid = new_id()
    ts = now_iso()
    intake = {
        "id": iid, "created_at": ts, "updated_at": ts, "version": 1,
        "dog_id": dog_id, "reactivity_score": reactivity_score,
        "bite_history": bite_history, "recommended_level": recommended_level,
        "outcome": outcome, "requires_private_first": outcome == "FLAGGED",
    }
    db.behavioral_intakes[iid] = intake
    return success(S.ser_intake(intake), 201)


@app.route("/behavioral-intakes", methods=["GET"])
def list_intakes():
    user_id, role = get_user_context()
    require_role(role, {"Trainer", "FrontDesk", "AdminManager"})
    rows = list(db.behavioral_intakes.values())
    dog_id = request.args.get("dog_id")
    if dog_id is not None:
        rows = [i for i in rows if i["dog_id"] == dog_id]
    return list_response(rows, S.ser_intake)


@app.route("/behavioral-intakes/<intake_id>", methods=["GET"])
def get_intake_ep(intake_id):
    user_id, role = get_user_context()
    require_role(role, {"Trainer", "FrontDesk", "AdminManager"})
    intake = db.behavioral_intakes.get(intake_id)
    if intake is None:
        raise err("ERR_INVALID_REQUEST", "Intake not found")
    return success(S.ser_intake(intake), 200)


# ===========================================================================
# TRAINERS
# ===========================================================================
@app.route("/trainers", methods=["POST"])
def create_trainer():
    user_id, role = get_user_context()
    require_role(role, {"AdminManager"})
    body = get_json_body()
    full_name = check_string(body, "full_name")
    certified_levels = check_array(body, "certified_levels")
    for lvl in certified_levels:
        if lvl not in CLASS_LEVELS:
            raise err("ERR_INVALID_REQUEST", "Invalid level in certified_levels")
    handles_private = check_bool(body, "handles_private", required=False, default=True)
    tid = new_id()
    ts = now_iso()
    trainer = {
        "id": tid, "created_at": ts, "updated_at": ts, "version": 1,
        "full_name": full_name, "certified_levels": list(certified_levels),
        "handles_private": handles_private, "status": "ACTIVE",
    }
    db.trainers[tid] = trainer
    return success(S.ser_trainer(trainer), 201)


@app.route("/trainers", methods=["GET"])
def list_trainers():
    user_id, role = get_user_context()
    require_role(role, {"Trainer", "FrontDesk", "AdminManager"})
    return list_response(list(db.trainers.values()), S.ser_trainer)


@app.route("/trainers/<trainer_id>", methods=["GET"])
def get_trainer_ep(trainer_id):
    user_id, role = get_user_context()
    require_role(role, {"Trainer", "FrontDesk", "AdminManager"})
    trainer = get_trainer(trainer_id)
    return success(S.ser_trainer(trainer), 200)


# ===========================================================================
# CLASS SERIES
# ===========================================================================
@app.route("/class-series", methods=["POST"])
def create_series():
    user_id, role = get_user_context()
    require_role(role, {"AdminManager"})
    body = get_json_body()
    title = check_string(body, "title")
    level = check_enum(body, "level", CLASS_LEVELS)
    prerequisite_level = check_enum(body, "prerequisite_level", PREREQ_LEVELS,
                                    required=False, default="NONE")
    modality = check_enum(body, "modality", {"PRIVATE", "GROUP"})
    capacity = check_int(body, "capacity")
    session_count = check_int(body, "session_count")
    list_price_cents = check_int(body, "list_price_cents")
    credit_cost = check_int(body, "credit_cost")
    if modality == "PRIVATE" and capacity != 1:
        raise err("ERR_INVALID_PRIVATE_CAPACITY", "PRIVATE series capacity must equal 1")
    sid = new_id()
    ts = now_iso()
    series = {
        "id": sid, "created_at": ts, "updated_at": ts, "version": 1,
        "title": title, "level": level, "prerequisite_level": prerequisite_level,
        "modality": modality, "capacity": capacity, "session_count": session_count,
        "list_price_cents": list_price_cents, "credit_cost": credit_cost,
        "enrolled_count": 0, "seats_available": 0, "status": "DRAFT",
    }
    db.class_series[sid] = series
    return success(S.ser_series(series), 201)


@app.route("/class-series", methods=["GET"])
def list_series():
    user_id, role = get_user_context()
    require_role(role, {"Owner", "Trainer", "FrontDesk", "AdminManager"})
    rows = list(db.class_series.values())
    level = request.args.get("level")
    status = request.args.get("status")
    if level is not None:
        rows = [s for s in rows if s["level"] == level]
    if status is not None:
        rows = [s for s in rows if s["status"] == status]
    return list_response(rows, S.ser_series)


@app.route("/class-series/<series_id>", methods=["GET"])
def get_series_ep(series_id):
    user_id, role = get_user_context()
    require_role(role, {"Owner", "Trainer", "FrontDesk", "AdminManager"})
    series = get_series(series_id)
    return success(S.ser_series(series), 200)


@app.route("/class-series/<series_id>/open", methods=["POST"])
def open_series(series_id):
    user_id, role = get_user_context()
    require_role(role, {"AdminManager"})
    series = get_series(series_id)
    if series["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Series must be DRAFT to open")
    sessions = [s for s in db.class_sessions.values() if s["series_id"] == series_id]
    # business constraints (priority 6) before vaccination etc.
    if len(sessions) < series["session_count"]:
        raise err("ERR_SESSIONS_INCOMPLETE",
                  "Series must have at least session_count sessions to open")
    for s in sessions:
        trainer = db.trainers.get(s["trainer_id"])
        if not trainer or series["level"] not in trainer["certified_levels"]:
            raise err("ERR_TRAINER_LEVEL_MISMATCH",
                      "A session's trainer is not certified for the series level")
    if series["modality"] == "PRIVATE" and series["capacity"] != 1:
        raise err("ERR_INVALID_PRIVATE_CAPACITY", "PRIVATE series capacity must equal 1")
    series["status"] = "OPEN"
    series["seats_available"] = series["capacity"]
    touch(series)
    domain.recompute_series_seats(series)
    return success(S.ser_series(series), 200)


@app.route("/class-series/<series_id>/close", methods=["POST"])
def close_series(series_id):
    user_id, role = get_user_context()
    require_role(role, {"AdminManager"})
    series = get_series(series_id)
    if series["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Series must be OPEN to close")
    series["status"] = "CLOSED"
    touch(series)
    return success(S.ser_series(series), 200)


@app.route("/class-series/<series_id>/archive", methods=["POST"])
def archive_series(series_id):
    user_id, role = get_user_context()
    require_role(role, {"AdminManager"})
    series = get_series(series_id)
    if series["status"] not in ("DRAFT", "CLOSED"):
        raise err("ERR_INVALID_STATE", "Series must be DRAFT or CLOSED to archive")
    for e in db.enrollments.values():
        if e["series_id"] == series_id and e["status"] in ("ACTIVE", "WAITLISTED", "SUSPENDED"):
            raise err("ERR_SERIES_HAS_LIVE_ENROLLMENTS",
                      "Series has live enrollments")
    series["status"] = "ARCHIVED"
    touch(series)
    for s in db.class_sessions.values():
        if s["series_id"] == series_id and s["status"] == "SCHEDULED":
            s["status"] = "CANCELLED"
            touch(s)
    return success(S.ser_series(series), 200)


# ===========================================================================
# CLASS SESSIONS
# ===========================================================================
@app.route("/class-sessions", methods=["POST"])
def create_session():
    user_id, role = get_user_context()
    require_role(role, {"AdminManager"})
    body = get_json_body()
    series_id = check_string(body, "series_id")
    trainer_id = check_string(body, "trainer_id")
    sequence_index = check_int(body, "sequence_index")
    starts_at = check_string(body, "starts_at")
    ends_at = check_string(body, "ends_at")
    is_makeup_slot = check_bool(body, "is_makeup_slot", required=False, default=False)
    # existence: series then trainer (left-to-right)
    get_series(series_id)
    get_trainer(trainer_id)
    s_dt = domain.parse_dt(starts_at)
    e_dt = domain.parse_dt(ends_at)
    if s_dt is None or e_dt is None:
        raise err("ERR_INVALID_REQUEST", "Invalid datetime")
    if e_dt <= s_dt:
        raise err("ERR_INVALID_SESSION_TIMES", "ends_at must be after starts_at")
    if domain.trainer_double_booked(trainer_id, starts_at, ends_at):
        raise err("ERR_TRAINER_DOUBLE_BOOKED", "Trainer is double-booked")
    sid = new_id()
    ts = now_iso()
    session = {
        "id": sid, "created_at": ts, "updated_at": ts, "version": 1,
        "series_id": series_id, "trainer_id": trainer_id,
        "sequence_index": sequence_index, "starts_at": starts_at, "ends_at": ends_at,
        "is_makeup_slot": is_makeup_slot, "status": "SCHEDULED",
    }
    db.class_sessions[sid] = session
    return success(S.ser_session(session), 201)


@app.route("/class-sessions", methods=["GET"])
def list_sessions():
    user_id, role = get_user_context()
    require_role(role, {"Owner", "Trainer", "FrontDesk", "AdminManager"})
    rows = list(db.class_sessions.values())
    series_id = request.args.get("series_id")
    trainer_id = request.args.get("trainer_id")
    if series_id is not None:
        rows = [s for s in rows if s["series_id"] == series_id]
    if trainer_id is not None:
        rows = [s for s in rows if s["trainer_id"] == trainer_id]
    return list_response(rows, S.ser_session)


@app.route("/class-sessions/<session_id>", methods=["GET"])
def get_session_ep(session_id):
    user_id, role = get_user_context()
    require_role(role, {"Owner", "Trainer", "FrontDesk", "AdminManager"})
    session = get_session(session_id)
    return success(S.ser_session(session), 200)


@app.route("/class-sessions/<session_id>", methods=["PATCH"])
def reschedule_session(session_id):
    user_id, role = get_user_context()
    require_role(role, {"AdminManager"})
    session = get_session(session_id)
    if session["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Only SCHEDULED sessions can be rescheduled")
    body = get_json_body()
    new_trainer = session["trainer_id"]
    new_start = session["starts_at"]
    new_end = session["ends_at"]
    if "trainer_id" in body and body["trainer_id"] is not None:
        new_trainer = check_string(body, "trainer_id")
        get_trainer(new_trainer)
    if "starts_at" in body and body["starts_at"] is not None:
        new_start = check_string(body, "starts_at")
    if "ends_at" in body and body["ends_at"] is not None:
        new_end = check_string(body, "ends_at")
    s_dt = domain.parse_dt(new_start)
    e_dt = domain.parse_dt(new_end)
    if s_dt is None or e_dt is None:
        raise err("ERR_INVALID_REQUEST", "Invalid datetime")
    if e_dt <= s_dt:
        raise err("ERR_INVALID_SESSION_TIMES", "ends_at must be after starts_at")
    if domain.trainer_double_booked(new_trainer, new_start, new_end,
                                    exclude_session_id=session_id):
        raise err("ERR_TRAINER_DOUBLE_BOOKED", "Trainer is double-booked")
    session["trainer_id"] = new_trainer
    session["starts_at"] = new_start
    session["ends_at"] = new_end
    touch(session)
    return success(S.ser_session(session), 200)


@app.route("/class-sessions/<session_id>/start", methods=["POST"])
def start_session(session_id):
    user_id, role = get_user_context()
    require_role(role, {"Trainer"})
    session = get_session(session_id)
    if session["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Session must be SCHEDULED to start")
    series = db.class_series.get(session["series_id"])
    if not series or series["status"] != "OPEN":
        raise err("ERR_SERIES_NOT_OPEN", "Owning series must be OPEN")
    if session["trainer_id"] != user_id:
        raise err("ERR_NOT_SESSION_TRAINER", "Only the assigned trainer may start")
    session["status"] = "IN_PROGRESS"
    touch(session)
    return success(S.ser_session(session), 200)


@app.route("/class-sessions/<session_id>/complete", methods=["POST"])
def complete_session(session_id):
    user_id, role = get_user_context()
    require_role(role, {"Trainer"})
    session = get_session(session_id)
    if session["status"] != "IN_PROGRESS":
        raise err("ERR_INVALID_STATE", "Session must be IN_PROGRESS to complete")
    if session["trainer_id"] != user_id:
        raise err("ERR_NOT_SESSION_TRAINER", "Only the assigned trainer may complete")
    for a in db.attendance_records.values():
        if a["session_id"] == session_id and a["state"] == "EXPECTED":
            raise err("ERR_ATTENDANCE_UNMARKED", "All attendance must be marked")
    session["status"] = "COMPLETED"
    touch(session)
    # recompute progress for enrollments with PRESENT records on this (non-makeup) session
    affected = set()
    for a in db.attendance_records.values():
        if a["session_id"] == session_id and a["state"] == "PRESENT":
            affected.add(a["enrollment_id"])
    for eid in affected:
        e = db.enrollments.get(eid)
        if e:
            domain.refresh_enrollment_progress_touch(e)
    return success(S.ser_session(session), 200)


@app.route("/class-sessions/<session_id>/cancel", methods=["POST"])
def cancel_session(session_id):
    user_id, role = get_user_context()
    require_role(role, {"AdminManager"})
    session = get_session(session_id)
    if session["status"] not in ("SCHEDULED", "IN_PROGRESS"):
        raise err("ERR_INVALID_STATE", "Session must be SCHEDULED or IN_PROGRESS to cancel")
    session["status"] = "CANCELLED"
    touch(session)
    # CASCADE L1+L2: attendance EXPECTED/MAKEUP_PENDING -> MISSED_PROVIDER (makeup_eligible)
    for a in db.attendance_records.values():
        if a["session_id"] == session_id and a["state"] in ("EXPECTED", "MAKEUP_PENDING"):
            a["state"] = "MISSED_PROVIDER"
            domain.refresh_attendance_eligible(a)
            touch(a)
    # CASCADE L3: MakeupBooking whose makeup_session_id == this in REQUESTED/CONFIRMED -> CANCELLED
    for m in db.makeup_bookings.values():
        if m["makeup_session_id"] == session_id and m["status"] in ("REQUESTED", "CONFIRMED"):
            m["status"] = "CANCELLED"
            touch(m)
            src = db.attendance_records.get(m["attendance_id"])
            if src:
                src["state"] = "MISSED_PROVIDER"
                domain.refresh_attendance_eligible(src)
                touch(src)
    return success(S.ser_session(session), 200)


# ===========================================================================
# ATTENDANCE
# ===========================================================================
@app.route("/class-sessions/<session_id>/attendance", methods=["POST"])
def mark_attendance(session_id):
    user_id, role = get_user_context()
    require_role(role, {"Trainer"})
    session = get_session(session_id)
    body = get_json_body()
    attendance_id = check_string(body, "attendance_id")
    state = check_enum(body, "state", {"PRESENT", "ABSENT"})
    attendance = get_attendance(attendance_id)
    if attendance["session_id"] != session_id:
        raise err("ERR_ATTENDANCE_NOT_FOUND", "Attendance does not belong to session")
    if session["trainer_id"] != user_id:
        raise err("ERR_NOT_SESSION_TRAINER", "Only the assigned trainer may mark")
    enrollment = db.enrollments.get(attendance["enrollment_id"])
    if enrollment and enrollment["status"] == "SUSPENDED":
        raise err("ERR_INVALID_STATE", "Cannot mark attendance for a suspended enrollment")
    attendance["state"] = state
    domain.refresh_attendance_eligible(attendance)
    touch(attendance)
    return success(S.ser_attendance(attendance), 200)


@app.route("/attendance-records", methods=["GET"])
def list_attendance():
    user_id, role = get_user_context()
    require_role(role, {"Owner", "Trainer", "FrontDesk", "AdminManager"})
    rows = list(db.attendance_records.values())
    enrollment_id = request.args.get("enrollment_id")
    session_id = request.args.get("session_id")
    if enrollment_id is not None:
        rows = [a for a in rows if a["enrollment_id"] == enrollment_id]
    if session_id is not None:
        rows = [a for a in rows if a["session_id"] == session_id]
    return list_response(rows, S.ser_attendance)


@app.route("/attendance-records/<attendance_id>", methods=["GET"])
def get_attendance_ep(attendance_id):
    user_id, role = get_user_context()
    require_role(role, {"Owner", "Trainer", "FrontDesk", "AdminManager"})
    attendance = get_attendance(attendance_id)
    return success(S.ser_attendance(attendance), 200)


# ===========================================================================
# Imports for the rest of routes (enrollment, package, makeup, certificate, clock)
# ===========================================================================
import routes_enroll  # noqa: E402
import routes_package  # noqa: E402
import routes_makeup  # noqa: E402
import routes_misc  # noqa: E402

routes_enroll.register(app)
routes_package.register(app)
routes_makeup.register(app)
routes_misc.register(app)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
