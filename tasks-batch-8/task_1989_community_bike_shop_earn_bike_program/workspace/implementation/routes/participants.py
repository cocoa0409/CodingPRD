"""Earn-a-bike participants and the hour ledger (PRD §3.7, §3.8)."""

from datetime import timedelta

from flask import Blueprint, request

from db import db, _parse_iso
from errors import ApiError
from middleware import require_roles, get_body, validate_payload
from response import success
from services.core import (make_common, make_event, touch, paginate, sorted_by_created,
                           participant_hours_earned, release_reserved_bike,
                           YOUTH_REQUIRED_HOURS, ADULT_REQUIRED_HOURS, DAILY_CAP_HOURS)

bp = Blueprint("participants", __name__)

AGE_GROUPS = ["YOUTH", "ADULT"]
ACTIVITY_TYPES = ["REFURB_WORK", "SHOP_HELP", "OUTREACH", "TRAINING_ASSIST"]


def participant_view(p):
    return {
        "id": p["id"],
        "full_name": p["full_name"],
        "contact_email": p["contact_email"],
        "age_group": p["age_group"],
        "enrolled_at": p["enrolled_at"],
        "enrollment_deadline": p["enrollment_deadline"],
        "required_hours": p["required_hours"],
        "hours_earned": p["hours_earned"],
        "safety_quiz_passed": p["safety_quiz_passed"],
        "reserved_bike_id": p["reserved_bike_id"],
        "status": p["status"],
        "graduated_at": p["graduated_at"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def hour_log_view(h):
    return {
        "id": h["id"],
        "participant_id": h["participant_id"],
        "shift_id": h["shift_id"],
        "work_date": h["work_date"],
        "hours": h["hours"],
        "activity_type": h["activity_type"],
        "description": h["description"],
        "status": h["status"],
        "created_by_user_id": h["created_by_user_id"],
        "reviewed_by_user_id": h["reviewed_by_user_id"],
        "void_reason": h["void_reason"],
        "created_at": h["created_at"],
        "updated_at": h["updated_at"],
        "version": h["version"],
    }


def _get_participant(participant_id):
    p = db.participants.get(participant_id)
    if p is None:
        raise ApiError("ERR_NOT_FOUND", f"EarnABikeParticipant {participant_id} does not exist")
    return p


def _get_hour_log(hour_log_id):
    h = db.hour_logs.get(hour_log_id)
    if h is None:
        raise ApiError("ERR_NOT_FOUND", f"HourLog {hour_log_id} does not exist")
    return h


def _check_participant_ownership(role, user_id, participant_id):
    if role == "Participant" and user_id != participant_id:
        raise ApiError("ERR_FORBIDDEN", "Participants may only touch their own record")


@bp.post("/participants")
def create_participant():
    require_roles("ShopCoordinator")
    body = get_body()
    validate_payload(body, {
        "full_name": {"type": "string", "required": True},
        "contact_email": {"type": "string", "required": True},
        "age_group": {"type": "string", "required": True, "enum": AGE_GROUPS},
    })
    now = db.now()
    deadline = now + timedelta(days=90)
    p = make_common()
    p.update({
        "full_name": body["full_name"],
        "contact_email": body["contact_email"],
        "age_group": body["age_group"],
        "enrolled_at": db.now_iso(),
        "enrollment_deadline": _fmt(deadline),
        "required_hours": YOUTH_REQUIRED_HOURS if body["age_group"] == "YOUTH" else ADULT_REQUIRED_HOURS,
        "hours_earned": 0,
        "safety_quiz_passed": False,
        "reserved_bike_id": None,
        "status": "ENROLLED",
        "graduated_at": None,
    })
    db.participants[p["id"]] = p
    return success(participant_view(p), status=201)


def _fmt(dt):
    from db import fmt_ts
    return fmt_ts(dt)


@bp.get("/participants/<participant_id>")
def get_participant(participant_id):
    user_id, role = require_roles("ShopCoordinator", "ProgramDirector", "Participant")
    p = _get_participant(participant_id)
    _check_participant_ownership(role, user_id, participant_id)
    return success(participant_view(p))


@bp.get("/participants")
def list_participants():
    require_roles("ShopCoordinator", "ProgramDirector")
    rows = list(db.participants.values())
    for param in ("status", "age_group", "reserved_bike_id"):
        value = request.args.get(param)
        if value is not None:
            rows = [p for p in rows if p[param] == value]
    rows = sorted_by_created(rows)
    page, pg = paginate(rows)
    return success([participant_view(p) for p in page], pagination=pg)


@bp.post("/participants/<participant_id>/record-quiz")
def record_quiz(participant_id):
    require_roles("ShopCoordinator")
    body = get_body()
    validate_payload(body, {"passed": {"type": "boolean", "required": True}})
    p = _get_participant(participant_id)
    p["safety_quiz_passed"] = body["passed"]
    touch(p)
    return success(participant_view(p))


# ---------------------------------------------------------------------------
# Hour logs
# ---------------------------------------------------------------------------

@bp.post("/participants/<participant_id>/hour-logs")
def create_hour_log(participant_id):
    user_id, role = require_roles("ShopCoordinator", "Participant")
    body = get_body()
    validate_payload(body, {
        "work_date": {"type": "string", "required": True},
        "hours": {"type": "integer", "required": True, "min_int": 1, "max_int": 6},
        "activity_type": {"type": "string", "required": True, "enum": ACTIVITY_TYPES},
        "shift_id": {"type": "string"},
        "description": {"type": "string"},
    })
    p = _get_participant(participant_id)
    _check_participant_ownership(role, user_id, participant_id)
    # Body FK existence.
    shift = None
    if body.get("shift_id") is not None:
        shift = db.shifts.get(body["shift_id"])
        if shift is None:
            raise ApiError("ERR_NOT_FOUND", f"VolunteerShift {body['shift_id']} does not exist")

    if p["status"] not in ("ENROLLED", "HOURS_MET"):
        raise ApiError("ERR_PARTICIPANT_NOT_ACTIVE", "Participant must be ENROLLED or HOURS_MET")

    # work_date window: [enrollment date, min(current clock date, deadline date)].
    try:
        work_date = _parse_date(body["work_date"])
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", "work_date must be a YYYY-MM-DD calendar date")
    enrolled_date = _parse_iso(p["enrolled_at"]).date()
    deadline_date = _parse_iso(p["enrollment_deadline"]).date()
    window_end = min(db.today(), deadline_date)
    if work_date < enrolled_date or work_date > window_end:
        raise ApiError("ERR_WORK_DATE_OUT_OF_WINDOW", "work_date is outside the participation window")

    # Daily cap: PENDING + APPROVED hours on the work_date, including the new log, <= 6.
    existing = sum(
        h["hours"] for h in db.hour_logs.values()
        if h["participant_id"] == p["id"]
        and h["work_date"] == body["work_date"]
        and h["status"] in ("PENDING", "APPROVED")
    )
    if existing + body["hours"] > DAILY_CAP_HOURS:
        raise ApiError("ERR_DAILY_HOURS_EXCEEDED", "Daily hours cap of 6 would be exceeded")

    if shift is not None and shift["status"] != "COMPLETED":
        raise ApiError("ERR_SHIFT_NOT_CREDITABLE", "shift_id must reference a COMPLETED shift")

    h = make_common()
    h.update({
        "participant_id": p["id"],
        "shift_id": body.get("shift_id"),
        "work_date": body["work_date"],
        "hours": body["hours"],
        "activity_type": body["activity_type"],
        "description": body.get("description"),
        "status": "PENDING",
        "created_by_user_id": user_id,
        "reviewed_by_user_id": None,
        "void_reason": None,
    })
    db.hour_logs[h["id"]] = h
    return success(hour_log_view(h), status=201)


def _parse_date(s):
    from datetime import date
    if not isinstance(s, str):
        raise ValueError
    parts = s.split("-")
    if len(parts) != 3:
        raise ValueError
    return date(int(parts[0]), int(parts[1]), int(parts[2]))


@bp.get("/hour-logs/<hour_log_id>")
def get_hour_log(hour_log_id):
    user_id, role = require_roles("ShopCoordinator", "ProgramDirector", "Participant")
    h = _get_hour_log(hour_log_id)
    _check_participant_ownership(role, user_id, h["participant_id"])
    return success(hour_log_view(h))


@bp.get("/hour-logs")
def list_hour_logs():
    require_roles("ShopCoordinator", "ProgramDirector")
    rows = list(db.hour_logs.values())
    for param in ("participant_id", "shift_id", "status", "work_date"):
        value = request.args.get(param)
        if value is not None:
            rows = [h for h in rows if h[param] == value]
    rows = sorted_by_created(rows)
    page, pg = paginate(rows)
    return success([hour_log_view(h) for h in page], pagination=pg)


def _recompute_participant_hours(p):
    """hours_accrual: recompute and apply the auto-transition / demotion cascade."""
    p["hours_earned"] = participant_hours_earned(p)
    if p["status"] == "ENROLLED" and p["hours_earned"] >= p["required_hours"]:
        p["status"] = "HOURS_MET"
    elif p["status"] == "HOURS_MET" and p["hours_earned"] < p["required_hours"]:
        # Demotion unwinds any held reservation.
        release_reserved_bike(p)
        p["status"] = "ENROLLED"


@bp.post("/hour-logs/<hour_log_id>/approve")
def approve_hour_log(hour_log_id):
    user_id, _ = require_roles("ShopCoordinator")
    body = get_body()
    validate_payload(body, {"expected_participant_version": {"type": "integer", "required": True}})
    h = _get_hour_log(hour_log_id)
    p = _get_participant(h["participant_id"])
    # OCC runs first among the state checks.
    if body["expected_participant_version"] != p["version"]:
        raise ApiError("ERR_STALE_VERSION", "Participant version has advanced; re-read and resubmit")
    if h["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", "Only a PENDING hour log can be approved")
    if p["status"] not in ("ENROLLED", "HOURS_MET"):
        raise ApiError("ERR_PARTICIPANT_NOT_ACTIVE", "Participant must be ENROLLED or HOURS_MET")
    if user_id == h["created_by_user_id"]:
        raise ApiError("ERR_REVIEWER_IS_LOGGER", "The reviewer must differ from the logger")
    h["status"] = "APPROVED"
    h["reviewed_by_user_id"] = user_id
    touch(h)
    _recompute_participant_hours(p)
    touch(p)
    return success(hour_log_view(h))


@bp.post("/hour-logs/<hour_log_id>/reject")
def reject_hour_log(hour_log_id):
    user_id, _ = require_roles("ShopCoordinator")
    get_body()
    h = _get_hour_log(hour_log_id)
    if h["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", "Only a PENDING hour log can be rejected")
    if user_id == h["created_by_user_id"]:
        raise ApiError("ERR_REVIEWER_IS_LOGGER", "The reviewer must differ from the logger")
    h["status"] = "REJECTED"
    h["reviewed_by_user_id"] = user_id
    touch(h)
    return success(hour_log_view(h))


@bp.post("/hour-logs/<hour_log_id>/void")
def void_hour_log(hour_log_id):
    user_id, _ = require_roles("ProgramDirector")
    body = get_body()
    validate_payload(body, {"reason": {"type": "string"}})
    h = _get_hour_log(hour_log_id)
    p = _get_participant(h["participant_id"])
    if h["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", "Only an APPROVED hour log can be voided")
    if p["status"] == "GRADUATED":
        raise ApiError("ERR_INVALID_STATE", "Graduated ledgers are sealed")
    if user_id == h["created_by_user_id"]:
        raise ApiError("ERR_REVIEWER_IS_LOGGER", "The voider must differ from the logger")
    h["status"] = "VOIDED"
    h["reviewed_by_user_id"] = user_id
    h["void_reason"] = body.get("reason")
    touch(h)
    _recompute_participant_hours(p)
    touch(p)
    return success(hour_log_view(h))


# ---------------------------------------------------------------------------
# Reservation, graduation, withdrawal
# ---------------------------------------------------------------------------

@bp.post("/participants/<participant_id>/reserve-bike")
def reserve_bike(participant_id):
    user_id, role = require_roles("ShopCoordinator", "Participant")
    body = get_body()
    validate_payload(body, {"bike_id": {"type": "string", "required": True}})
    p = _get_participant(participant_id)
    _check_participant_ownership(role, user_id, participant_id)
    bike = db.bikes.get(body["bike_id"])
    if bike is None:
        raise ApiError("ERR_NOT_FOUND", f"Bike {body['bike_id']} does not exist")
    if bike["status"] != "READY_FOR_DISPOSITION":
        raise ApiError("ERR_BIKE_NOT_AVAILABLE", "Bike is not READY_FOR_DISPOSITION")
    if p["reserved_bike_id"] is not None:
        raise ApiError("ERR_RESERVATION_EXISTS", "Participant already holds a reservation")
    if p["status"] != "HOURS_MET":
        raise ApiError("ERR_HOURS_NOT_MET", "Participant hours are not yet met")
    bike["status"] = "RESERVED_FOR_GRADUATE"
    touch(bike)
    p["reserved_bike_id"] = bike["id"]
    touch(p)
    return success(participant_view(p))


@bp.post("/participants/<participant_id>/release-bike")
def release_bike(participant_id):
    user_id, role = require_roles("ShopCoordinator", "Participant")
    p = _get_participant(participant_id)
    _check_participant_ownership(role, user_id, participant_id)
    if p["reserved_bike_id"] is None:
        raise ApiError("ERR_INVALID_STATE", "Participant holds no reserved bike")
    release_reserved_bike(p)
    touch(p)
    return success(participant_view(p))


@bp.post("/participants/<participant_id>/graduate")
def graduate(participant_id):
    require_roles("ProgramDirector")
    p = _get_participant(participant_id)
    if p["status"] != "HOURS_MET":
        raise ApiError("ERR_INVALID_STATE", "Only a HOURS_MET participant can graduate")
    if p["reserved_bike_id"] is None:
        raise ApiError("ERR_NO_BIKE_RESERVED", "Graduation requires a reserved bike")
    if not p["safety_quiz_passed"]:
        raise ApiError("ERR_QUIZ_NOT_PASSED", "Safety quiz must be passed before graduation")
    if not any(d["recipient_kind"] == "EARN_A_BIKE_GRADUATE" and d.get("participant_id") == p["id"]
               for d in db.helmet_distributions.values()):
        raise ApiError("ERR_HELMET_REQUIRED", "A helmet must be distributed before graduation")
    bike = db.bikes.get(p["reserved_bike_id"])
    p["status"] = "GRADUATED"
    p["graduated_at"] = db.now_iso()
    touch(p)
    if bike is not None:
        bike["status"] = "GIFTED"
        touch(bike)
    return success(participant_view(p))


@bp.post("/participants/<participant_id>/withdraw")
def withdraw(participant_id):
    user_id, role = require_roles("ShopCoordinator", "Participant")
    p = _get_participant(participant_id)
    _check_participant_ownership(role, user_id, participant_id)
    if p["status"] not in ("ENROLLED", "HOURS_MET"):
        raise ApiError("ERR_INVALID_STATE", "Only an ENROLLED or HOURS_MET participant can withdraw")
    release_reserved_bike(p)
    p["status"] = "WITHDRAWN"
    touch(p)
    return success(participant_view(p))
