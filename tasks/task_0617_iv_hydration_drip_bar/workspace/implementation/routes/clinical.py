"""Intake-screening reads, consent lifecycle, adverse-event lifecycle, and the
appointment-scoped reverse lookups for screenings/consents/adverse-events.
"""
from flask import Blueprint

import db
import serialize
import validate as v
from errors import (
    err,
    ERR_INVALID_STATE,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_CONSENT_NOT_AFFIRMED,
)
from helpers import get_or_404, sort_paginate, recompute_open_adverse_event_count
from middleware import authenticate, require_role
from response import success, success_list
from services import booking

bp = Blueprint("clinical", __name__)


# --------------------------------------------------------------------------
# IntakeScreening reads
# --------------------------------------------------------------------------
@bp.route("/intake-screenings/<id>", methods=["GET"])
def get_intake_screening(id):
    _, role = authenticate()
    require_role(role, {"ClinicAdmin", "IntakeNurse", "MedicalDirector"})
    rec = get_or_404(db.intake_screenings, id, "intake screening")
    return success(serialize.intake_screening(rec), status=200)


@bp.route("/appointments/<id>/intake-screenings", methods=["GET"])
def appointment_intake_screenings(id):
    _, role = authenticate()
    require_role(role, {"ClinicAdmin", "IntakeNurse", "MedicalDirector"})
    get_or_404(db.appointments, id, "appointment")
    limit, offset = v.parse_pagination()
    items = [s for s in db.intake_screenings.values() if s["appointment_id"] == id]
    page, total = sort_paginate(items, limit, offset)
    return success_list([serialize.intake_screening(r) for r in page], limit, offset, total)


# --------------------------------------------------------------------------
# Consent
# --------------------------------------------------------------------------
@bp.route("/consents", methods=["POST"])
def create_consent():
    _, role = authenticate()
    require_role(role, {"IntakeNurse", "ClinicAdmin"})
    body = v.body_obj()
    appointment_id = v.as_string(v.require(body, "appointment_id"), "appointment_id")
    signed = v.require(body, "signed_by_patient")
    witness = v.as_string(v.require(body, "witness_user_id"), "witness_user_id")

    # Existence (FK).
    get_or_404(db.appointments, appointment_id, "appointment")

    # signed_by_patient must be true (else ERR_CONSENT_NOT_AFFIRMED, 422).
    if not isinstance(signed, bool):
        raise err(ERR_CONSENT_NOT_AFFIRMED, "signed_by_patient must be true.")
    if signed is not True:
        raise err(ERR_CONSENT_NOT_AFFIRMED, "signed_by_patient must be true.")

    # SoD: witness_user_id must differ from the screening author for this
    # appointment (latest SUBMITTED screening).
    screening = booking.latest_submitted_screening(appointment_id)
    if screening is not None and witness == screening["author_user_id"]:
        raise err(ERR_SEGREGATION_OF_DUTIES,
                  "Consent witness must differ from the screening author.")

    rec = {
        "appointment_id": appointment_id, "signed_by_patient": True,
        "witness_user_id": witness, "status": "SIGNED",
    }
    db.stamp_create(rec)
    db.consents[rec["id"]] = rec
    return success(serialize.consent(rec), status=201)


@bp.route("/consents/<id>", methods=["GET"])
def get_consent(id):
    _, role = authenticate()
    require_role(role, {"ClinicAdmin", "IntakeNurse", "MedicalDirector"})
    rec = get_or_404(db.consents, id, "consent")
    return success(serialize.consent(rec), status=200)


@bp.route("/consents/<id>/revoke", methods=["POST"])
def revoke_consent(id):
    _, role = authenticate()
    require_role(role, {"IntakeNurse", "ClinicAdmin", "MedicalDirector"})
    rec = get_or_404(db.consents, id, "consent")
    if rec["status"] != "SIGNED":
        raise err(ERR_INVALID_STATE, "Consent is not SIGNED.")
    rec["status"] = "REVOKED"
    db.touch(rec)
    return success(serialize.consent(rec), status=200)


