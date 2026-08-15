"""Registration endpoints: create, pay, confirm, withdraw, mark-dnf, bike check-in/out."""
from datetime import timedelta

from flask import Blueprint, request

import db
from errors import (ApiError, ERR_VALIDATION, ERR_INVALID_STATE, ERR_EVENT_POSTURE,
                    ERR_CONFIRM_WINDOW_CLOSED, ERR_CHECKIN_WINDOW_CLOSED,
                    ERR_ATHLETE_SUSPENDED, ERR_APPEAL_PENDING,
                    ERR_REFUND_DESTINATION_REQUIRED, ERR_BIB_MISMATCH,
                    ERR_DUPLICATE_BIKE_CHECKIN, ERR_FORBIDDEN, not_found)
from middleware import require_roles
from response import success_object, success_list, paginate
from services.core import (select_wave, refresh_wave, promote_waitlist, age_at_event,
                           withdraw_registration, refund_tier, days_until)
from util import stamp_common, touch, require_fields, require_int, require_enum, clock_dt, parse_dt

bp = Blueprint("registrations", __name__)

ALL = ("RaceDirector", "PermitCoordinator", "Referee", "Timer", "VolunteerCoordinator", "Athlete")


def get_event_or_404(event_id):
    ev = db.events.get(event_id)
    if not ev:
        raise not_found("event not found")
    return ev


def get_reg_or_404(reg_id):
    r = db.registrations.get(reg_id)
    if not r:
        raise not_found("registration not found")
    return r


def check_athlete_ownership(user_id, role, registration):
    """Athlete-role callers may only act on own registrations (priority 3)."""
    if role == "Athlete" and registration["athlete_id"] != user_id:
        raise ApiError(ERR_FORBIDDEN, "Athlete may only act on own registrations", 403)


@bp.post("/events/<event_id>/registrations")
def create_registration(event_id):
    user_id, role = require_roles("RaceDirector", "Athlete")
    ev = get_event_or_404(event_id)
    body = request.get_json(silent=True) or {}
    require_fields(body, ["athlete_id", "division", "entry_fee_cents"])
    athlete_id = body["athlete_id"]
    if not isinstance(athlete_id, str):
        raise ApiError(ERR_VALIDATION, "athlete_id must be a string", 400)
    # Athlete self-registration check (priority 3 ownership)
    if role == "Athlete" and athlete_id != user_id:
        raise ApiError(ERR_FORBIDDEN, "Athlete may only register self", 403)
    athlete = db.athletes.get(athlete_id)
    if not athlete or athlete["event_id"] != event_id:
        raise not_found("athlete not found in this event")
    division = require_enum(body["division"], ("AGE_GROUP", "ELITE"), "division")
    fee = require_int(body["entry_fee_cents"], "entry_fee_cents")
    if fee < 0:
        raise ApiError(ERR_VALIDATION, "entry_fee_cents must be >= 0", 400)
    if athlete["license_status"] != "ACTIVE":
        raise ApiError(ERR_ATHLETE_SUSPENDED, "athlete license not ACTIVE", 409)

    reg = stamp_common({
        "event_id": event_id,
        "athlete_id": athlete_id,
        "wave_id": None,
        "division": division,
        "entry_fee_cents": fee,
        "age_at_event": None,
        "status": "ENTERED",
        "refund_destination": None,
        "refund_estimate_cents": None,
        "refund_final_cents": None,
        "withdrawn_at": None,
    })
    db.registrations[reg["id"]] = reg
    return success_object(reg, status=201)


@bp.get("/events/<event_id>/registrations")
def list_registrations(event_id):
    require_roles(*ALL)
    get_event_or_404(event_id)
    items = [r for r in db.registrations.values() if r["event_id"] == event_id]
    athlete_id = request.args.get("athlete_id")
    wave_id = request.args.get("wave_id")
    status = request.args.get("status")
    if athlete_id:
        items = [r for r in items if r["athlete_id"] == athlete_id]
    if wave_id:
        items = [r for r in items if r.get("wave_id") == wave_id]
    if status:
        items = [r for r in items if r["status"] == status]
    page, limit, offset, total = paginate(items, request.args)
    return success_list(page, limit, offset, total)


