"""Inspections, adverse events, protocol deviations, and procedure-room
bookings (PRD §3.8-3.9).
"""
from datetime import timedelta

from flask import Blueprint

from db import STORE, new_rec, now
from domain import (
    SEMIANNUAL_DAYS,
    SEVERE_GRADES,
    TURNOVER_MINUTES,
    file_deviation_from_escalation,
    personnel_cleared,
    ser_adverse_event,
    ser_deviation,
    ser_inspection,
    ser_room_booking,
    suspend_protocol_cascade,
)
from envelope import get_body, list_response, ok_obj
from errors import (
    ApiError,
    ERR_BOOKING_IN_PAST,
    ERR_INSPECTION_LAPSED,
    ERR_PROTOCOL_NOT_APPROVED,
    ERR_RESOLUTION_OVERDUE,
    ERR_ROOM_CONFLICT,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_SERIOUS_DEVIATION_NOT_CLOSABLE,
    ERR_TRAINING_INCOMPLETE,
    invalid_request,
    invalid_state,
)
from routes_admin import fetch
from validation import (
    authenticate,
    opt_int,
    require_role,
    req_dt,
    req_enum,
    req_str,
)

bp = Blueprint("compliance", __name__)

INSPECTION_KINDS = {"FACILITY", "PROGRAM_REVIEW"}
SEVERITIES = {"MINOR", "MODERATE", "SEVERE", "MORBUND"}
SERIOUSNESS = {"MINOR", "SERIOUS"}


# ---------------------------------------------------------------------------
# Facility inspections
# ---------------------------------------------------------------------------

@bp.post("/iacuc/inspections")
def create_inspection():
    uid, role = authenticate()
    require_role(role, "IacucAdministrator")
    body = get_body()
    inspection_kind = req_enum(body, "inspection_kind", INSPECTION_KINDS)
    scheduled_for = req_dt(body, "scheduled_for")
    deficiency_count = opt_int(body, "deficiency_count", default=0, minimum=0)
    completed_same_kind = [
        i.completed_at
        for i in STORE["inspections"].values()
        if i.inspection_kind == inspection_kind
        and i.state == "COMPLETED"
        and i.completed_at is not None
    ]
    if completed_same_kind:
        due_by = max(completed_same_kind) + timedelta(days=SEMIANNUAL_DAYS)
    else:
        due_by = scheduled_for
    r = new_rec(
        "inspections",
        inspection_kind=inspection_kind,
        scheduled_for=scheduled_for,
        due_by=due_by,
        completed_at=None,
        state="SCHEDULED",
        deficiency_count=deficiency_count,
    )
    return ok_obj(ser_inspection(r), 201)


@bp.get("/iacuc/inspections/<rid>")
def get_inspection(rid):
    uid, role = authenticate()
    require_role(role, "IacucAdministrator", "FacilityManager")
    return ok_obj(ser_inspection(fetch("inspections", rid)))


@bp.post("/iacuc/inspections/<rid>/complete")
def complete_inspection(rid):
    uid, role = authenticate()
    require_role(role, "IacucAdministrator")
    body = get_body()
    completed_at = req_dt(body, "completed_at")
    insp = fetch("inspections", rid)
    if insp.state != "SCHEDULED":
        raise invalid_state("Inspection is not SCHEDULED")
    if "deficiency_count" in body and body.get("deficiency_count") is not None:
        insp.deficiency_count = opt_int(body, "deficiency_count", minimum=0)
    insp.completed_at = completed_at
    if completed_at <= insp.due_by:
        insp.state = "COMPLETED"
        insp.touch()
        return ok_obj(ser_inspection(insp))
    # Completion even one second past due_by -> LAPSED (terminal) + error.
    insp.state = "LAPSED"
    insp.touch()
    raise ApiError(
        ERR_INSPECTION_LAPSED, 422,
        "Completion attempted after due_by; inspection is LAPSED",
    )


# ---------------------------------------------------------------------------
# Adverse event reports
# ---------------------------------------------------------------------------

@bp.post("/iacuc/adverse-events")
def create_adverse_event():
    uid, role = authenticate()
    require_role(role, "AnimalCareStaff", "AttendingVeterinarian")
    body = get_body()
    protocol_id = req_str(body, "protocol_id")
    animal_id = req_str(body, "animal_id")
    reported_by = req_str(body, "reported_by_personnel_id")
    severity = req_enum(body, "severity", SEVERITIES)
    description = req_str(body, "description")
    protocol = fetch("protocols", protocol_id)
    fetch("animals", animal_id)
    fetch("personnel", reported_by)
    # Priority 9 (personnel gates) precedes priority 11 (protocol-approved).
    if not personnel_cleared(reported_by):
        raise ApiError(
            ERR_TRAINING_INCOMPLETE, 422,
            "Reporter lacks completed training or occ-health clearance",
        )
    if protocol.status != "APPROVED":
        raise ApiError(
            ERR_PROTOCOL_NOT_APPROVED, 409,
            "Protocol must be APPROVED to file adverse events against it",
        )
    r = new_rec(
        "adverse_events",
        protocol_id=protocol_id,
        animal_id=animal_id,
        reported_by_personnel_id=reported_by,
        severity=severity,
        description=description,
        state="OPEN",
        reported_at=now(),
        resolved_at=None,
    )
    return ok_obj(ser_adverse_event(r), 201)


