"""FieldCrew and CrewBooking endpoints."""

from flask import Blueprint, request

import db
from errors import (
    ERR_CREW_CAPACITY_EXCEEDED,
    ERR_CREW_WINDOW_CONFLICT,
    ERR_DATE_IN_PAST,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    raise_error,
)
from middleware import (
    ANY_ROLE,
    check_app_mutable,
    get_body,
    new_id,
    paginate,
    parse_iso_date,
    require_enum,
    require_fields,
    require_int,
    require_roles,
    require_str,
    validate_window,
)
from response import success_list, success_object
from services.domain import get_application, get_booking, get_crew, touch

bp = Blueprint("crews", __name__)

SPECIALTIES = ("MAIN_EXTENSION", "SERVICE_LINE", "RESTORATION", "GENERAL")
SCOPES = ("MAIN_CONSTRUCTION", "SERVICE_INSTALL", "RESTORATION")
TURNAROUND_BUFFER_MIN = 30


# --- Field crews -------------------------------------------------------------

@bp.route("/field-crews", methods=["POST"])
def create_crew():
    require_roles("SystemAdmin")
    body = get_body()
    require_fields(body, "crew_name", "specialty", "daily_capacity_minutes")
    specialty = require_enum(body, "specialty", SPECIALTIES)
    capacity = require_int(body, "daily_capacity_minutes", minimum=1)
    now = db.now_iso()
    crew = {
        "id": new_id(),
        "crew_name": require_str(body, "crew_name"),
        "specialty": specialty,
        "daily_capacity_minutes": capacity,
        "active": True,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.field_crews[crew["id"]] = crew
    return success_object(crew, 201)


@bp.route("/field-crews/<cid>", methods=["GET"])
def get_one_crew(cid):
    require_roles(*ANY_ROLE)
    return success_object(get_crew(cid))


@bp.route("/field-crews", methods=["GET"])
def list_crews():
    require_roles(*ANY_ROLE)
    page, limit, offset, total = paginate(list(db.field_crews.values()))
    return success_list(page, limit, offset, total)


# --- Crew bookings ------------------------------------------------------------

@bp.route("/crew-bookings", methods=["POST"])
def create_booking():
    require_roles("FieldSupervisor")
    body = get_body()
    require_fields(
        body,
        "service_application_id",
        "field_crew_id",
        "work_date",
        "start_minute",
        "end_minute",
        "scope",
    )
    app = get_application(body["service_application_id"])
    crew = get_crew(body["field_crew_id"])
    work_date = body["work_date"]
    parse_iso_date(work_date, "work_date")
    start_minute = body["start_minute"]
    end_minute = body["end_minute"]
    validate_window(start_minute, end_minute)
    scope = require_enum(body, "scope", SCOPES)
    check_app_mutable(app)
    now = db.now_iso()
    booking = {
        "id": new_id(),
        "service_application_id": app["id"],
        "field_crew_id": crew["id"],
        "work_date": work_date,
        "start_minute": start_minute,
        "end_minute": end_minute,
        "scope": scope,
        "status": "REQUESTED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.crew_bookings[booking["id"]] = booking
    return success_object(booking, 201)


@bp.route("/crew-bookings/<bid>", methods=["GET"])
def get_one_booking(bid):
    require_roles(*ANY_ROLE)
    return success_object(get_booking(bid))


@bp.route("/crew-bookings", methods=["GET"])
def list_bookings():
    require_roles(*ANY_ROLE)
    records = list(db.crew_bookings.values())
    crew_id = request.args.get("field_crew_id")
    app_id = request.args.get("service_application_id")
    work_date = request.args.get("work_date")
    status = request.args.get("status")
    if crew_id is not None:
        records = [b for b in records if b["field_crew_id"] == crew_id]
    if app_id is not None:
        records = [b for b in records if b["service_application_id"] == app_id]
    if work_date is not None:
        records = [b for b in records if b["work_date"] == work_date]
    if status is not None:
        records = [b for b in records if b["status"] == status]
    page, limit, offset, total = paginate(records)
    return success_list(page, limit, offset, total)


def _confirmed_bookings_for_crew_day(crew_id, work_date, exclude_id=None):
    return [
        b for b in db.crew_bookings.values()
        if b["field_crew_id"] == crew_id
        and b["work_date"] == work_date
        and b["status"] == "CONFIRMED"
        and b["id"] != exclude_id
    ]


def _check_confirm_rules(crew, booking):
    """Buffered-overlap (closed interval + 30 min) and daily-capacity rules."""
    for other in _confirmed_bookings_for_crew_day(crew["id"], booking["work_date"], exclude_id=booking["id"]):
        # conflict iff new.start < existing.end + 30 AND new.end + 30 > existing.start
        if booking["start_minute"] < other["end_minute"] + TURNAROUND_BUFFER_MIN and \
           booking["end_minute"] + TURNAROUND_BUFFER_MIN > other["start_minute"]:
            raise_error(ERR_CREW_WINDOW_CONFLICT, "Booking window conflicts with an existing confirmed booking")
    used = sum(
        b["end_minute"] - b["start_minute"]
        for b in _confirmed_bookings_for_crew_day(crew["id"], booking["work_date"], exclude_id=booking["id"])
    )
    duration = booking["end_minute"] - booking["start_minute"]
    if used + duration > crew["daily_capacity_minutes"]:
        raise_error(ERR_CREW_CAPACITY_EXCEEDED, "Crew daily capacity exceeded")


@bp.route("/crew-bookings/<bid>/confirm", methods=["POST"])
def confirm_booking(bid):
    require_roles("FieldSupervisor")
    booking = get_booking(bid)
    app = get_application(booking["service_application_id"])
    check_app_mutable(app)
    if booking["status"] != "REQUESTED":
        raise_error(ERR_INVALID_STATE, "Only REQUESTED bookings can be confirmed")
    crew = get_crew(booking["field_crew_id"])
    work_date = parse_iso_date(booking["work_date"], "work_date")
    if work_date < db.today_date():
        raise_error(ERR_DATE_IN_PAST, "work_date must not be in the past")
    if not crew["active"]:
        raise_error(ERR_INVALID_STATE, "Inactive crews reject new bookings")
    _check_confirm_rules(crew, booking)
    booking["status"] = "CONFIRMED"
    touch(booking)
    return success_object(booking)


@bp.route("/crew-bookings/<bid>/complete", methods=["POST"])
def complete_booking(bid):
    require_roles("FieldSupervisor")
    booking = get_booking(bid)
    app = get_application(booking["service_application_id"])
    check_app_mutable(app)
    if booking["status"] != "CONFIRMED":
        raise_error(ERR_INVALID_STATE, "Only CONFIRMED bookings can be completed")
    booking["status"] = "COMPLETED"
    touch(booking)
    # Application CONSTRUCTION_SCHEDULED → SERVICE_INSTALLED
    if app["status"] == "CONSTRUCTION_SCHEDULED":
        app["status"] = "SERVICE_INSTALLED"
        touch(app)
    # MainExtension ACCEPTED → CONSTRUCTED
    from services.domain import main_extension_for_application
    me = main_extension_for_application(app["id"])
    if me is not None and me["status"] == "ACCEPTED":
        me["status"] = "CONSTRUCTED"
        touch(me)
    return success_object(booking)


@bp.route("/crew-bookings/<bid>/cancel", methods=["POST"])
def cancel_booking(bid):
    require_roles("FieldSupervisor")
    booking = get_booking(bid)
    app = get_application(booking["service_application_id"])
    check_app_mutable(app)
    if booking["status"] not in ("REQUESTED", "CONFIRMED"):
        raise_error(ERR_INVALID_STATE, "Only REQUESTED or CONFIRMED bookings can be cancelled")
    booking["status"] = "CANCELLED"
    touch(booking)
    return success_object(booking)


@bp.route("/crew-bookings/<bid>/reschedule", methods=["POST"])
def reschedule_booking(bid):
    require_roles("FieldSupervisor")
    booking = get_booking(bid)
    app = get_application(booking["service_application_id"])
    body = get_body()
    require_fields(body, "work_date", "start_minute", "end_minute")
    work_date = body["work_date"]
    parse_iso_date(work_date, "work_date")
    validate_window(body["start_minute"], body["end_minute"])
    check_app_mutable(app)
    if booking["status"] != "CONFIRMED":
        raise_error(ERR_INVALID_STATE, "Only CONFIRMED bookings can be rescheduled")
    booking["work_date"] = work_date
    booking["start_minute"] = body["start_minute"]
    booking["end_minute"] = body["end_minute"]
    booking["status"] = "REQUESTED"
    touch(booking)
    return success_object(booking)
