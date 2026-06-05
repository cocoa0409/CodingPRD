"""Appointment endpoints, scheduling validations, and state machine (PRD §3.4)."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_APPOINTMENT_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_ITEM_NOT_FOUND,
    ERR_OPERATORY_DOUBLE_BOOKED,
    ERR_OPERATORY_NOT_FOUND,
    ERR_PATIENT_INACTIVE,
    ERR_PATIENT_NOT_FOUND,
    ERR_PLAN_NOT_ACCEPTED,
    ERR_PREDETERMINATION_NOT_APPROVED,
    ERR_PROVIDER_NOT_FOUND,
    ERR_PROVIDER_TYPE_MISMATCH,
    ERR_VALIDATION,
)
from middleware import (
    ROLE_BILLING,
    ROLE_CLINICIAN,
    ROLE_FRONT_DESK,
    ROLE_PATIENT,
)
from response import ok_array, ok_object
from routes._helpers import apply_filters, enforce_patient_ownership, guard
from services import clock, common

bp = Blueprint("appointments", __name__)

NON_TERMINAL_APPT = {"SCHEDULED", "CHECKED_IN"}


def _intervals_overlap(a_start, a_end, b_start, b_end) -> bool:
    """Half-open interval overlap: [a_start, a_end) intersects [b_start, b_end)."""
    return a_start < b_end and b_start < a_end


@bp.post("/appointments")
def create_appointment():
    guard([ROLE_FRONT_DESK])
    body = common.get_json_body()
    common.require_fields(body, [
        "patient_id", "provider_id", "operatory_id", "appointment_type", "start_at", "end_at",
    ])
    # --- existence (body FKs) — left-to-right per declared input order (§2.8) ---
    patient_id = common.require_string(body, "patient_id")
    patient = common.resolve(db.patients, patient_id, ERR_PATIENT_NOT_FOUND)
    provider_id = common.require_string(body, "provider_id")
    provider = common.resolve(db.providers, provider_id, ERR_PROVIDER_NOT_FOUND)
    operatory_id = common.require_string(body, "operatory_id")
    operatory = common.resolve(db.operatories, operatory_id, ERR_OPERATORY_NOT_FOUND)

    item = None
    tpi_id = body.get("treatment_plan_item_id")
    if tpi_id is not None:
        if not isinstance(tpi_id, str):
            raise APIError(ERR_VALIDATION, 422, "treatment_plan_item_id must be a string")
        item = common.resolve(db.treatment_plan_items, tpi_id, ERR_ITEM_NOT_FOUND)

    # --- body well-formedness (§2.8 step after existence) ---
    appointment_type = common.require_enum(body, "appointment_type", {"PREVENTIVE", "OPERATIVE"})
    start_raw = common.require_string(body, "start_at")
    end_raw = common.require_string(body, "end_at")
    try:
        start_at = clock.parse_dt(start_raw)
        end_at = clock.parse_dt(end_raw)
    except Exception:
        raise APIError(ERR_VALIDATION, 422, "start_at/end_at must be ISO 8601 datetimes")
    if not (end_at > start_at):
        raise APIError(ERR_VALIDATION, 422, "end_at must be strictly after start_at")

    # --- referential business rules (priority 7, ERR_PROVIDER_TYPE_MISMATCH) ---
    # HYGIENIST may own only PREVENTIVE appointments.
    if provider["provider_type"] == "HYGIENIST" and appointment_type == "OPERATIVE":
        raise APIError(ERR_PROVIDER_TYPE_MISMATCH, 409, "HYGIENIST may only own PREVENTIVE appointments")
    # CLOSED operatory rejects new appointments.
    if operatory["status"] != "OPEN":
        raise APIError(ERR_PROVIDER_TYPE_MISMATCH, 409, "Operatory is CLOSED")
    # INACTIVE provider or patient.
    if provider["status"] != "ACTIVE":
        raise APIError(ERR_PROVIDER_TYPE_MISMATCH, 409, "Provider is INACTIVE")
    if patient["status"] != "ACTIVE":
        raise APIError(ERR_PROVIDER_TYPE_MISMATCH, 409, "Patient is INACTIVE")

    # --- temporal double-booking (priority 8, ERR_OPERATORY_DOUBLE_BOOKED) ---
    _check_double_booking(operatory, provider_id, start_at, end_at)

    # --- item bubble to SCHEDULED (state preconditions) ---
    if item is not None:
        plan = db.treatment_plans[item["treatment_plan_id"]]
        if plan["status"] != "ACCEPTED":
            raise APIError(ERR_PLAN_NOT_ACCEPTED, 409, "Parent plan must be ACCEPTED")
        if item["requires_predetermination"]:
            pre_id = item.get("predetermination_id")
            pre = db.predeterminations.get(pre_id) if pre_id else None
            if pre is None or pre["status"] != "APPROVED":
                raise APIError(ERR_PREDETERMINATION_NOT_APPROVED, 409,
                               "Item requires an APPROVED predetermination")

    rec = common.new_common_fields()
    rec.update({
        "patient_id": patient_id,
        "provider_id": provider_id,
        "operatory_id": operatory_id,
        "treatment_plan_item_id": tpi_id,
        "appointment_type": appointment_type,
        "start_at": start_raw,
        "end_at": end_raw,
        "status": "SCHEDULED",
        "_start_dt": start_at,
        "_end_dt": end_at,
    })
    db.appointments[rec["id"]] = rec

    if item is not None:
        item["status"] = "SCHEDULED"
        item["appointment_id"] = rec["id"]
        common.touch(item)

    return ok_object(common.serialize(rec), 201)


def _check_double_booking(operatory, provider_id, start_at, end_at):
    buffer = timedelta(minutes=operatory["turnover_buffer_minutes"])
    for appt in db.appointments.values():
        if appt["status"] not in NON_TERMINAL_APPT:
            continue
        ex_start = appt["_start_dt"]
        ex_end = appt["_end_dt"]
        # Same operatory: existing booking's room interval is widened by the
        # operatory's turnover buffer appended after the booking (PRD §3.4).
        if appt["operatory_id"] == operatory["id"]:
            if _intervals_overlap(start_at, end_at, ex_start, ex_end + buffer):
                raise APIError(ERR_OPERATORY_DOUBLE_BOOKED, 409, "Operatory chair-time conflict")
        # Same provider: no buffer.
        if appt["provider_id"] == provider_id:
            if _intervals_overlap(start_at, end_at, ex_start, ex_end):
                raise APIError(ERR_OPERATORY_DOUBLE_BOOKED, 409, "Provider chair-time conflict")


@bp.get("/appointments")
def list_appointments():
    guard([ROLE_FRONT_DESK, ROLE_CLINICIAN, ROLE_BILLING])
    records = apply_filters(list(db.appointments.values()), {
        "patient_id": request.args.get("patient_id"),
        "provider_id": request.args.get("provider_id"),
        "operatory_id": request.args.get("operatory_id"),
        "treatment_plan_item_id": request.args.get("treatment_plan_item_id"),
        "status": request.args.get("status"),
    })
    items, limit, offset, total = common.paginate(records)
    return ok_array(items, limit, offset, total)


@bp.get("/appointments/<appointment_id>")
def get_appointment(appointment_id):
    guard([ROLE_FRONT_DESK, ROLE_CLINICIAN, ROLE_BILLING, ROLE_PATIENT])
    rec = common.resolve(db.appointments, appointment_id, ERR_APPOINTMENT_NOT_FOUND)
    enforce_patient_ownership(rec["patient_id"])
    return ok_object(common.serialize(rec), 200)


@bp.post("/appointments/<appointment_id>/check-in")
def check_in(appointment_id):
    guard([ROLE_FRONT_DESK])
    rec = common.resolve(db.appointments, appointment_id, ERR_APPOINTMENT_NOT_FOUND)
    if rec["status"] != "SCHEDULED":
        raise APIError(ERR_INVALID_STATE, 409, "Appointment must be SCHEDULED to check in")
    patient = db.patients[rec["patient_id"]]
    if patient["status"] != "ACTIVE":
        raise APIError(ERR_PATIENT_INACTIVE, 409, "Patient is INACTIVE")
    rec["status"] = "CHECKED_IN"
    common.touch(rec)
    return ok_object(common.serialize(rec), 200)


@bp.post("/appointments/<appointment_id>/complete")
def complete_appointment(appointment_id):
    guard([ROLE_CLINICIAN])
    rec = common.resolve(db.appointments, appointment_id, ERR_APPOINTMENT_NOT_FOUND)
    if rec["status"] != "CHECKED_IN":
        raise APIError(ERR_INVALID_STATE, 409, "Appointment must be CHECKED_IN to complete")
    rec["status"] = "COMPLETED"
    common.touch(rec)
    # Bubble linked item SCHEDULED -> COMPLETED.
    tpi_id = rec.get("treatment_plan_item_id")
    if tpi_id:
        item = db.treatment_plan_items.get(tpi_id)
        if item is not None and item["status"] == "SCHEDULED":
            item["status"] = "COMPLETED"
            common.touch(item)
    return ok_object(common.serialize(rec), 200)


@bp.post("/appointments/<appointment_id>/cancel")
def cancel_appointment(appointment_id):
    guard([ROLE_FRONT_DESK])
    rec = common.resolve(db.appointments, appointment_id, ERR_APPOINTMENT_NOT_FOUND)
    if rec["status"] not in ("SCHEDULED", "CHECKED_IN"):
        raise APIError(ERR_INVALID_STATE, 409, "Appointment must be SCHEDULED or CHECKED_IN to cancel")
    rec["status"] = "CANCELLED"
    common.touch(rec)
    _release_linked_item(rec)
    return ok_object(common.serialize(rec), 200)


@bp.post("/appointments/<appointment_id>/no-show")
def no_show_appointment(appointment_id):
    guard([ROLE_FRONT_DESK])
    rec = common.resolve(db.appointments, appointment_id, ERR_APPOINTMENT_NOT_FOUND)
    if rec["status"] != "SCHEDULED":
        raise APIError(ERR_INVALID_STATE, 409, "Appointment must be SCHEDULED to mark no-show")
    rec["status"] = "NO_SHOW"
    common.touch(rec)
    _release_linked_item(rec)
    return ok_object(common.serialize(rec), 200)


def _release_linked_item(appt):
    """If the linked item is SCHEDULED, release it back to PLANNED and clear its
    appointment_id (PRD §3.4)."""
    tpi_id = appt.get("treatment_plan_item_id")
    if not tpi_id:
        return
    item = db.treatment_plan_items.get(tpi_id)
    if item is not None and item["status"] == "SCHEDULED":
        item["status"] = "PLANNED"
        item["appointment_id"] = None
        common.touch(item)