@bp.get("/iacuc/protocols/<rid>/adverse-events")
def list_protocol_adverse_events(rid):
    uid, role = authenticate()
    require_role(role, "AttendingVeterinarian", "IacucAdministrator")
    fetch("protocols", rid)
    rows = [e for e in STORE["adverse_events"].values() if e.protocol_id == rid]
    return list_response(rows, ser_adverse_event)


@bp.get("/iacuc/animals/<rid>/adverse-events")
def list_animal_adverse_events(rid):
    uid, role = authenticate()
    require_role(role, "AttendingVeterinarian", "IacucAdministrator")
    fetch("animals", rid)
    rows = [e for e in STORE["adverse_events"].values() if e.animal_id == rid]
    return list_response(rows, ser_adverse_event)


@bp.get("/iacuc/personnel/<rid>/adverse-events")
def list_personnel_adverse_events(rid):
    uid, role = authenticate()
    require_role(role, "AttendingVeterinarian", "IacucAdministrator")
    fetch("personnel", rid)
    rows = [
        e
        for e in STORE["adverse_events"].values()
        if e.reported_by_personnel_id == rid
    ]
    return list_response(rows, ser_adverse_event)


@bp.post("/iacuc/adverse-events/<rid>/begin-treatment")
def begin_treatment(rid):
    uid, role = authenticate()
    require_role(role, "AttendingVeterinarian")
    ev = fetch("adverse_events", rid)
    if ev.state != "OPEN":
        raise invalid_state("Adverse event is not OPEN")
    ev.state = "UNDER_TREATMENT"
    ev.touch()
    return ok_obj(ser_adverse_event(ev))


@bp.post("/iacuc/adverse-events/<rid>/escalate")
def escalate_event(rid):
    uid, role = authenticate()
    require_role(role, "AttendingVeterinarian")
    ev = fetch("adverse_events", rid)
    if ev.state not in ("OPEN", "UNDER_TREATMENT"):
        raise invalid_state("Adverse event cannot be escalated from its state")
    ev.state = "ESCALATED"
    ev.touch()
    if ev.severity in SEVERE_GRADES:
        file_deviation_from_escalation(ev)
    return ok_obj(ser_adverse_event(ev))


@bp.post("/iacuc/adverse-events/<rid>/resolve")
def resolve_event(rid):
    uid, role = authenticate()
    require_role(role, "AttendingVeterinarian")
    ev = fetch("adverse_events", rid)
    if ev.state not in ("UNDER_TREATMENT", "ESCALATED"):
        raise invalid_state("Adverse event cannot be resolved from its state")
    if ev.state == "UNDER_TREATMENT" and now() > ev.reported_at + timedelta(hours=72):
        raise ApiError(
            ERR_RESOLUTION_OVERDUE, 422,
            "Resolution deadline (reported_at + 72h) passed; escalate first",
        )
    ev.state = "RESOLVED"
    ev.resolved_at = now()
    ev.touch()
    return ok_obj(ser_adverse_event(ev))


# ---------------------------------------------------------------------------
# Protocol deviations
# ---------------------------------------------------------------------------

@bp.post("/iacuc/protocol-deviations")
def create_deviation():
    uid, role = authenticate()
    require_role(role, "AnimalCareStaff", "AttendingVeterinarian", "Investigator")
    body = get_body()
    protocol_id = req_str(body, "protocol_id")
    reported_by = req_str(body, "reported_by_personnel_id")
    description = req_str(body, "description")
    seriousness = req_enum(body, "seriousness", SERIOUSNESS)
    fetch("protocols", protocol_id)
    fetch("personnel", reported_by)
    r = new_rec(
        "deviations",
        protocol_id=protocol_id,
        reported_by_personnel_id=reported_by,
        description=description,
        seriousness=seriousness,
        state="REPORTED",
    )
    return ok_obj(ser_deviation(r), 201)


@bp.get("/iacuc/protocols/<rid>/deviations")
def list_protocol_deviations(rid):
    uid, role = authenticate()
    require_role(role, "IacucAdministrator", "AttendingVeterinarian")
    fetch("protocols", rid)
    rows = [d for d in STORE["deviations"].values() if d.protocol_id == rid]
    return list_response(rows, ser_deviation)


@bp.get("/iacuc/personnel/<rid>/protocol-deviations")
def list_personnel_deviations(rid):
    uid, role = authenticate()
    require_role(role, "IacucAdministrator")
    fetch("personnel", rid)
    rows = [
        d
        for d in STORE["deviations"].values()
        if d.reported_by_personnel_id == rid
    ]
    return list_response(rows, ser_deviation)


@bp.post("/iacuc/protocol-deviations/<rid>/begin-review")
def begin_review(rid):
    uid, role = authenticate()
    require_role(role, "IacucAdministrator")
    d = fetch("deviations", rid)
    if d.state != "REPORTED":
        raise invalid_state("Deviation is not REPORTED")
    d.state = "UNDER_REVIEW"
    d.touch()
    return ok_obj(ser_deviation(d))


