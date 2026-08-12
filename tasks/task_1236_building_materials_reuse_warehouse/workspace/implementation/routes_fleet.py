"""Routes: crew members, crew assignments, vehicles, pickup appointments,
diversion reports."""
import re

from flask import Blueprint, request

import db
from errors import ApiError, err_invalid_request, err_invalid_time_window
from response import success_obj, success_list
from services import (
    PICKUP_FEE_CENTS,
    compute_report_totals,
    crew_overlaps,
    recompute_donor_standing,
    recompute_job_fee,
    serialize_report,
    vehicle_conflicts,
)
from util import (
    authenticate,
    require_role,
    get_body,
    req_str,
    opt_str,
    req_enum,
    opt_enum,
    req_num,
    opt_num,
    opt_int,
    req_dt,
    lookup,
    paginate,
    serialize,
    parse_bool_param,
    round_cents,
    D,
)

bp = Blueprint("fleet", __name__)

CREW_TYPES = {"VOLUNTEER", "PAID"}
ASSIGNMENT_ROLES = {"LEAD", "WORKER"}
VEHICLE_STATES = {"AVAILABLE", "IN_MAINTENANCE", "RETIRED"}
VEHICLE_TRANSITIONS = {
    ("AVAILABLE", "IN_MAINTENANCE"),
    ("IN_MAINTENANCE", "AVAILABLE"),
    ("IN_MAINTENANCE", "RETIRED"),
}
SUBJECT_TYPES = {"DONATION_OFFER", "DECONSTRUCTION_JOB"}

CREW_READ_ROLES = [
    "CrewCoordinator",
    "WarehouseAdmin",
    "CrewLead",
    "HazmatTechnician",
    "IntakeStaff",
]
ASSIGNMENT_READ_ROLES = ["CrewCoordinator", "WarehouseAdmin", "CrewLead", "HazmatTechnician"]
APPT_ROLES = ["CrewCoordinator", "IntakeStaff"]
APPT_READ_ROLES = ["CrewCoordinator", "IntakeStaff", "WarehouseAdmin"]


# ---------------------------------------------------------------------------
# Crew members
# ---------------------------------------------------------------------------


@bp.post("/reuse/crew-members")
def create_crew_member():
    data = get_body()
    full_name = req_str(data, "full_name")
    crew_type = req_enum(data, "crew_type", CREW_TYPES)
    hourly_rate_cents = opt_int(data, "hourly_rate_cents", 0, min_value=0)
    hazmat_certified = data.get("hazmat_certified", False)
    lead_certified = data.get("lead_certified", False)
    if not isinstance(hazmat_certified, bool):
        raise err_invalid_request("hazmat_certified must be a boolean")
    if not isinstance(lead_certified, bool):
        raise err_invalid_request("lead_certified must be a boolean")
    ctx = authenticate()
    require_role(ctx, ["CrewCoordinator", "WarehouseAdmin"])
    if crew_type == "VOLUNTEER":
        hourly_rate_cents = 0  # forced to 0 for volunteers whatever the payload says
    member = {
        **db.base_fields(),
        "full_name": full_name,
        "crew_type": crew_type,
        "hourly_rate_cents": hourly_rate_cents,
        "hazmat_certified": hazmat_certified,
        "lead_certified": lead_certified,
        "status": "ACTIVE",
        "cumulative_job_hours": 0,
    }
    db.crew_members[member["id"]] = member
    return success_obj(serialize(member), 201)


@bp.get("/reuse/crew-members")
def list_crew_members():
    ctx = authenticate()
    require_role(ctx, CREW_READ_ROLES)
    records = list(db.crew_members.values())
    for param in ("status", "crew_type"):
        v = request.args.get(param)
        if v is not None:
            records = [m for m in records if m.get(param) == v]
    hazmat = parse_bool_param("hazmat_certified")
    if hazmat is not None:
        records = [m for m in records if m["hazmat_certified"] == hazmat]
    page, meta = paginate(records)
    return success_list([serialize(m) for m in page], meta)


@bp.get("/reuse/crew-members/<memberId>")
def get_crew_member(memberId):
    ctx = authenticate()
    require_role(ctx, CREW_READ_ROLES)
    return success_obj(serialize(lookup(db.crew_members, "crew_member", memberId)))


