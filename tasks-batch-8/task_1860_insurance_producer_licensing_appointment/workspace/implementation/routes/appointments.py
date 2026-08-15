"""Appointment endpoints (PRD 3.4): standard filings, terminations, rescission."""

from flask import Blueprint

from core import calc, constants as K
from core.clock import add_days
from core.envelope import filter_exact, object_response, paginate
from core.errors import fail
from core.pipeline import (
    authorize, producer_scope, req_dt, req_enum, req_loa_list, req_str,
    require_exactly_one_subject, resolve, resolve_subject_refs, subject_ids,
    subject_of,
)
from core.serialize import appointment as serialize_appointment
from core.store import db, new_row, bump

bp = Blueprint("appointments", __name__)

_READ_ROLES = ("LicensingCoordinator", "ComplianceOfficer", "CarrierAdmin", "Producer")
_LIST_ROLES = ("LicensingCoordinator", "ComplianceOfficer", "CarrierAdmin")


def check_appointment_uniqueness(subject_field, subject_id, state_code, effective_date):
    """The two creation guards of PRD 3.4: at most one non-terminal
    appointment per (subject, state), then the half-open interval overlap."""
    for appt in calc.appointments_of_subject(subject_field, subject_id, state_code):
        if appt["status"] in K.APPOINTMENT_NON_TERMINAL:
            fail(
                "ERR_APPOINTMENT_ALREADY_ACTIVE",
                "A non-terminal appointment already exists for this subject and state.",
            )
    for appt in calc.appointments_of_subject(subject_field, subject_id, state_code):
        termination_date = appt["termination_date"]
        if termination_date is None:
            continue
        # Interval [effective_date, termination_date), half-open: an effective
        # instant exactly equal to a prior termination_date is adjacent, allowed.
        if appt["effective_date"] <= effective_date < termination_date:
            fail(
                "ERR_APPOINTMENT_INTERVAL_OVERLAP",
                "effective_date falls inside another appointment interval in this state.",
            )


@bp.route("/api/appointments", methods=["POST"])
def create_appointment():
    ctx = authorize("LicensingCoordinator")
    producer_id, agency_id = subject_ids(ctx)
    state_code = req_str(ctx.body, "state_code")
    loas = req_loa_list(ctx.body, "lines_of_authority")
    effective_date = req_dt(ctx.body, "effective_date")
    resolve_subject_refs(ctx, producer_id, agency_id)
    require_exactly_one_subject(producer_id, agency_id)
    subject_field = "producer_id" if producer_id is not None else "agency_id"
    subject_id = producer_id if producer_id is not None else agency_id
    check_appointment_uniqueness(subject_field, subject_id, state_code, effective_date)
    row = new_row("appointments", {
        "producer_id": producer_id,
        "agency_id": agency_id,
        "state_code": state_code,
        "lines_of_authority": loas,
        "origin": "STANDARD",
        "status": "REQUESTED",
        "effective_date": effective_date,
        "termination_date": None,
        "termination_reason": None,
        "termination_initiated_at": None,
        "jit_filing_deadline": None,
    })
    return object_response(serialize_appointment(row), 201)


@bp.route("/api/appointments/<appointmentId>", methods=["GET"])
def get_appointment(appointmentId):
    ctx = authorize(*_READ_ROLES)
    row = resolve("appointments", appointmentId)
    producer_scope(ctx, row["producer_id"])
    return object_response(serialize_appointment(row), 200)


@bp.route("/api/appointments", methods=["GET"])
def list_appointments():
    authorize(*_LIST_ROLES)
    rows = db.ordered("appointments")
    rows = filter_exact(rows, "producer_id")
    rows = filter_exact(rows, "agency_id")
    rows = filter_exact(rows, "state_code")
    rows = filter_exact(rows, "status")
    return paginate(rows, serialize_appointment)