@bp.post("/iacuc/protocol-deviations/<rid>/close")
def close_deviation(rid):
    uid, role = authenticate()
    require_role(role, "IacucAdministrator")
    d = fetch("deviations", rid)
    if d.state != "UNDER_REVIEW":
        raise invalid_state("Deviation is not UNDER_REVIEW")
    # Segregation of duties (priority 8) precedes the serious-close rule (12).
    if uid == d.reported_by_personnel_id:
        raise ApiError(
            ERR_SEGREGATION_OF_DUTIES, 403,
            "The reporter of a deviation may not close it",
        )
    if d.seriousness == "SERIOUS":
        raise ApiError(
            ERR_SERIOUS_DEVIATION_NOT_CLOSABLE, 422,
            "A SERIOUS deviation under review must be resolved via "
            "impose-suspension",
        )
    d.state = "CLOSED"
    d.touch()
    return ok_obj(ser_deviation(d))


@bp.post("/iacuc/protocol-deviations/<rid>/impose-suspension")
def impose_suspension(rid):
    uid, role = authenticate()
    require_role(role, "IacucAdministrator")
    d = fetch("deviations", rid)
    if d.state != "UNDER_REVIEW":
        raise invalid_state("Deviation is not UNDER_REVIEW")
    d.state = "SUSPENSION_IMPOSED"
    d.touch()
    protocol = STORE["protocols"].get(d.protocol_id)
    if protocol is not None and protocol.status == "APPROVED":
        suspend_protocol_cascade(protocol)
    return ok_obj(ser_deviation(d))


# ---------------------------------------------------------------------------
# Procedure-room bookings
# ---------------------------------------------------------------------------

@bp.post("/iacuc/room-bookings")
def create_room_booking():
    uid, role = authenticate()
    require_role(role, "AnimalCareStaff", "AttendingVeterinarian")
    body = get_body()
    room_code = req_str(body, "room_code")
    protocol_id = req_str(body, "protocol_id")
    booked_by = req_str(body, "booked_by_personnel_id")
    start_at = req_dt(body, "start_at")
    end_at = req_dt(body, "end_at")
    if end_at <= start_at:
        raise invalid_request("end_at must fall after start_at")
    protocol = fetch("protocols", protocol_id)
    fetch("personnel", booked_by)
    # Priority 9 (personnel gates) precedes 11/16/17.
    if not personnel_cleared(booked_by):
        raise ApiError(
            ERR_TRAINING_INCOMPLETE, 422,
            "Booking member lacks completed training or occ-health clearance",
        )
    if protocol.status != "APPROVED":
        raise ApiError(
            ERR_PROTOCOL_NOT_APPROVED, 409,
            "Protocol must be APPROVED to book rooms against it",
        )
    if start_at < now():
        raise ApiError(
            ERR_BOOKING_IN_PAST, 422,
            "Booking start_at precedes the current logical clock time",
        )
    buffer = timedelta(minutes=TURNOVER_MINUTES)
    for b in STORE["room_bookings"].values():
        if b.room_code != room_code or b.state != "CONFIRMED":
            continue
        if start_at < b.end_at + buffer and b.start_at < end_at + buffer:
            raise ApiError(
                ERR_ROOM_CONFLICT, 409,
                "Booking overlaps a CONFIRMED booking within the turnover buffer",
            )
    r = new_rec(
        "room_bookings",
        room_code=room_code,
        protocol_id=protocol_id,
        booked_by_personnel_id=booked_by,
        start_at=start_at,
        end_at=end_at,
        state="CONFIRMED",
    )
    return ok_obj(ser_room_booking(r), 201)


@bp.get("/iacuc/protocols/<rid>/room-bookings")
def list_protocol_room_bookings(rid):
    uid, role = authenticate()
    require_role(role, "AnimalCareStaff", "AttendingVeterinarian", "IacucAdministrator")
    fetch("protocols", rid)
    rows = [b for b in STORE["room_bookings"].values() if b.protocol_id == rid]
    return list_response(rows, ser_room_booking)


@bp.get("/iacuc/personnel/<rid>/room-bookings")
def list_personnel_room_bookings(rid):
    uid, role = authenticate()
    require_role(role, "AnimalCareStaff", "IacucAdministrator")
    fetch("personnel", rid)
    rows = [
        b
        for b in STORE["room_bookings"].values()
        if b.booked_by_personnel_id == rid
    ]
    return list_response(rows, ser_room_booking)


@bp.post("/iacuc/room-bookings/<rid>/cancel")
def cancel_room_booking(rid):
    uid, role = authenticate()
    require_role(role, "AnimalCareStaff", "AttendingVeterinarian")
    b = fetch("room_bookings", rid)
    if b.state != "CONFIRMED":
        raise invalid_state("Booking is not CONFIRMED")
    b.state = "CANCELLED"
    b.touch()
    return ok_obj(ser_room_booking(b))
