"""Routes: hospital units, staff members, holiday observances, interview rooms."""

import re

from flask import Blueprint, request

import db
import errors
import middleware
from helpers import (
    CAPABILITIES,
    UNIT_CATEGORIES,
    UNIT_POSTURES,
    _MISSING,
    check_enum,
    check_int,
    check_string,
    check_bool,
    get_body,
    paginate,
    parse_bool_query,
    parse_pagination,
    require_present,
    serialize_holiday,
    serialize_room,
    serialize_staff,
    serialize_unit,
    sorted_by_creation,
    stamp_light,
    stamp_new,
    touch,
)
from response import success_list, success_object

bp = Blueprint("org", __name__)

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ---------------------------------------------------------------------------
# HospitalUnit
# ---------------------------------------------------------------------------


@bp.route("/api/hospital-units", methods=["POST"])
def create_unit():
    middleware.authenticate()
    middleware.require_roles("SystemAdmin")
    body = get_body()
    require_present(body, "name", "category")
    name = check_string(body, "name", required=True)
    max_roundings = check_int(body, "max_concurrent_roundings", minimum=1, default=2)
    category = check_enum(body, "category", UNIT_CATEGORIES, required=True)
    unit = stamp_new()
    unit.update(
        {
            "name": name,
            "category": category,
            "posture": "STANDARD",
            "max_concurrent_roundings": max_roundings,
        }
    )
    db.hospital_units[unit["id"]] = unit
    return success_object(serialize_unit(unit), 201)


@bp.route("/api/hospital-units", methods=["GET"])
def list_units():
    middleware.authenticate()
    middleware.require_roles(*middleware.ALL_ROLES)
    limit, offset = parse_pagination()
    posture = request.args.get("posture")
    category = request.args.get("category")
    units = list(db.hospital_units.values())
    if posture is not None:
        units = [u for u in units if u["posture"] == posture]
    if category is not None:
        units = [u for u in units if u["category"] == category]
    units = sorted_by_creation(units)
    page, total = paginate(units, limit, offset)
    return success_list([serialize_unit(u) for u in page], limit, offset, total)


@bp.route("/api/hospital-units/<unit_id>", methods=["GET"])
def get_unit(unit_id):
    middleware.authenticate()
    middleware.require_roles(*middleware.ALL_ROLES)
    unit = db.hospital_units.get(unit_id)
    if unit is None:
        raise errors.not_found(errors.ERR_UNIT_NOT_FOUND, "HospitalUnit not found")
    return success_object(serialize_unit(unit))


@bp.route("/api/hospital-units/<unit_id>", methods=["PATCH"])
def patch_unit(unit_id):
    middleware.authenticate()
    middleware.require_roles("PatientRelationsDirector", "SystemAdmin")
    unit = db.hospital_units.get(unit_id)
    if unit is None:
        raise errors.not_found(errors.ERR_UNIT_NOT_FOUND, "HospitalUnit not found")
    body = get_body()
    new_posture = body.get("posture")
    if (
        isinstance(new_posture, str)
        and unit["posture"] == "RESTRICTED"
        and new_posture == "STANDARD"
        and unit_late_events_unresolved(unit["id"])
    ):
        # Restoration blocked while any LATE_FILED event on the unit's cases
        # remains unacknowledged.
        raise errors.api_error(
            errors.ERR_UNIT_HAS_UNRESOLVED_LATE_EVENTS,
            409,
            "Unit has unacknowledged LATE_FILED reportable events",
        )
    posture = check_enum(body, "posture", UNIT_POSTURES)
    max_roundings = check_int(body, "max_concurrent_roundings", minimum=1)
    if posture is not None:
        unit["posture"] = posture
    if max_roundings is not None:
        unit["max_concurrent_roundings"] = max_roundings
    touch(unit)
    return success_object(serialize_unit(unit))


def unit_late_events_unresolved(unit_id):
    """Any LATE_FILED (unacknowledged) ReportableEvent on this unit's cases."""
    import derived

    return derived.unit_late_filed_event_count(unit_id) > 0


# ---------------------------------------------------------------------------
# StaffMember
# ---------------------------------------------------------------------------


@bp.route("/api/staff-members", methods=["POST"])
def create_staff():
    middleware.authenticate()
    middleware.require_roles("SystemAdmin")
    body = get_body()
    require_present(body, "full_name", "capabilities")
    full_name = check_string(body, "full_name", required=True)
    max_assignments = check_int(body, "max_concurrent_assignments", minimum=1, default=5)
    issuance_limit = check_int(body, "recovery_issuance_limit_cents", minimum=0, default=10000)
    capabilities = body.get("capabilities")
    if not isinstance(capabilities, list) or not capabilities:
        raise errors.invalid_request("capabilities must be a non-empty array")
    for entry in capabilities:
        if entry not in CAPABILITIES:
            raise errors.invalid_enum(f"capabilities entry invalid: {entry}")
    staff = stamp_new()
    staff.update(
        {
            "full_name": full_name,
            "capabilities": capabilities,
            "on_leave": False,
            "max_concurrent_assignments": max_assignments,
            "recovery_issuance_limit_cents": issuance_limit,
        }
    )
    db.staff_members[staff["id"]] = staff
    return success_object(serialize_staff(staff), 201)