@bp.patch("/reuse/crew-members/<memberId>")
def patch_crew_member(memberId):
    data = get_body()
    status = opt_enum(data, "status", {"ACTIVE", "INACTIVE"})
    hourly_rate_cents = opt_int(data, "hourly_rate_cents", min_value=0)
    hazmat_certified = data.get("hazmat_certified")
    lead_certified = data.get("lead_certified")
    if hazmat_certified is not None and not isinstance(hazmat_certified, bool):
        raise err_invalid_request("hazmat_certified must be a boolean")
    if lead_certified is not None and not isinstance(lead_certified, bool):
        raise err_invalid_request("lead_certified must be a boolean")
    ctx = authenticate()
    require_role(ctx, ["CrewCoordinator", "WarehouseAdmin"])
    member = lookup(db.crew_members, "crew_member", memberId)
    if status is not None:
        member["status"] = status
    if hourly_rate_cents is not None:
        member["hourly_rate_cents"] = hourly_rate_cents
    if hazmat_certified is not None:
        member["hazmat_certified"] = hazmat_certified
    if lead_certified is not None:
        member["lead_certified"] = lead_certified
    if member["crew_type"] == "VOLUNTEER":
        member["hourly_rate_cents"] = 0
    db.touch(member)
    return success_obj(serialize(member))


# ---------------------------------------------------------------------------
# Crew assignments
# ---------------------------------------------------------------------------


@bp.post("/reuse/crew-assignments")
def create_assignment():
    data = get_body()
    job_id = req_str(data, "job_id")
    crew_member_id = req_str(data, "crew_member_id")
    role_on_job = req_enum(data, "role_on_job", ASSIGNMENT_ROLES)
    start_at = req_dt(data, "start_at")
    end_at = req_dt(data, "end_at")
    ctx = authenticate()
    require_role(ctx, ["CrewCoordinator"])
    job = lookup(db.jobs, "job", job_id)
    lookup(db.crew_members, "crew_member", crew_member_id)
    # Business constraints (priority 9): half-open crew overlap
    if crew_overlaps(crew_member_id, start_at, end_at):
        raise ApiError(
            "ERR_CREW_TIME_OVERLAP",
            409,
            "Assignment overlaps an existing ASSIGNED/COMPLETED assignment",
        )
    # Temporal arithmetic (priority 10)
    if not end_at > start_at:
        raise err_invalid_time_window("end_at must be after start_at")
    if (
        job["scheduled_start"] is None
        or start_at < job["scheduled_start"]
        or end_at > job["scheduled_end"]
    ):
        raise ApiError(
            "ERR_ASSIGNMENT_OUTSIDE_JOB_WINDOW",
            422,
            "Assignment window must lie inside the job's scheduled window",
        )
    assignment = {
        **db.base_fields(),
        "job_id": job_id,
        "crew_member_id": crew_member_id,
        "role_on_job": role_on_job,
        "start_at": start_at,
        "end_at": end_at,
        "status": "ASSIGNED",
        "hours_worked": 0,
        "labor_cost_cents": 0,
    }
    db.assignments[assignment["id"]] = assignment
    return success_obj(serialize(assignment), 201)


@bp.get("/reuse/crew-assignments")
def list_assignments():
    ctx = authenticate()
    require_role(ctx, ASSIGNMENT_READ_ROLES)
    records = list(db.assignments.values())
    for param in ("job_id", "crew_member_id", "status"):
        v = request.args.get(param)
        if v is not None:
            records = [a for a in records if a.get(param) == v]
    page, meta = paginate(records)
    return success_list([serialize(a) for a in page], meta)


@bp.get("/reuse/crew-assignments/<assignmentId>")
def get_assignment(assignmentId):
    ctx = authenticate()
    require_role(ctx, ASSIGNMENT_READ_ROLES)
    return success_obj(serialize(lookup(db.assignments, "assignment", assignmentId)))