@bp.route("/api/appointments/<appointmentId>/file", methods=["POST"])
def file_appointment(appointmentId):
    authorize("LicensingCoordinator")
    appt = resolve("appointments", appointmentId)
    # Domain-specific state error first (PRD 2.9): filing a LAPSED JIT.
    if appt["status"] == "LAPSED":
        fail("ERR_JIT_FILING_WINDOW_CLOSED", "The JIT filing window has closed.")
    if appt["status"] not in ("REQUESTED", "JIT_PENDING"):
        fail(
            "ERR_INVALID_STATE",
            "Appointment in status {} cannot be filed.".format(appt["status"]),
        )
    subject_field, subject_id = subject_of(appt)
    lic = calc.active_license_covering(
        subject_field, subject_id, appt["state_code"], appt["lines_of_authority"]
    )
    if lic is None:
        fail(
            "ERR_LICENSE_NOT_ACTIVE",
            "Subject holds no ACTIVE license in this state covering every requested line.",
        )
    if appt["status"] == "JIT_PENDING":
        # Timeliness: filing exactly at the deadline instant is timely.  The
        # sweep normally lapses the appointment first; this guards the seam.
        if db.now > appt["jit_filing_deadline"]:
            fail("ERR_JIT_FILING_WINDOW_CLOSED", "The JIT filing window has closed.")
    appt["status"] = "ACTIVE"
    bump(appt)
    return object_response(serialize_appointment(appt), 200)


@bp.route("/api/appointments/<appointmentId>/terminate", methods=["POST"])
def terminate_appointment(appointmentId):
    ctx = authorize("LicensingCoordinator")
    appt = resolve("appointments", appointmentId)
    reason = req_enum(ctx.body, "termination_reason", ("VOLUNTARY", "FOR_CAUSE"))
    if appt["status"] != "ACTIVE":
        fail(
            "ERR_INVALID_STATE",
            "Appointment in status {} cannot be terminated.".format(appt["status"]),
        )
    appt["status"] = "TERMINATION_PENDING"
    appt["termination_reason"] = reason
    appt["termination_initiated_at"] = db.now
    bump(appt)
    return object_response(serialize_appointment(appt), 200)


@bp.route("/api/appointments/<appointmentId>/file-termination", methods=["POST"])
def file_termination(appointmentId):
    authorize("LicensingCoordinator")
    appt = resolve("appointments", appointmentId)
    if appt["status"] != "TERMINATION_PENDING":
        fail(
            "ERR_INVALID_STATE",
            "Appointment in status {} has no pending termination.".format(appt["status"]),
        )
    if appt["termination_reason"] == "FOR_CAUSE":
        deadline = add_days(appt["termination_initiated_at"], K.TERMINATION_FILING_DAYS)
        if db.now > deadline:
            fail(
                "ERR_TERMINATION_FILING_OVERDUE",
                "A FOR_CAUSE termination must be filed within 30 days of terminate.",
            )
    appt["status"] = "TERMINATED"
    appt["termination_date"] = db.now
    bump(appt)
    return object_response(serialize_appointment(appt), 200)


@bp.route("/api/appointments/<appointmentId>/rescind-termination", methods=["POST"])
def rescind_termination(appointmentId):
    authorize("LicensingCoordinator")
    appt = resolve("appointments", appointmentId)
    if appt["status"] != "TERMINATION_PENDING":
        fail(
            "ERR_INVALID_STATE",
            "Appointment in status {} has no pending termination.".format(appt["status"]),
        )
    subject_field, subject_id = subject_of(appt)
    lic = calc.active_license_in_state(subject_field, subject_id, appt["state_code"])
    if lic is None:
        fail("ERR_LICENSE_NOT_ACTIVE", "Subject's license in this state is not ACTIVE.")
    appt["status"] = "ACTIVE"
    appt["termination_reason"] = None
    appt["termination_initiated_at"] = None
    bump(appt)
    return object_response(serialize_appointment(appt), 200)