@bp.route("/api/staff-members", methods=["GET"])
def list_staff():
    middleware.authenticate()
    middleware.require_roles(*middleware.ALL_ROLES)
    limit, offset = parse_pagination()
    on_leave = parse_bool_query("on_leave")
    staff = list(db.staff_members.values())
    if on_leave is not _MISSING:
        staff = [s for s in staff if s["on_leave"] is on_leave]
    staff = sorted_by_creation(staff)
    page, total = paginate(staff, limit, offset)
    return success_list([serialize_staff(s) for s in page], limit, offset, total)


@bp.route("/api/staff-members/<staff_id>", methods=["GET"])
def get_staff(staff_id):
    middleware.authenticate()
    middleware.require_roles(*middleware.ALL_ROLES)
    staff = db.staff_members.get(staff_id)
    if staff is None:
        raise errors.not_found(errors.ERR_STAFF_NOT_FOUND, "StaffMember not found")
    return success_object(serialize_staff(staff))


@bp.route("/api/staff-members/<staff_id>", methods=["PATCH"])
def patch_staff(staff_id):
    middleware.authenticate()
    middleware.require_roles("SystemAdmin", "PatientRelationsDirector")
    staff = db.staff_members.get(staff_id)
    if staff is None:
        raise errors.not_found(errors.ERR_STAFF_NOT_FOUND, "StaffMember not found")
    body = get_body()
    on_leave = check_bool(body, "on_leave")
    max_assignments = check_int(body, "max_concurrent_assignments", minimum=1)
    issuance_limit = check_int(body, "recovery_issuance_limit_cents", minimum=0)
    if on_leave is not None:
        staff["on_leave"] = on_leave
    if max_assignments is not None:
        staff["max_concurrent_assignments"] = max_assignments
    if issuance_limit is not None:
        staff["recovery_issuance_limit_cents"] = issuance_limit
    touch(staff)
    return success_object(serialize_staff(staff))


# ---------------------------------------------------------------------------
# HolidayObservance
# ---------------------------------------------------------------------------


@bp.route("/api/holiday-observances", methods=["POST"])
def create_holiday():
    middleware.authenticate()
    middleware.require_roles("SystemAdmin")
    body = get_body()
    require_present(body, "observance_date", "name")
    observance_date = body.get("observance_date")
    name = check_string(body, "name", required=True)
    if isinstance(observance_date, str):
        for h in db.holiday_observances.values():
            if h["observance_date"] == observance_date:
                raise errors.api_error(
                    errors.ERR_DUPLICATE_HOLIDAY,
                    409,
                    "HolidayObservance with same observance_date exists",
                )
    if (
        not isinstance(observance_date, str)
        or not _DATE_RE.match(observance_date)
        or not _valid_date(observance_date)
    ):
        raise errors.invalid_request("observance_date must be a valid YYYY-MM-DD date")
    holiday = stamp_light()
    holiday.update({"observance_date": observance_date, "name": name})
    db.holiday_observances[holiday["id"]] = holiday
    return success_object(serialize_holiday(holiday), 201)


def _valid_date(text):
    from datetime import date

    try:
        date.fromisoformat(text)
        return True
    except ValueError:
        return False


@bp.route("/api/holiday-observances", methods=["GET"])
def list_holidays():
    middleware.authenticate()
    middleware.require_roles(*middleware.ALL_ROLES)
    limit, offset = parse_pagination()
    holidays = sorted_by_creation(list(db.holiday_observances.values()))
    page, total = paginate(holidays, limit, offset)
    return success_list([serialize_holiday(h) for h in page], limit, offset, total)


@bp.route("/api/holiday-observances/<holiday_id>", methods=["DELETE"])
def delete_holiday(holiday_id):
    middleware.authenticate()
    middleware.require_roles("SystemAdmin")
    holiday = db.holiday_observances.get(holiday_id)
    if holiday is None:
        raise errors.not_found(errors.ERR_HOLIDAY_NOT_FOUND, "HolidayObservance not found")
    del db.holiday_observances[holiday_id]
    return "", 204


# ---------------------------------------------------------------------------
# InterviewRoom
# ---------------------------------------------------------------------------


@bp.route("/api/interview-rooms", methods=["POST"])
def create_room():
    middleware.authenticate()
    middleware.require_roles("SystemAdmin")
    body = get_body()
    require_present(body, "name", "location")
    name = check_string(body, "name", required=True)
    location = check_string(body, "location", required=True)
    room = stamp_new()
    room.update({"name": name, "location": location, "active": True})
    db.interview_rooms[room["id"]] = room
    return success_object(serialize_room(room), 201)


@bp.route("/api/interview-rooms", methods=["GET"])
def list_rooms():
    middleware.authenticate()
    middleware.require_roles(*middleware.ALL_ROLES)
    limit, offset = parse_pagination()
    rooms = sorted_by_creation(list(db.interview_rooms.values()))
    page, total = paginate(rooms, limit, offset)
    return success_list([serialize_room(r) for r in page], limit, offset, total)


@bp.route("/api/interview-rooms/<room_id>", methods=["GET"])
def get_room(room_id):
    middleware.authenticate()
    middleware.require_roles(*middleware.ALL_ROLES)
    room = db.interview_rooms.get(room_id)
    if room is None:
        raise errors.not_found(errors.ERR_ROOM_NOT_FOUND, "InterviewRoom not found")
    return success_object(serialize_room(room))
