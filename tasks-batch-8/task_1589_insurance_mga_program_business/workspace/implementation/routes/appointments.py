"""TPA appointments: create/activate with the 30-day gap rule, suspend /
reinstate / revoke with the claim referral cascade (PRD section 3.6)."""
from datetime import timedelta

from flask import Blueprint, request

import serialize
from db import STORE, new_entity, touch, now_dt
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_TPA_SUSPENDED,
    ERR_APPOINTMENT_WINDOW_CLOSED, ERR_APPOINTMENT_WINDOW_GAP,
    ERR_PROGRAM_NOT_ACTIVE, ERR_INVALID_REQUEST,
)
from middleware import require_roles, require_carrier_owner, ALL_ROLES
from response import success_object
from routes.common import get_or_404, render_list, filter_query
from routes.programs import require_program_not_terminal
from services import cascades
from validation import get_body, req_enum, req_int_nonneg, req_datetime, fk_or_404
from validation import req_str

bp = Blueprint("appointments", __name__)

CLAIM_TYPES = {"PROPERTY_DAMAGE", "BODILY_INJURY", "LIABILITY", "OTHER"}
APPOINTMENT_MIN_GAP_DAYS = 30


def _window_gap_ok(new_from, new_to, other_from, other_to):
    """Closed-window gap semantics: the new window must begin at least 30 days
    after the other's end, or the other must begin at least 30 days after the
    new window's end. Any smaller separation — including abutting windows — is
    a conflict."""
    gap = timedelta(days=APPOINTMENT_MIN_GAP_DAYS)
    return (new_from - other_to) >= gap or (other_from - new_to) >= gap


@bp.post("/mga/programs/<programId>/tpa-appointments")
def create_appointment(programId):
    require_roles("CarrierUnderwriter")
    program = get_or_404(STORE.programs, programId, "Program")
    require_carrier_owner(program)
    body = get_body()
    fk_or_404(STORE.tpas, body, "tpa_id", "TPA", ERR_NOT_FOUND)
    tpa_id = req_str(body, "tpa_id")
    claim_type = req_enum(body, "claim_type", CLAIM_TYPES)
    authority_limit_cents = req_int_nonneg(body, "authority_limit_cents")
    effective_from = req_datetime(body, "effective_from")
    effective_to = req_datetime(body, "effective_to")
    if effective_from > effective_to:
        raise_err(ERR_INVALID_REQUEST, "effective_from may not fall after effective_to (closed window).")
    require_program_not_terminal(program)
    tpa = STORE.tpas[tpa_id]
    if tpa["status"] != "ACTIVE":
        raise_err(ERR_TPA_SUSPENDED, "A SUSPENDED TPA cannot receive new appointments.")
    a = new_entity()
    a.update({
        "program_id": program["id"],
        "tpa_id": tpa_id,
        "claim_type": claim_type,
        "authority_limit_cents": authority_limit_cents,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "status": "PENDING",
    })
    STORE.tpa_appointments[a["id"]] = a
    return success_object(serialize.appointment(a), status=201)


@bp.get("/mga/programs/<programId>/tpa-appointments")
def list_program_appointments(programId):
    require_roles(*ALL_ROLES)
    get_or_404(STORE.programs, programId, "Program")
    items = filter_query(
        [a for a in STORE.tpa_appointments.values() if a["program_id"] == programId],
        tpa_id=request.args.get("tpa_id"),
        status=request.args.get("status"),
    )
    return render_list(items, serialize.appointment)


@bp.get("/mga/tpa-appointments/<appointmentId>")
def get_appointment(appointmentId):
    require_roles(*ALL_ROLES)
    a = get_or_404(STORE.tpa_appointments, appointmentId, "TPAAppointment")
    return success_object(serialize.appointment(a))


