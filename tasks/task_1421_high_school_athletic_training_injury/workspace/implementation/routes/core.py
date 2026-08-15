"""Routes: staff, athletes, physicals, baseline tests."""
from flask import Blueprint, request

import db
from domain import (
    INSTRUMENTS, POSTURES, SEXES, SPORTS, STAFF_ROLES, TEAM_LEVELS,
    VALIDITY_POLICIES, PHYSICAL_OUTCOMES, PHYSICAL_STATUSES, BASELINE_STATUSES,
    baseline_valid_until, body_json, date_start_dt, is_int, new_resource,
    now_dt, opt_enum, opt_string, physical_expires_on, posture_dependent_recompute,
    recompute_posture, req_enum, req_field, req_int, req_number, req_string,
    ser_athlete, ser_baseline, ser_physical, ser_staff, set_props, parse_date,
    parse_dt, opt_string_list, get_path_resource,
)
from errors import ApiError
from middleware import require_roles
from response import success_list, success_object

bp = Blueprint("core", __name__)

ALL_STAFF_ROLES = ["SystemAdmin", "AthleticTrainer", "AthleticDirector", "SchoolNurse", "Physician", "TeamCoach"]
MEDICAL_READ_ROLES = ["SystemAdmin", "AthleticTrainer", "AthleticDirector", "SchoolNurse", "Physician"]


def parse_pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def list_response(records, serializer, filters):
    items = [r for r in records if all(f(r) for f in filters)]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(items)
    limit, offset = parse_pagination()
    page = items[offset:offset + limit]
    return success_list([serializer(r) for r in page], total, limit, offset)


def query_filter(field, transform=None):
    raw = request.args.get(field)
    if raw is None:
        return None
    if transform is not None:
        try:
            value = transform(raw)
        except (TypeError, ValueError):
            return lambda r: False
    else:
        value = raw
    return lambda r: r.get(field) == value


def parse_bool_param(raw):
    if raw.lower() in ("true", "1", "yes"):
        return True
    if raw.lower() in ("false", "0", "no"):
        return False
    raise ValueError(raw)


# --------------------------------------------------------------------------
# Staff
# --------------------------------------------------------------------------
@bp.post("/staff")
@require_roles("SystemAdmin")
def create_staff(ctx):
    body = body_json()
    full_name = req_string(body, "full_name")
    role_type = req_enum(body, "role_type", STAFF_ROLES)
    certs = opt_string_list(body, "sport_certifications", default=[], allowed=SPORTS)
    is_active = body.get("is_active", True)
    if not isinstance(is_active, bool):
        raise ApiError("ERR_INVALID_REQUEST", "Field 'is_active' must be a boolean.")
    rec = new_resource(
        {
            "full_name": full_name,
            "role_type": role_type,
            "sport_certifications": certs,
            "is_active": is_active,
        }
    )
    db.staff[rec["id"]] = rec
    return success_object(ser_staff(rec), 201)


@bp.get("/staff")
@require_roles(*ALL_STAFF_ROLES)
def list_staff(ctx):
    filters = []
    f = query_filter("role_type")
    if f:
        filters.append(f)
    raw_active = request.args.get("is_active")
    if raw_active is not None:
        try:
            active = parse_bool_param(raw_active)
        except ValueError:
            active = None
        filters.append(lambda r: r["is_active"] is active)
    return list_response(list(db.staff.values()), ser_staff, filters)


@bp.get("/staff/<staffId>")
@require_roles(*ALL_STAFF_ROLES)
def get_staff(ctx, staffId):
    rec = get_path_resource(
        db.staff, staffId, "ERR_STAFF_NOT_FOUND", "Staff id does not exist.")
    return success_object(ser_staff(rec))


@bp.patch("/staff/<staffId>")
@require_roles("SystemAdmin")
def patch_staff(ctx, staffId):
    rec = get_path_resource(
        db.staff, staffId, "ERR_STAFF_NOT_FOUND", "Staff id does not exist.")
    body = body_json()
    if "is_active" in body:
        if not isinstance(body["is_active"], bool):
            raise ApiError("ERR_INVALID_REQUEST", "Field 'is_active' must be a boolean.")
        set_props(rec, is_active=body["is_active"])
    return success_object(ser_staff(rec))