@bp.get("/registrations/<reg_id>")
def get_registration(reg_id):
    require_roles(*ALL)
    return success_object(get_reg_or_404(reg_id))


@bp.post("/registrations/<reg_id>/pay")
def pay_registration(reg_id):
    user_id, role = require_roles("RaceDirector", "Athlete")
    reg = get_reg_or_404(reg_id)
    check_athlete_ownership(user_id, role, reg)
    if reg["status"] != "ENTERED":
        raise ApiError(ERR_INVALID_STATE, f"cannot pay from {reg['status']}", 409)
    athlete = db.athletes[reg["athlete_id"]]
    if athlete["license_status"] != "ACTIVE":
        raise ApiError(ERR_ATHLETE_SUSPENDED, "athlete license not ACTIVE", 409)
    reg["status"] = "PAID"
    touch(reg)
    return success_object(reg)


@bp.post("/registrations/<reg_id>/confirm")
def confirm_registration(reg_id):
    require_roles("RaceDirector")
    reg = get_reg_or_404(reg_id)
    if reg["status"] != "PAID":
        raise ApiError(ERR_INVALID_STATE, f"cannot confirm from {reg['status']}", 409)
    ev = db.events[reg["event_id"]]
    if ev["posture"] != "PUBLISHED":
        raise ApiError(ERR_EVENT_POSTURE, "event posture must be PUBLISHED", 409)
    deadline = parse_dt(ev["start_date"]) - timedelta(hours=24)
    if clock_dt() >= deadline:
        raise ApiError(ERR_CONFIRM_WINDOW_CLOSED, "confirm window closed", 409)
    athlete = db.athletes[reg["athlete_id"]]
    if athlete["license_status"] != "ACTIVE":
        raise ApiError(ERR_ATHLETE_SUSPENDED, "athlete license not ACTIVE", 409)

    wave = select_wave(ev, reg, athlete)
    if wave is None:
        reg["status"] = "WAITLISTED"
        touch(reg)
        return success_object(reg)

    reg["status"] = "CONFIRMED"
    reg["wave_id"] = wave["id"]
    reg["age_at_event"] = age_at_event(ev, athlete)
    touch(reg)
    refresh_wave(wave)
    touch(wave)
    return success_object(reg)


@bp.post("/registrations/<reg_id>/withdraw")
def withdraw(reg_id):
    user_id, role = require_roles("RaceDirector", "Athlete")
    reg = get_reg_or_404(reg_id)
    check_athlete_ownership(user_id, role, reg)
    body = request.get_json(silent=True) or {}
    refund_destination = body.get("refund_destination")
    if refund_destination is not None and not isinstance(refund_destination, str):
        raise ApiError(ERR_VALIDATION, "refund_destination must be a string", 400)

    # open appeal guard (priority 6, integrity-of-competition) — evaluated
    # before state-machine from-state validity per PRD §2.10
    reg_penalty_ids = {p["id"] for p in db.penalties.values() if p["registration_id"] == reg["id"]}
    if any(a["penalty_id"] in reg_penalty_ids and a["status"] in ("FILED", "UNDER_REVIEW")
           for a in db.appeals.values()):
        raise ApiError(ERR_APPEAL_PENDING, "open appeal blocks withdrawal", 409)

    if reg["status"] not in ("ENTERED", "PAID", "CONFIRMED", "WAITLISTED", "RACKED"):
        raise ApiError(ERR_INVALID_STATE, f"cannot withdraw from {reg['status']}", 409)

    ev = db.events[reg["event_id"]]
    estimate = refund_tier(reg["entry_fee_cents"], days_until(ev, clock_dt()))
    if estimate > 0 and not refund_destination:
        raise ApiError(ERR_REFUND_DESTINATION_REQUIRED,
                       "refund_destination required when refund_estimate_cents > 0", 400)

    withdraw_registration(reg, full_refund=False, refund_destination=refund_destination)
    return success_object(reg)


