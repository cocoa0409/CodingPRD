"""Attendance day endpoints + the census-gated check-in. PRD §3.5."""
from flask import Blueprint, request

import db
from errors import err
from middleware import require_roles
from response import success, list_response
from services import common as c

bp = Blueprint("attendance", __name__)


def day_view(d):
    return dict(d)


def _cancel_planned_legs(day_id):
    """Cascade: every PLANNED TransportLeg under this day → CANCELLED."""
    for leg in db.transport_legs.values():
        if leg["attendance_day_id"] == day_id and leg["status"] == "PLANNED":
            leg["status"] = "CANCELLED"
            c.touch(leg)


@bp.post("/pace/attendance-days")
@require_roles("IntakeCoordinator", "NurseStaff")
def create_day():
    body = c.get_body()
    participant_id = c.as_str(body, "participant_id")
    service_date = c.parse_datetime(body, "service_date")
    meals = c.as_int(body, "meals_provided", required=False, default=1, min_val=0, max_val=3)
    activities = c.as_int(body, "activities_count", required=False, default=0)
    transport_required = c.as_bool(body, "transport_required", required=False, default=True)
    c.find_or_404(db.participants, participant_id)

    svc_iso = c.iso_out(service_date)
    svc_date = service_date.date()
    # service_date unique per participant (priority 21)
    for d in db.attendance_days.values():
        if d["participant_id"] == participant_id:
            if c.parse_iso(d["service_date"]).date() == svc_date:
                raise err("ERR_DUPLICATE_PERIOD", "Duplicate service_date for participant")

    d = c.base_fields()
    d.update({
        "participant_id": participant_id,
        "service_date": svc_iso,
        "meals_provided": meals,
        "activities_count": activities,
        "transport_required": transport_required,
        "transport_leg_count": 0,
        "status": "SCHEDULED",
    })
    db.attendance_days[d["id"]] = d
    return success(day_view(d), status=201)


@bp.get("/pace/attendance-days/<day_id>")
@require_roles("ProgramAdmin", "IntakeCoordinator", "MedicalDirector",
               "NurseStaff", "BillingSpecialist")
def get_day(day_id):
    d = c.find_or_404(db.attendance_days, day_id)
    return success(day_view(d))


@bp.get("/pace/attendance-days")
@require_roles("ProgramAdmin", "IntakeCoordinator", "MedicalDirector",
               "NurseStaff", "BillingSpecialist")
def list_days():
    limit, offset = c.get_pagination()
    items = list(db.attendance_days.values())
    for key in ("participant_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [d for d in items if d.get(key) == val]
    page, total = c.paginate(items, limit, offset)
    return list_response([day_view(d) for d in page], limit, offset, total)


@bp.post("/pace/attendance-days/<day_id>/check-in")
@require_roles("NurseStaff")
def check_in(day_id):
    d = c.find_or_404(db.attendance_days, day_id)
    # State (priority 5)
    if d["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Attendance day not SCHEDULED")
    participant = db.participants.get(d["participant_id"])
    # Participant ENROLLED (priority 7)
    if not participant or participant["status"] != "ENROLLED":
        raise err("ERR_PARTICIPANT_NOT_ENROLLED", "Participant not enrolled")
    # Live census on the same service_date for this program (priority 22)
    program_id = participant["program_id"]
    svc_date = c.parse_iso(d["service_date"]).date()
    occupancy = 0
    for other in db.attendance_days.values():
        if other["status"] != "CHECKED_IN":
            continue
        op = db.participants.get(other["participant_id"])
        if not op or op["program_id"] != program_id:
            continue
        if c.parse_iso(other["service_date"]).date() == svc_date:
            occupancy += 1
    program = db.programs.get(program_id)
    if occupancy >= program["daily_census_capacity"]:
        raise err("ERR_CENSUS_FULL", "Live census full")

    d["status"] = "CHECKED_IN"
    c.touch(d)
    return success(day_view(d))


@bp.post("/pace/attendance-days/<day_id>/complete")
@require_roles("NurseStaff")
def complete(day_id):
    d = c.find_or_404(db.attendance_days, day_id)
    if d["status"] != "CHECKED_IN":
        raise err("ERR_INVALID_STATE", "Attendance day not CHECKED_IN")
    d["status"] = "COMPLETED"
    c.touch(d)
    participant = db.participants.get(d["participant_id"])
    if participant:
        participant["lifetime_attendance_days"] = participant["lifetime_attendance_days"] + 1
        c.touch(participant)
    return success(day_view(d))


@bp.post("/pace/attendance-days/<day_id>/no-show")
@require_roles("NurseStaff")
def no_show(day_id):
    d = c.find_or_404(db.attendance_days, day_id)
    if d["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Attendance day not SCHEDULED")
    d["status"] = "NO_SHOW"
    c.touch(d)
    _cancel_planned_legs(d["id"])
    return success(day_view(d))


@bp.post("/pace/attendance-days/<day_id>/cancel")
@require_roles("NurseStaff", "IntakeCoordinator")
def cancel(day_id):
    d = c.find_or_404(db.attendance_days, day_id)
    if d["status"] not in ("SCHEDULED", "CHECKED_IN"):
        raise err("ERR_INVALID_STATE", "Attendance day not SCHEDULED/CHECKED_IN")
    d["status"] = "CANCELLED"
    c.touch(d)
    _cancel_planned_legs(d["id"])
    return success(day_view(d))
