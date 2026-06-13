"""Prescription lifecycle: issue (from patient path), get, list, revoke."""
from decimal import Decimal

from flask import Blueprint, request

import clock
import errors
import helpers
import response
import serialize
from db import db, new_id, stamp_create, touch
from middleware import require_roles

bp = Blueprint("prescriptions", __name__)

RX_TYPES = {"EYEGLASS", "CONTACT"}
EXPIRY_MONTHS = {"EYEGLASS": 24, "CONTACT": 12}
SPHERE_MIN = Decimal("-20.00")
SPHERE_MAX = Decimal("20.00")
SPHERE_STEP = Decimal("0.25")


def _validate_sphere(value, field):
    # value already checked to be a number
    dec = Decimal(str(value))
    if dec < SPHERE_MIN or dec > SPHERE_MAX:
        raise errors.invalid_request("%s must be between -20.00 and 20.00" % field)
    if (dec / SPHERE_STEP) != (dec / SPHERE_STEP).to_integral_value():
        raise errors.invalid_request("%s must be a multiple of 0.25" % field)
    return value


@bp.post("/patients/<patient_id>/prescriptions")
@require_roles("Optometrist")
def issue_prescription(patient_id):
    # path existence (priority 3)
    patient = db.patients.get(patient_id)
    if patient is None:
        raise errors.not_found("Patient not found")

    body = helpers.get_json_body()
    encounter_id = helpers.require_str(body, "encounter_id")

    # body FK existence (priority 4)
    encounter = db.encounters.get(encounter_id)
    if encounter is None:
        raise errors.reference_not_found("encounter_id references no Encounter")

    rx_type = helpers.require_enum(body, "rx_type", RX_TYPES)
    sphere_od = helpers.require_number(body, "sphere_od")
    sphere_os = helpers.require_number(body, "sphere_os")
    _validate_sphere(sphere_od, "sphere_od")
    _validate_sphere(sphere_os, "sphere_os")
    issue_date = helpers.require_str(body, "issue_date")
    issue_dt = clock.parse_date(issue_date)
    if issue_dt is None:
        raise errors.invalid_request("issue_date must be a valid ISO date")

    # state legality (priority 6): encounter must be REFRACTED or FINALIZED
    if encounter["status"] not in ("REFRACTED", "FINALIZED", "OPEN"):
        raise errors.invalid_state(
            "Encounter must be OPEN, REFRACTED, or FINALIZED to issue an Rx")
    # The scaffold constraint: referenced Encounter.status must be REFRACTED or
    # FINALIZED — but issuing the *first* Rx from an OPEN encounter is the very
    # trigger that moves it to REFRACTED. So OPEN is allowed (it transitions);
    # VOIDED is not.
    if encounter["status"] == "VOIDED":
        raise errors.invalid_state("Encounter is VOIDED")

    months = EXPIRY_MONTHS[rx_type]
    expiry_date = clock.add_months(issue_dt, months)

    record = {
        "id": new_id(),
        "encounter_id": encounter_id,
        "patient_id": encounter["patient_id"],
        "rx_type": rx_type,
        "sphere_od": sphere_od,
        "sphere_os": sphere_os,
        "issue_date": issue_date,
        "expiry_months": months,
        "expiry_date": expiry_date.isoformat(),
        "status": "ACTIVE",
    }
    stamp_create(record)

    # Supersede any prior ACTIVE Rx of identical rx_type for this patient.
    for other in db.prescriptions.values():
        if (other["patient_id"] == encounter["patient_id"]
                and other["rx_type"] == rx_type
                and other["status"] == "ACTIVE"):
            other["status"] = "SUPERSEDED"
            touch(other)

    db.prescriptions[record["id"]] = record

    # If the source encounter is OPEN, advance it to REFRACTED.
    if encounter["status"] == "OPEN":
        encounter["refraction_recorded"] = True
        encounter["status"] = "REFRACTED"
        touch(encounter)

    return response.object_response(serialize.prescription(record), 201)


@bp.get("/prescriptions/<prescription_id>")
@require_roles("FrontDesk", "Optometrist", "Optician")
def get_prescription(prescription_id):
    record = db.prescriptions.get(prescription_id)
    if record is None:
        raise errors.not_found("Prescription not found")
    return response.object_response(serialize.prescription(record), 200)


@bp.get("/patients/<patient_id>/prescriptions")
@require_roles("FrontDesk", "Optometrist", "Optician")
def list_patient_prescriptions(patient_id):
    patient = db.patients.get(patient_id)
    if patient is None:
        raise errors.not_found("Patient not found")
    limit, offset = helpers.parse_pagination()
    rx_type = request.args.get("rx_type")
    status = request.args.get("status")
    records = [r for r in db.prescriptions.values() if r["patient_id"] == patient_id]
    if rx_type is not None:
        records = [r for r in records if r["rx_type"] == rx_type]
    if status is not None:
        records = [r for r in records
                   if serialize.effective_rx_status(r) == status]
    page, total = helpers.paginate(records, limit, offset)
    return response.array_response(
        [serialize.prescription(r) for r in page], limit, offset, total, 200)


@bp.get("/prescriptions")
@require_roles("FrontDesk", "Optometrist", "Optician")
def list_prescriptions():
    limit, offset = helpers.parse_pagination()
    encounter_id = request.args.get("encounter_id")
    patient_id = request.args.get("patient_id")
    records = list(db.prescriptions.values())
    if encounter_id is not None:
        records = [r for r in records if r["encounter_id"] == encounter_id]
    if patient_id is not None:
        records = [r for r in records if r["patient_id"] == patient_id]
    page, total = helpers.paginate(records, limit, offset)
    return response.array_response(
        [serialize.prescription(r) for r in page], limit, offset, total, 200)


@bp.post("/prescriptions/<prescription_id>/revoke")
@require_roles("Optometrist")
def revoke_prescription(prescription_id):
    record = db.prescriptions.get(prescription_id)
    if record is None:
        raise errors.not_found("Prescription not found")
    # Revocation legal only when stored status is ACTIVE (expiry is a read-time
    # derivation; an ACTIVE-but-past-expiry Rx reads EXPIRED, so block it too).
    if serialize.effective_rx_status(record) != "ACTIVE":
        raise errors.invalid_state("Prescription must be ACTIVE to revoke")
    # no LabOrder in PLACED or IN_LAB references this Rx
    for lo in db.lab_orders.values():
        if lo["prescription_id"] == prescription_id and lo["status"] in ("PLACED", "IN_LAB"):
            raise errors.invalid_state(
                "Prescription is referenced by an active lab order")

    record["status"] = "REVOKED"
    touch(record)
    return response.object_response(serialize.prescription(record), 200)