@bp.post("/registrations/<reg_id>/mark-dnf")
def mark_dnf(reg_id):
    require_roles("RaceDirector", "Referee")
    reg = get_reg_or_404(reg_id)
    if reg["status"] != "RACING":
        raise ApiError(ERR_INVALID_STATE, f"cannot mark DNF from {reg['status']}", 409)
    reg["status"] = "DNF"
    touch(reg)
    return success_object(reg)


@bp.post("/registrations/<reg_id>/check-in-bike")
def check_in_bike(reg_id):
    user_id, role = require_roles("RaceDirector", "Athlete")
    reg = get_reg_or_404(reg_id)
    check_athlete_ownership(user_id, role, reg)
    body = request.get_json(silent=True) or {}
    require_fields(body, ["bib_code"])
    if not isinstance(body["bib_code"], str) or not body["bib_code"]:
        raise ApiError(ERR_VALIDATION, "bib_code must be a non-empty string", 400)

    if reg["status"] != "CONFIRMED":
        raise ApiError(ERR_INVALID_STATE, f"cannot check in bike from {reg['status']}", 409)
    ev = db.events[reg["event_id"]]
    if ev["posture"] != "PUBLISHED":
        raise ApiError(ERR_EVENT_POSTURE, "event posture must be PUBLISHED", 409)
    if clock_dt() >= parse_dt(ev["start_date"]):
        raise ApiError(ERR_CHECKIN_WINDOW_CLOSED, "check-in window closed", 409)
    if any(bc["registration_id"] == reg["id"] and bc["status"] == "CHECKED_IN"
           for bc in db.bike_checks.values()):
        raise ApiError(ERR_DUPLICATE_BIKE_CHECKIN, "a CHECKED_IN bike check already exists", 409)

    bc = stamp_common({
        "registration_id": reg["id"],
        "bib_code": body["bib_code"],
        "status": "CHECKED_IN",
        "checked_in_at": db.get_clock(),
        "checked_out_at": None,
    })
    db.bike_checks[bc["id"]] = bc
    reg["status"] = "RACKED"
    touch(reg)

    result = stamp_common({
        "registration_id": reg["id"],
        "status": "PROVISIONAL",
        "swim_seconds": None,
        "t1_seconds": None,
        "bike_seconds": None,
        "t2_seconds": None,
        "run_seconds": None,
        "penalty_seconds_total": 0,
        "provisional_total_seconds": None,
        "official_total_seconds": None,
        "effective_total_seconds": None,
        "division_rank": None,
        "finish_timestamp": None,
    })
    db.results[result["id"]] = result
    return success_object(bc, status=201)


@bp.post("/registrations/<reg_id>/check-out-bike")
def check_out_bike(reg_id):
    user_id, role = require_roles("RaceDirector", "Athlete")
    reg = get_reg_or_404(reg_id)
    check_athlete_ownership(user_id, role, reg)
    body = request.get_json(silent=True) or {}
    require_fields(body, ["bib_code"])
    if not isinstance(body["bib_code"], str):
        raise ApiError(ERR_VALIDATION, "bib_code must be a string", 400)

    open_check = next((bc for bc in db.bike_checks.values()
                       if bc["registration_id"] == reg["id"] and bc["status"] == "CHECKED_IN"), None)
    if open_check is None:
        raise ApiError(ERR_INVALID_STATE, "no open CHECKED_IN bike check", 409)
    if reg["status"] not in ("FINISHED", "DNF"):
        raise ApiError(ERR_INVALID_STATE, f"registration must be FINISHED or DNF, is {reg['status']}", 409)
    if body["bib_code"] != open_check["bib_code"]:
        raise ApiError(ERR_BIB_MISMATCH, "bib_code does not match open check-in", 409)

    open_check["status"] = "CHECKED_OUT"
    open_check["checked_out_at"] = db.get_clock()
    touch(open_check)
    return success_object(open_check)


@bp.get("/registrations/<reg_id>/bike-checks")
def list_bike_checks(reg_id):
    require_roles(*ALL)
    reg = get_reg_or_404(reg_id)
    items = [bc for bc in db.bike_checks.values() if bc["registration_id"] == reg["id"]]
    page, limit, offset, total = paginate(items, request.args)
    return success_list(page, limit, offset, total)