@bp.post("/reuse/crew-assignments/<assignmentId>/complete")
def complete_assignment(assignmentId):
    data = get_body()
    hours_worked = req_num(data, "hours_worked", gt=0)
    ctx = authenticate()
    require_role(ctx, ["CrewCoordinator"])
    assignment = lookup(db.assignments, "assignment", assignmentId)
    if assignment["status"] != "ASSIGNED":
        raise ApiError(
            "ERR_ASSIGNMENT_NOT_ACTIVE", 409, "complete requires ASSIGNED"
        )
    member = db.crew_members[assignment["crew_member_id"]]
    if member["crew_type"] == "VOLUNTEER":
        labor_cost = 0
    else:
        labor_cost = round_cents(D(hours_worked) * D(member["hourly_rate_cents"]))
    assignment["status"] = "COMPLETED"
    assignment["hours_worked"] = hours_worked
    assignment["labor_cost_cents"] = labor_cost
    db.touch(assignment)
    # Ledger sync: crew cumulative hours
    member["cumulative_job_hours"] = float(
        D(member["cumulative_job_hours"]) + D(hours_worked)
    )
    db.touch(member)
    # Cascade hop 2: job actual fee recomputed
    job = db.jobs[assignment["job_id"]]
    recompute_job_fee(job)
    db.touch(job)
    return success_obj(serialize(assignment))


@bp.post("/reuse/crew-assignments/<assignmentId>/cancel")
def cancel_assignment(assignmentId):
    get_body()
    ctx = authenticate()
    require_role(ctx, ["CrewCoordinator"])
    assignment = lookup(db.assignments, "assignment", assignmentId)
    if assignment["status"] != "ASSIGNED":
        raise ApiError("ERR_ASSIGNMENT_NOT_ACTIVE", 409, "cancel requires ASSIGNED")
    assignment["status"] = "CANCELLED"
    db.touch(assignment)
    job = db.jobs[assignment["job_id"]]
    before = job["actual_fee_cents"]
    recompute_job_fee(job)
    if job["actual_fee_cents"] != before:
        db.touch(job)
    return success_obj(serialize(assignment))


@bp.post("/reuse/crew-assignments/<assignmentId>/mark-no-show")
def no_show_assignment(assignmentId):
    get_body()
    ctx = authenticate()
    require_role(ctx, ["CrewCoordinator"])
    assignment = lookup(db.assignments, "assignment", assignmentId)
    if assignment["status"] != "ASSIGNED":
        raise ApiError(
            "ERR_ASSIGNMENT_NOT_ACTIVE", 409, "mark-no-show requires ASSIGNED"
        )
    assignment["status"] = "NO_SHOW"
    db.touch(assignment)
    return success_obj(serialize(assignment))


# ---------------------------------------------------------------------------
# Vehicles
# ---------------------------------------------------------------------------


@bp.post("/reuse/vehicles")
def create_vehicle():
    data = get_body()
    plate_code = req_str(data, "plate_code")
    capacity_lbs = req_num(data, "capacity_lbs", gt=0)
    ctx = authenticate()
    require_role(ctx, ["CrewCoordinator", "WarehouseAdmin"])
    for v in db.vehicles.values():
        if v["plate_code"] == plate_code:
            raise ApiError("ERR_DUPLICATE_CODE", 409, "Vehicle plate already exists")
    vehicle = {
        **db.base_fields(),
        "plate_code": plate_code,
        "capacity_lbs": capacity_lbs,
        "status": "AVAILABLE",
    }
    db.vehicles[vehicle["id"]] = vehicle
    return success_obj(serialize(vehicle), 201)


@bp.get("/reuse/vehicles")
def list_vehicles():
    ctx = authenticate()
    require_role(ctx, ["CrewCoordinator", "WarehouseAdmin", "IntakeStaff"])
    records = list(db.vehicles.values())
    v = request.args.get("status")
    if v is not None:
        records = [x for x in records if x["status"] == v]
    page, meta = paginate(records)
    return success_list([serialize(x) for x in page], meta)


@bp.get("/reuse/vehicles/<vehicleId>")
def get_vehicle(vehicleId):
    ctx = authenticate()
    require_role(ctx, ["CrewCoordinator", "WarehouseAdmin", "IntakeStaff"])
    return success_obj(serialize(lookup(db.vehicles, "vehicle", vehicleId)))