# --------------------------------------------------------------------------
# Athletes
# --------------------------------------------------------------------------
@bp.post("/athletes")
@require_roles("AthleticTrainer", "SystemAdmin")
def create_athlete(ctx):
    body = body_json()
    full_name = req_string(body, "full_name")
    dob = parse_date(req_field(body, "date_of_birth"), "date_of_birth")
    grade = req_int(body, "grade")
    if grade < 9 or grade > 12:
        raise ApiError("ERR_INVALID_REQUEST", "Field 'grade' must be an integer in [9, 12].")
    sex = req_enum(body, "sex", SEXES)
    sport = req_enum(body, "primary_sport", SPORTS)
    level = req_enum(body, "team_level", TEAM_LEVELS)
    guardian_name = req_string(body, "guardian_name")
    guardian_user_id = req_string(body, "guardian_user_id")
    guardian_email = opt_string(body, "guardian_email")
    guardian_phone = opt_string(body, "guardian_phone")
    rec = new_resource(
        {
            "full_name": full_name,
            "date_of_birth": dob,
            "grade": grade,
            "sex": sex,
            "primary_sport": sport,
            "team_level": level,
            "guardian_name": guardian_name,
            "guardian_user_id": guardian_user_id,
            "guardian_email": guardian_email,
            "guardian_phone": guardian_phone,
            "participation_posture": "NOT_CLEARED",
            "posture_reasons": ["NO_VERIFIED_PHYSICAL"],
        }
    )
    db.athletes[rec["id"]] = rec
    return success_object(ser_athlete(rec), 201)


@bp.get("/athletes")
@require_roles(*ALL_STAFF_ROLES)
def list_athletes(ctx):
    filters = []
    for field in ("primary_sport", "team_level", "participation_posture"):
        f = query_filter(field)
        if f:
            filters.append(f)
    return list_response(list(db.athletes.values()), ser_athlete, filters)


@bp.get("/athletes/<athleteId>")
@require_roles(*ALL_STAFF_ROLES, "ParentGuardian")
def get_athlete(ctx, athleteId):
    rec = get_path_resource(
        db.athletes, athleteId, "ERR_ATHLETE_NOT_FOUND", "Athlete id does not exist.")
    if ctx["role"] == "ParentGuardian" and ctx["uid"] != rec["guardian_user_id"]:
        raise ApiError("ERR_OWNERSHIP_MISMATCH", "Guardians may only view their own child.")
    return success_object(ser_athlete(rec))


@bp.get("/athletes/<athleteId>/clearance")
@require_roles(*ALL_STAFF_ROLES)
def get_athlete_clearance(ctx, athleteId):
    rec = get_path_resource(
        db.athletes, athleteId, "ERR_ATHLETE_NOT_FOUND", "Athlete id does not exist.")
    verified = [
        p for p in db.physicals.values()
        if p["athlete_id"] == athleteId and p["verified_by_staff_id"] is not None
    ]
    physical_expires = None
    if verified:
        latest = max(verified, key=lambda p: (date_start_dt(p["exam_date"]), p["created_at"], p["_seq"]))
        physical_expires = latest["expires_on"]
    currents = [
        b for b in db.baselines.values()
        if b["athlete_id"] == athleteId and b["status"] == "CURRENT"
    ]
    baseline_until = None
    if currents:
        latest_b = max(currents, key=lambda b: (date_start_dt(b["test_date"]), b["created_at"], b["_seq"]))
        baseline_until = latest_b["valid_until"]
    return success_object(
        {
            "athlete_id": athleteId,
            "participation_posture": rec["participation_posture"],
            "posture_reasons": list(rec["posture_reasons"]),
            "physical_expires_on": physical_expires,
            "baseline_valid_until": baseline_until,
        }
    )


# --------------------------------------------------------------------------
# Pre-participation physicals
# --------------------------------------------------------------------------
@bp.post("/physicals")
@require_roles("AthleticTrainer", "SchoolNurse")
def create_physical(ctx):
    body = body_json()
    athlete_id = req_string(body, "athlete_id")
    exam_date = parse_date(req_field(body, "exam_date"), "exam_date")
    physician_name = req_string(body, "examining_physician_name")
    outcome = req_enum(body, "outcome", PHYSICAL_OUTCOMES)
    policy = req_enum(body, "validity_policy", VALIDITY_POLICIES)
    restriction_notes = opt_string(body, "restriction_notes")

    athlete = db.athletes.get(athlete_id)
    if athlete is None:
        raise ApiError("ERR_ATHLETE_NOT_FOUND", "Athlete id does not exist.")
    if date_start_dt(exam_date) > now_dt():
        raise ApiError("ERR_INVALID_DATE_RANGE", "exam_date may not lie in the future.")

    rec = new_resource(
        {
            "athlete_id": athlete_id,
            "exam_date": exam_date,
            "examining_physician_name": physician_name,
            "outcome": outcome,
            "validity_policy": policy,
            "restriction_notes": restriction_notes,
            "recorded_by_staff_id": ctx["uid"],
            "verified_by_staff_id": None,
            "expires_on": physical_expires_on(exam_date, policy),
            "status": "RECORDED",
        }
    )
    db.physicals[rec["id"]] = rec
    return success_object(ser_physical(rec), 201)


@bp.get("/physicals")
@require_roles(*MEDICAL_READ_ROLES)
def list_physicals(ctx):
    filters = []
    for field in ("athlete_id", "recorded_by_staff_id", "verified_by_staff_id", "status"):
        f = query_filter(field)
        if f:
            filters.append(f)
    return list_response(list(db.physicals.values()), ser_physical, filters)