@bp.route("/appointments/<id>/consents", methods=["GET"])
def appointment_consents(id):
    _, role = authenticate()
    require_role(role, {"ClinicAdmin", "IntakeNurse", "MedicalDirector"})
    get_or_404(db.appointments, id, "appointment")
    limit, offset = v.parse_pagination()
    items = [c for c in db.consents.values() if c["appointment_id"] == id]
    page, total = sort_paginate(items, limit, offset)
    return success_list([serialize.consent(r) for r in page], limit, offset, total)


# --------------------------------------------------------------------------
# AdverseEvent
# --------------------------------------------------------------------------
@bp.route("/adverse-events", methods=["POST"])
def create_adverse_event():
    _, role = authenticate()
    require_role(role, {"Nurse", "MedicalDirector"})
    body = v.body_obj()
    appointment_id = v.as_string(v.require(body, "appointment_id"), "appointment_id")
    reporter = v.as_string(v.require(body, "reported_by_user_id"), "reported_by_user_id")
    severity = v.as_enum(v.require(body, "severity"), "severity", {"MILD", "MODERATE", "SEVERE"})
    description = v.as_string(v.require(body, "description"), "description")

    appt = get_or_404(db.appointments, appointment_id, "appointment")

    # Reaction may only be reported against IN_PROGRESS or COMPLETED appts.
    if appt["status"] not in ("IN_PROGRESS", "COMPLETED"):
        raise err(ERR_INVALID_STATE, "Appointment is not IN_PROGRESS or COMPLETED.")

    rec = {
        "appointment_id": appointment_id, "reported_by_user_id": reporter,
        "severity": severity, "description": description, "status": "REPORTED",
    }
    db.stamp_create(rec)
    db.adverse_events[rec["id"]] = rec

    # Recompute patient open_adverse_event_count (increment).
    recompute_open_adverse_event_count(appt["patient_id"])

    return success(serialize.adverse_event(rec), status=201)


@bp.route("/adverse-events/<id>", methods=["GET"])
def get_adverse_event(id):
    _, role = authenticate()
    require_role(role, {"ClinicAdmin", "MedicalDirector", "Nurse"})
    rec = get_or_404(db.adverse_events, id, "adverse event")
    return success(serialize.adverse_event(rec), status=200)


@bp.route("/adverse-events/<id>/review", methods=["POST"])
def review_adverse_event(id):
    _, role = authenticate()
    require_role(role, {"MedicalDirector"})
    rec = get_or_404(db.adverse_events, id, "adverse event")
    if rec["status"] != "REPORTED":
        raise err(ERR_INVALID_STATE, "Adverse event is not REPORTED.")
    rec["status"] = "UNDER_REVIEW"
    db.touch(rec)
    # REPORTED->UNDER_REVIEW leaves open_adverse_event_count unchanged (both open).
    return success(serialize.adverse_event(rec), status=200)


@bp.route("/adverse-events/<id>/resolve", methods=["POST"])
def resolve_adverse_event(id):
    _, role = authenticate()
    require_role(role, {"MedicalDirector"})
    rec = get_or_404(db.adverse_events, id, "adverse event")
    if rec["status"] != "UNDER_REVIEW":
        raise err(ERR_INVALID_STATE, "Adverse event is not UNDER_REVIEW.")
    rec["status"] = "RESOLVED"
    db.touch(rec)
    # Recompute patient open_adverse_event_count (decrement).
    appt = db.appointments.get(rec["appointment_id"])
    if appt is not None:
        recompute_open_adverse_event_count(appt["patient_id"])
    return success(serialize.adverse_event(rec), status=200)


@bp.route("/appointments/<id>/adverse-events", methods=["GET"])
def appointment_adverse_events(id):
    _, role = authenticate()
    require_role(role, {"ClinicAdmin", "MedicalDirector", "Nurse"})
    get_or_404(db.appointments, id, "appointment")
    limit, offset = v.parse_pagination()
    items = [a for a in db.adverse_events.values() if a["appointment_id"] == id]
    page, total = sort_paginate(items, limit, offset)
    return success_list([serialize.adverse_event(r) for r in page], limit, offset, total)
