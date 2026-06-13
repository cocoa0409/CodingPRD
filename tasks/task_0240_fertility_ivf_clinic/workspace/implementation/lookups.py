"""Existence resolution (left-to-right per PRD §2.6) + pagination + list helpers."""

from flask import request

import db
import errors as E
from errors import fail


def get_clinic(clinic_id):
    rec = db.clinics.get(clinic_id)
    if rec is None:
        fail(E.ERR_CLINIC_NOT_FOUND, "Clinic %s not found" % clinic_id)
    return rec


def _scoped_get(collection, clinic_id, entity_id, not_found, scope_field="clinic_id"):
    rec = collection.get(entity_id)
    if rec is None or rec.get(scope_field) != clinic_id:
        fail(not_found, "%s not found" % entity_id)
    return rec


def get_package(clinic_id, pid):
    return _scoped_get(db.packages, clinic_id, pid, E.ERR_PACKAGE_NOT_FOUND)


def get_patient(clinic_id, pid):
    return _scoped_get(db.patients, clinic_id, pid, E.ERR_PATIENT_NOT_FOUND)


def get_donor(clinic_id, pid):
    return _scoped_get(db.donors, clinic_id, pid, E.ERR_DONOR_NOT_FOUND)


def get_surrogate(clinic_id, pid):
    return _scoped_get(db.surrogates, clinic_id, pid, E.ERR_SURROGATE_NOT_FOUND)


def get_consent_form(clinic_id, pid):
    return _scoped_get(db.consent_forms, clinic_id, pid, E.ERR_CONSENT_FORM_NOT_FOUND)


def get_consent(clinic_id, pid):
    """PatientConsent scoped to clinic via its patient's clinic_id."""
    rec = db.patient_consents.get(pid)
    if rec is None:
        fail(E.ERR_CONSENT_NOT_FOUND, "Consent %s not found" % pid)
    pat = db.patients.get(rec["patient_id"])
    if pat is None or pat.get("clinic_id") != clinic_id:
        fail(E.ERR_CONSENT_NOT_FOUND, "Consent %s not found" % pid)
    return rec


def get_tank(clinic_id, pid):
    return _scoped_get(db.tanks, clinic_id, pid, E.ERR_TANK_NOT_FOUND)


def get_cycle(clinic_id, pid):
    """TreatmentCycle scoped to clinic via its patient's clinic_id."""
    rec = db.cycles.get(pid)
    if rec is None:
        fail(E.ERR_CYCLE_NOT_FOUND, "Cycle %s not found" % pid)
    pat = db.patients.get(rec["patient_id"])
    if pat is None or pat.get("clinic_id") != clinic_id:
        fail(E.ERR_CYCLE_NOT_FOUND, "Cycle %s not found" % pid)
    return rec


def get_medication(clinic_id, pid):
    rec = db.medications.get(pid)
    if rec is None or rec.get("clinic_id") != clinic_id:
        fail(E.ERR_MEDICATION_NOT_FOUND, "Medication %s not found" % pid)
    return rec


def get_appointment(clinic_id, pid):
    rec = db.appointments.get(pid)
    if rec is None or rec.get("clinic_id") != clinic_id:
        fail(E.ERR_APPOINTMENT_NOT_FOUND, "Appointment %s not found" % pid)
    return rec


def get_specimen(clinic_id, pid):
    rec = db.specimens.get(pid)
    if rec is None or rec.get("clinic_id") != clinic_id:
        fail(E.ERR_SPECIMEN_NOT_FOUND, "Specimen %s not found" % pid)
    return rec


def get_invoice(clinic_id, pid):
    rec = db.invoices.get(pid)
    if rec is None or rec.get("clinic_id") != clinic_id:
        fail(E.ERR_INVOICE_NOT_FOUND, "Invoice %s not found" % pid)
    return rec


def get_outcome(clinic_id, pid):
    rec = db.outcomes.get(pid)
    if rec is None or rec.get("clinic_id") != clinic_id:
        fail(E.ERR_OUTCOME_NOT_FOUND, "Outcome %s not found" % pid)
    return rec


def parse_pagination():
    """limit default 10 (1..100), offset default 0 (PRD §2.3)."""
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            fail(E.ERR_VALIDATION, "limit must be an integer")
        if limit < 1 or limit > 100:
            fail(E.ERR_VALIDATION, "limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            fail(E.ERR_VALIDATION, "offset must be an integer")
        if offset < 0:
            fail(E.ERR_VALIDATION, "offset must be >= 0")
    return limit, offset


def paginate(records, serializer):
    """Sort by creation order, apply limit/offset, return (data, meta-page)."""
    limit, offset = parse_pagination()
    ordered = sorted(records, key=lambda r: r["_seq"])
    total = len(ordered)
    window = ordered[offset:offset + limit]
    data = [serializer(r) for r in window]
    page = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return data, page
