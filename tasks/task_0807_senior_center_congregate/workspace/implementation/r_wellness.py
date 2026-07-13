"""Wellness programs & enrollments, volunteer shifts, and the logical clock."""
from flask import Blueprint, request

from store import db, base_common, touch, iso_of
from core import (
    require_actor, authorize, get_body, ok_object, ok_array, paginate,
    req_str, req_int, req_bool, req_number, req_enum, err, parse_dt,
)
from lookups import get_program, get_participant, get_enrollment
from serializers import ser_program, ser_enrollment, ser_volunteer_shift

bp = Blueprint("wellness", __name__)

WELLNESS_MODELS = {"CDSMP", "DPP", "ENHANCE_FITNESS", "MATTER_OF_BALANCE"}
LAPSE_ABSENCE_THRESHOLD = 2


# ---------------------------- WellnessProgram ------------------------------
@bp.post("/wellness-programs")
def create_program():
    actor = require_actor()
    authorize(actor, {"CenterAdmin", "Coordinator"})
    body = get_body()
    title = req_str(body, "title")
    model = req_enum(body, "model", WELLNESS_MODELS)
    total_sessions = req_int(body, "total_sessions", minimum=1)
    fidelity = req_int(body, "fidelity_min_sessions", minimum=1)
    if fidelity > total_sessions:
        raise err("ERR_VALIDATION", "fidelity_min_sessions must be <= total_sessions")
    rec = base_common()
    rec.update({
        "title": title,
        "model": model,
        "total_sessions": total_sessions,
        "fidelity_min_sessions": fidelity,
    })
    db.programs[rec["id"]] = rec
    return ok_object(ser_program(rec), 201)


# --------------------------- WellnessEnrollment ----------------------------
@bp.post("/wellness-enrollments")
def create_enrollment():
    actor = require_actor()
    authorize(actor, {"Coordinator"})
    body = get_body()
    program_id = req_str(body, "program_id")
    participant_id = req_str(body, "participant_id")
    get_program(program_id)
    get_participant(participant_id)
    rec = base_common()
    rec.update({
        "program_id": program_id,
        "participant_id": participant_id,
        "sessions_attended": 0,
        "consecutive_absences": 0,
        "absences_total": 0,
        "status": "ACTIVE",
    })
    db.enrollments[rec["id"]] = rec
    return ok_object(ser_enrollment(rec), 201)


@bp.get("/wellness-enrollments/<eid>")
def get_enrollment_route(eid):
    actor = require_actor()
    authorize(actor, {"CenterAdmin", "Coordinator", "Participant", "Auditor"})
    return ok_object(ser_enrollment(get_enrollment(eid)))


@bp.get("/wellness-enrollments")
def list_enrollments():
    actor = require_actor()
    authorize(actor, {"CenterAdmin", "Coordinator", "Participant", "Auditor"})
    rows = list(db.enrollments.values())
    args = request.args
    for key in ("program_id", "participant_id"):
        if key in args:
            rows = [r for r in rows if r.get(key) == args.get(key)]
    window, page = paginate(rows)
    return ok_array([ser_enrollment(r) for r in window], page)


@bp.post("/wellness-enrollments/<eid>/log-session")
def log_session(eid):
    actor = require_actor()
    authorize(actor, {"Coordinator"})
    body = get_body()
    attended = req_bool(body, "attended")
    rec = get_enrollment(eid)
    if rec["status"] not in ("ACTIVE", "LAPSED"):
        raise err("ERR_INVALID_STATE", "Enrollment is terminal")
    if attended:
        rec["sessions_attended"] += 1
        rec["consecutive_absences"] = 0
        if rec["status"] == "LAPSED":
            rec["status"] = "ACTIVE"  # re-engagement closes the ACTIVE<->LAPSED cycle
    else:
        new_consec = rec["consecutive_absences"] + 1
        rec["consecutive_absences"] = new_consec
        rec["absences_total"] += 1
        if rec["status"] == "ACTIVE" and new_consec >= LAPSE_ABSENCE_THRESHOLD:
            rec["status"] = "LAPSED"
    touch(rec)
    return ok_object(ser_enrollment(rec))


@bp.post("/wellness-enrollments/<eid>/finalize")
def finalize_enrollment(eid):
    actor = require_actor()
    authorize(actor, {"Coordinator"})
    rec = get_enrollment(eid)
    if rec["status"] not in ("ACTIVE", "LAPSED"):
        raise err("ERR_INVALID_STATE", "Only ACTIVE or LAPSED enrollments can be finalized")
    program = db.programs.get(rec["program_id"])
    fidelity = program["fidelity_min_sessions"] if program else 0
    if rec["sessions_attended"] >= fidelity:
        rec["status"] = "GRADUATED"
    else:
        rec["status"] = "WITHDRAWN"
    touch(rec)
    return ok_object(ser_enrollment(rec))


# ----------------------------- VolunteerShift ------------------------------
@bp.post("/volunteer-shifts")
def create_volunteer_shift():
    actor = require_actor()
    authorize(actor, {"CenterAdmin", "Coordinator"})
    body = get_body()
    volunteer_name = req_str(body, "volunteer_name")
    role = req_str(body, "role")
    hours = req_number(body, "hours", gt=0)
    service_raw = req_str(body, "service_date")
    parse_dt(service_raw, "service_date")
    rec = base_common()
    rec.update({
        "volunteer_name": volunteer_name,
        "role": role,
        "hours": hours,
        "service_date": service_raw,
    })
    db.volunteer_shifts[rec["id"]] = rec
    return ok_object(ser_volunteer_shift(rec), 201)


@bp.get("/volunteer-shifts")
def list_volunteer_shifts():
    actor = require_actor()
    authorize(actor, {"CenterAdmin", "Coordinator", "Auditor"})
    rows = list(db.volunteer_shifts.values())
    if "volunteer_name" in request.args:
        rows = [r for r in rows if r["volunteer_name"] == request.args.get("volunteer_name")]
    window, page = paginate(rows)
    return ok_array([ser_volunteer_shift(r) for r in window], page)


# ------------------------------- Clock -------------------------------------
@bp.post("/_clock/set_current_utc")
def set_clock():
    actor = require_actor()
    authorize(actor, {"CenterAdmin"})
    body = get_body()
    to_iso = req_str(body, "to_iso8601")
    db.clock = parse_dt(to_iso, "to_iso8601")
    return ok_object({"current_utc": iso_of(db.clock)})
