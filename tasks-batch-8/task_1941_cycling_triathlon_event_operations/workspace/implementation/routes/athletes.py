"""Athlete endpoints with suspension cascade."""
from flask import Blueprint, request

import db
from errors import ApiError, ERR_VALIDATION, not_found
from middleware import require_roles
from response import success_object, success_list, paginate
from services.core import withdraw_registration
from util import stamp_common, touch, require_fields, require_enum

bp = Blueprint("athletes", __name__)

ALL = ("RaceDirector", "PermitCoordinator", "Referee", "Timer", "VolunteerCoordinator", "Athlete")


def get_event_or_404(event_id):
    ev = db.events.get(event_id)
    if not ev:
        raise not_found("event not found")
    return ev


def get_athlete_or_404(athlete_id):
    a = db.athletes.get(athlete_id)
    if not a:
        raise not_found("athlete not found")
    return a


@bp.post("/events/<event_id>/athletes")
def create_athlete(event_id):
    require_roles("RaceDirector")
    get_event_or_404(event_id)
    body = request.get_json(silent=True) or {}
    require_fields(body, ["full_name", "birth_date", "license_number"])
    for f in ("full_name", "birth_date", "license_number"):
        if not isinstance(body[f], str) or not body[f]:
            raise ApiError(ERR_VALIDATION, f"{f} must be a non-empty string", 400)
    # basic YYYY-MM-DD shape check
    bd = body["birth_date"]
    parts = bd.split("-")
    if len(parts) != 3 or len(parts[0]) != 4:
        raise ApiError(ERR_VALIDATION, "birth_date must be ISO YYYY-MM-DD", 400)
    a = stamp_common({
        "event_id": event_id,
        "full_name": body["full_name"],
        "birth_date": body["birth_date"],
        "license_number": body["license_number"],
        "license_status": "ACTIVE",
    })
    db.athletes[a["id"]] = a
    return success_object(a, status=201)


@bp.get("/events/<event_id>/athletes")
def list_athletes(event_id):
    require_roles(*ALL)
    get_event_or_404(event_id)
    items = [a for a in db.athletes.values() if a["event_id"] == event_id]
    page, limit, offset, total = paginate(items, request.args)
    return success_list(page, limit, offset, total)


@bp.get("/athletes/<athlete_id>")
def get_athlete(athlete_id):
    require_roles(*ALL)
    return success_object(get_athlete_or_404(athlete_id))


@bp.patch("/athletes/<athlete_id>")
def update_athlete(athlete_id):
    require_roles("RaceDirector")
    a = get_athlete_or_404(athlete_id)
    body = request.get_json(silent=True) or {}
    require_fields(body, ["license_status"])
    new_status = require_enum(body["license_status"], ("ACTIVE", "SUSPENDED"), "license_status")

    if new_status == "SUSPENDED" and a["license_status"] != "SUSPENDED":
        # cascade: withdraw all non-terminal pre-racing registrations
        for reg in list(db.registrations.values()):
            if reg["athlete_id"] == a["id"] and reg["status"] in (
                    "ENTERED", "PAID", "CONFIRMED", "WAITLISTED", "RACKED"):
                withdraw_registration(reg, full_refund=False)
    a["license_status"] = new_status
    touch(a)
    return success_object(a)


@bp.get("/athletes/<athlete_id>/registrations")
def athlete_registrations(athlete_id):
    require_roles(*ALL)
    a = get_athlete_or_404(athlete_id)
    items = [r for r in db.registrations.values() if r["athlete_id"] == a["id"]]
    page, limit, offset, total = paginate(items, request.args)
    return success_list(page, limit, offset, total)