@bp.patch("/reuse/vehicles/<vehicleId>")
def patch_vehicle(vehicleId):
    data = get_body()
    new_status = opt_enum(data, "status", VEHICLE_STATES)
    ctx = authenticate()
    require_role(ctx, ["CrewCoordinator", "WarehouseAdmin"])
    vehicle = lookup(db.vehicles, "vehicle", vehicleId)
    if new_status is not None and new_status != vehicle["status"]:
        if (vehicle["status"], new_status) not in VEHICLE_TRANSITIONS:
            raise err_invalid_request(
                "Invalid vehicle status transition %s -> %s"
                % (vehicle["status"], new_status)
            )
        if new_status == "IN_MAINTENANCE":
            booked = any(
                a["vehicle_id"] == vehicle["id"] and a["status"] == "BOOKED"
                for a in db.appointments.values()
            )
            if booked:
                raise ApiError(
                    "ERR_ACTIVE_APPOINTMENT_EXISTS",
                    409,
                    "A BOOKED pickup appointment references this vehicle",
                )
        vehicle["status"] = new_status
    db.touch(vehicle)
    return success_obj(serialize(vehicle))


# ---------------------------------------------------------------------------
# Pickup appointments
# ---------------------------------------------------------------------------


@bp.post("/reuse/pickup-appointments")
def create_appointment():
    data = get_body()
    subject_type = req_enum(data, "subject_type", SUBJECT_TYPES)
    subject_id = req_str(data, "subject_id")
    vehicle_id = req_str(data, "vehicle_id")
    window_start = req_dt(data, "window_start")
    window_end = req_dt(data, "window_end")
    ctx = authenticate()
    require_role(ctx, APPT_ROLES)
    # Body FK existence (priority 5)
    if subject_type == "DONATION_OFFER":
        subject = lookup(db.offers, "offer", subject_id)
    else:
        subject = lookup(db.jobs, "job", subject_id)
    vehicle = lookup(db.vehicles, "vehicle", vehicle_id)
    # State (priority 7): subject bookable state + vehicle availability
    if subject_type == "DONATION_OFFER":
        if subject["status"] != "ACCEPTED":
            raise ApiError(
                "ERR_INVALID_OFFER_STATE",
                409,
                "DONATION_OFFER subjects must be ACCEPTED",
            )
    else:
        if subject["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            raise ApiError(
                "ERR_INVALID_JOB_STATE",
                409,
                "DECONSTRUCTION_JOB subjects must be SCHEDULED or IN_PROGRESS",
            )
    if vehicle["status"] != "AVAILABLE":
        raise ApiError("ERR_VEHICLE_NOT_AVAILABLE", 409, "Vehicle is not AVAILABLE")
    # Business constraints (priority 9): buffered vehicle overlap
    if vehicle_conflicts(vehicle_id, window_start, window_end):
        raise ApiError(
            "ERR_VEHICLE_TIME_OVERLAP",
            409,
            "Vehicle has a conflicting occupation within the 60-minute buffer",
        )
    # Temporal arithmetic (priority 10)
    if not window_end > window_start:
        raise err_invalid_time_window("window_end must be after window_start")
    # Fee computed once, at booking time
    if subject_type == "DECONSTRUCTION_JOB":
        fee_cents = 0
    else:
        donor = db.donors[subject["donor_id"]]
        recompute_donor_standing(donor)
        fee_cents = (
            0
            if donor["recognition_tier"] in ("BUILDER", "CORNERSTONE")
            else PICKUP_FEE_CENTS
        )
    appointment = {
        **db.base_fields(),
        "subject_type": subject_type,
        "subject_id": subject_id,
        "vehicle_id": vehicle_id,
        "window_start": window_start,
        "window_end": window_end,
        "status": "BOOKED",
        "fee_cents": fee_cents,
        "completion_notes": "",
    }
    db.appointments[appointment["id"]] = appointment
    return success_obj(serialize(appointment), 201)


@bp.get("/reuse/pickup-appointments")
def list_appointments():
    ctx = authenticate()
    require_role(ctx, APPT_READ_ROLES)
    records = list(db.appointments.values())
    for param in ("vehicle_id", "subject_id", "status"):
        v = request.args.get(param)
        if v is not None:
            records = [a for a in records if a.get(param) == v]
    page, meta = paginate(records)
    return success_list([serialize(a) for a in page], meta)


@bp.get("/reuse/pickup-appointments/<appointmentId>")
def get_appointment(appointmentId):
    ctx = authenticate()
    require_role(ctx, APPT_READ_ROLES)
    return success_obj(serialize(lookup(db.appointments, "appointment", appointmentId)))