@bp.get("/mga/tpa-appointments")
def list_appointments():
    require_roles(*ALL_ROLES)
    items = filter_query(
        list(STORE.tpa_appointments.values()),
        tpa_id=request.args.get("tpa_id"),
        program_id=request.args.get("program_id"),
        status=request.args.get("status"),
    )
    return render_list(items, serialize.appointment)


def _carrier_scoped_appointment(appointmentId):
    require_roles("CarrierUnderwriter")
    a = get_or_404(STORE.tpa_appointments, appointmentId, "TPAAppointment")
    program = STORE.programs[a["program_id"]]
    require_carrier_owner(program)
    return a, program


@bp.post("/mga/tpa-appointments/<appointmentId>/activate")
def activate_appointment(appointmentId):
    a, program = _carrier_scoped_appointment(appointmentId)
    if a["status"] != "PENDING":
        raise_err(ERR_INVALID_STATE, "Only a PENDING appointment can be activated.")
    clock = now_dt()
    if clock > a["effective_to"]:
        raise_err(ERR_APPOINTMENT_WINDOW_CLOSED, "The appointment window has closed.")
    for o in STORE.tpa_appointments.values():
        if (
            o["id"] != a["id"]
            and o["program_id"] == a["program_id"]
            and o["claim_type"] == a["claim_type"]
            and o["tpa_id"] == a["tpa_id"]
            and o["status"] in ("ACTIVE", "SUSPENDED")
            and not _window_gap_ok(a["effective_from"], a["effective_to"], o["effective_from"], o["effective_to"])
        ):
            raise_err(
                ERR_APPOINTMENT_WINDOW_GAP,
                "Appointment window is within 30 days of another ACTIVE/SUSPENDED appointment for the same program, claim type and TPA.",
            )
    tpa = STORE.tpas[a["tpa_id"]]
    if tpa["status"] != "ACTIVE":
        raise_err(ERR_TPA_SUSPENDED, "A SUSPENDED TPA's appointments cannot be activated.")
    a["status"] = "ACTIVE"
    touch(a)
    return success_object(serialize.appointment(a))


@bp.post("/mga/tpa-appointments/<appointmentId>/suspend")
def suspend_appointment(appointmentId):
    a, program = _carrier_scoped_appointment(appointmentId)
    if a["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "Only an ACTIVE appointment can be suspended.")
    cascades.suspend_appointment(a)
    return success_object(serialize.appointment(a))


@bp.post("/mga/tpa-appointments/<appointmentId>/reinstate")
def reinstate_appointment(appointmentId):
    a, program = _carrier_scoped_appointment(appointmentId)
    if a["status"] != "SUSPENDED":
        raise_err(ERR_INVALID_STATE, "Only a SUSPENDED appointment can be reinstated.")
    require_program_not_terminal(program)
    if program["status"] != "ACTIVE":
        raise_err(ERR_PROGRAM_NOT_ACTIVE, "Appointment reinstatement requires program status ACTIVE.")
    if now_dt() > a["effective_to"]:
        raise_err(ERR_APPOINTMENT_WINDOW_CLOSED, "The appointment window has closed.")
    # Referred claims are NOT auto-returned; they stay REFERRED for carrier decision.
    a["status"] = "ACTIVE"
    touch(a)
    return success_object(serialize.appointment(a))


@bp.post("/mga/tpa-appointments/<appointmentId>/revoke")
def revoke_appointment(appointmentId):
    a, program = _carrier_scoped_appointment(appointmentId)
    if a["status"] not in ("ACTIVE", "SUSPENDED"):
        raise_err(ERR_INVALID_STATE, "Only an ACTIVE or SUSPENDED appointment can be revoked.")
    was_active = a["status"] == "ACTIVE"
    a["status"] = "REVOKED"
    touch(a)
    if was_active:
        # Revoking from ACTIVE refers its UNDER_REVIEW claims; claims still
        # REPORTED stay REPORTED but can never start review.
        cascades.refer_under_review_claims_of_appointment(a)
    return success_object(serialize.appointment(a))