@bp.get("/physicals/<physicalId>")
@require_roles(*MEDICAL_READ_ROLES)
def get_physical(ctx, physicalId):
    rec = get_path_resource(
        db.physicals, physicalId, "ERR_PHYSICAL_NOT_FOUND", "Physical id does not exist.")
    return success_object(ser_physical(rec))


@bp.post("/physicals/<physicalId>/verify")
@require_roles("SchoolNurse")
def verify_physical(ctx, physicalId):
    rec = get_path_resource(
        db.physicals, physicalId, "ERR_PHYSICAL_NOT_FOUND", "Physical id does not exist.")
    if rec["status"] != "RECORDED":
        raise ApiError("ERR_INVALID_STATE", "Only a RECORDED physical can be verified.")
    if ctx["uid"] == rec["recorded_by_staff_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The verifying nurse may not be the staff member who recorded the physical.",
        )
    set_props(rec, status="VERIFIED", verified_by_staff_id=ctx["uid"])
    recompute_posture(rec["athlete_id"])
    posture_dependent_recompute(rec["athlete_id"])
    return success_object(ser_physical(rec))


@bp.post("/physicals/<physicalId>/void")
@require_roles("AthleticTrainer")
def void_physical(ctx, physicalId):
    rec = get_path_resource(
        db.physicals, physicalId, "ERR_PHYSICAL_NOT_FOUND", "Physical id does not exist.")
    if rec["status"] != "RECORDED":
        raise ApiError("ERR_INVALID_STATE", "Only a RECORDED physical can be voided.")
    set_props(rec, status="VOIDED")
    recompute_posture(rec["athlete_id"])
    posture_dependent_recompute(rec["athlete_id"])
    return success_object(ser_physical(rec))


# --------------------------------------------------------------------------
# Baseline concussion tests
# --------------------------------------------------------------------------
@bp.post("/baseline-tests")
@require_roles("AthleticTrainer", "SchoolNurse")
def create_baseline(ctx):
    body = body_json()
    athlete_id = req_string(body, "athlete_id")
    test_date = parse_date(req_field(body, "test_date"), "test_date")
    instrument = req_enum(body, "instrument", INSTRUMENTS)
    symptom_score = req_int(body, "symptom_score")
    if symptom_score < 0 or symptom_score > 132:
        raise ApiError("ERR_INVALID_REQUEST", "Field 'symptom_score' must be in [0, 132].")
    memory_index = req_number(body, "memory_index")
    if memory_index < 0 or memory_index > 100:
        raise ApiError("ERR_INVALID_REQUEST", "Field 'memory_index' must be in [0, 100].")
    reaction_time_ms = req_number(body, "reaction_time_ms")
    if reaction_time_ms <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "Field 'reaction_time_ms' must be positive.")
    balance_errors = req_int(body, "balance_errors")
    if balance_errors < 0 or balance_errors > 60:
        raise ApiError("ERR_INVALID_REQUEST", "Field 'balance_errors' must be in [0, 60].")

    athlete = db.athletes.get(athlete_id)
    if athlete is None:
        raise ApiError("ERR_ATHLETE_NOT_FOUND", "Athlete id does not exist.")
    if date_start_dt(test_date) > now_dt():
        raise ApiError("ERR_INVALID_DATE_RANGE", "test_date may not lie in the future.")

    rec = new_resource(
        {
            "athlete_id": athlete_id,
            "test_date": test_date,
            "instrument": instrument,
            "symptom_score": symptom_score,
            "memory_index": memory_index,
            "reaction_time_ms": reaction_time_ms,
            "balance_errors": balance_errors,
            "administered_by_staff_id": ctx["uid"],
            "valid_until": baseline_valid_until(test_date),
            "status": "CURRENT",
        }
    )
    db.baselines[rec["id"]] = rec
    # One CURRENT baseline per athlete: the new test supersedes the old one.
    for other in db.baselines.values():
        if (
            other["id"] != rec["id"]
            and other["athlete_id"] == athlete_id
            and other["status"] == "CURRENT"
        ):
            set_props(other, status="SUPERSEDED")
    recompute_posture(athlete_id)
    posture_dependent_recompute(athlete_id)
    return success_object(ser_baseline(rec), 201)


@bp.get("/baseline-tests")
@require_roles(*MEDICAL_READ_ROLES)
def list_baselines(ctx):
    filters = []
    for field in ("athlete_id", "administered_by_staff_id", "status"):
        f = query_filter(field)
        if f:
            filters.append(f)
    return list_response(list(db.baselines.values()), ser_baseline, filters)


@bp.get("/baseline-tests/<testId>")
@require_roles(*MEDICAL_READ_ROLES)
def get_baseline(ctx, testId):
    rec = get_path_resource(
        db.baselines, testId, "ERR_BASELINE_NOT_FOUND", "Baseline test id does not exist.")
    return success_object(ser_baseline(rec))