def _appointment_transition(appointmentId, target, record_notes=False):
    data = get_body()
    notes = opt_str(data, "completion_notes")
    ctx = authenticate()
    require_role(ctx, APPT_ROLES)
    appt = lookup(db.appointments, "appointment", appointmentId)
    if appt["status"] != "BOOKED":
        raise ApiError(
            "ERR_APPOINTMENT_NOT_BOOKED", 409, "transition requires BOOKED"
        )
    appt["status"] = target
    if record_notes and notes is not None:
        appt["completion_notes"] = notes
    db.touch(appt)
    return success_obj(serialize(appt))


@bp.post("/reuse/pickup-appointments/<appointmentId>/complete")
def complete_appointment(appointmentId):
    return _appointment_transition(appointmentId, "COMPLETED", record_notes=True)


@bp.post("/reuse/pickup-appointments/<appointmentId>/cancel")
def cancel_appointment(appointmentId):
    return _appointment_transition(appointmentId, "CANCELLED")


@bp.post("/reuse/pickup-appointments/<appointmentId>/mark-no-show")
def no_show_appointment(appointmentId):
    return _appointment_transition(appointmentId, "NO_SHOW", record_notes=True)


# ---------------------------------------------------------------------------
# Diversion reports
# ---------------------------------------------------------------------------

PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


@bp.post("/reuse/diversion-reports")
def create_report():
    data = get_body()
    period = req_str(data, "period")
    if not PERIOD_RE.match(period):
        raise err_invalid_request("period must be in YYYY-MM format")
    ctx = authenticate()
    require_role(ctx, ["WarehouseAdmin"])
    for r in db.reports.values():
        if r["period"] == period:
            raise ApiError(
                "ERR_DUPLICATE_REPORT_PERIOD",
                409,
                "A DiversionReport already exists for this period",
            )
    report = {
        **db.base_fields(),
        "period": period,
        "status": "OPEN",
        "total_diverted_lbs": 0,
        "sold_lbs": 0,
        "donated_lbs": 0,
        "recycled_lbs": 0,
        "landfill_lbs": 0,
        "closed_by_user_id": "",
        "closed_at": None,
        "_frozen": None,
    }
    db.reports[report["id"]] = report
    return success_obj(serialize_report(report), 201)


@bp.get("/reuse/diversion-reports")
def list_reports():
    ctx = authenticate()
    require_role(ctx, ["WarehouseAdmin", "StoreManager"])
    records = list(db.reports.values())
    v = request.args.get("status")
    if v is not None:
        records = [r for r in records if r["status"] == v]
    page, meta = paginate(records)
    return success_list([serialize_report(r) for r in page], meta)


@bp.get("/reuse/diversion-reports/<reportId>")
def get_report(reportId):
    ctx = authenticate()
    require_role(ctx, ["WarehouseAdmin", "StoreManager"])
    return success_obj(serialize_report(lookup(db.reports, "report", reportId)))


@bp.post("/reuse/diversion-reports/<reportId>/close")
def close_report(reportId):
    get_body()
    ctx = authenticate()
    require_role(ctx, ["WarehouseAdmin"])
    report = lookup(db.reports, "report", reportId)
    if report["status"] != "OPEN":
        raise ApiError("ERR_REPORT_NOT_OPEN", 409, "close requires OPEN")
    # Unweighed material anywhere has no report_period and cannot be attributed
    if any(b["status"] == "MANIFESTED" for b in db.batches.values()):
        raise ApiError(
            "ERR_UNWEIGHED_BATCHES_IN_PERIOD",
            409,
            "Salvage batches still stand MANIFESTED",
        )
    if any(
        b["report_period"] == report["period"] and b["status"] == "QUARANTINED"
        for b in db.batches.values()
    ):
        raise ApiError(
            "ERR_QUARANTINED_BATCHES_OPEN",
            422,
            "Period has batches in QUARANTINED status",
        )
    # Freeze the figures at close; a CLOSED report never recomputes
    frozen = compute_report_totals(report["period"])
    report.update(frozen)
    report["_frozen"] = True
    report["status"] = "CLOSED"
    report["closed_at"] = db.now()
    report["closed_by_user_id"] = ctx.user_id
    db.touch(report)
    return success_obj(serialize_report(report))
