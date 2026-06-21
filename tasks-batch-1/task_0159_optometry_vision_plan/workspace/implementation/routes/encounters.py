"""Encounter lifecycle: open, get, list, finalize, void."""
from flask import Blueprint, request, g

import clock
import errors
import helpers
import response
import serialize
from db import db, new_id, stamp_create, touch
from middleware import require_roles

bp = Blueprint("encounters", __name__)

ENCOUNTER_TYPES = {"ROUTINE_VISION", "MEDICAL_EYE"}


@bp.post("/encounters")
@require_roles("FrontDesk", "Optometrist")
def create_encounter():
    body = helpers.get_json_body()
    patient_id = helpers.require_str(body, "patient_id")
    provider_id = helpers.require_str(body, "provider_id")

    # Body FK existence (priority 4) before schema (priority 5)
    patient = db.patients.get(patient_id)
    if patient is None:
        raise errors.reference_not_found("patient_id references no Patient")
    provider = db.providers.get(provider_id)
    if provider is None:
        raise errors.reference_not_found("provider_id references no Provider")

    encounter_type = helpers.require_enum(body, "encounter_type", ENCOUNTER_TYPES)
    chief = helpers.require_str(body, "chief_complaint_code", required=False)
    if chief is None:
        chief = "Z01"
    exam_fee = helpers.require_int(body, "exam_fee_cents", minimum=0)
    refraction_fee = helpers.require_int(body, "refraction_fee_cents",
                                         required=False, minimum=0, default=0)

    # Business referential (priority 7): provider role must be OPTOMETRIST
    if provider["role"] != "OPTOMETRIST":
        raise errors.wrong_provider_role(
            "Encounter provider must have role OPTOMETRIST")

    record = {
        "id": new_id(),
        "patient_id": patient_id,
        "provider_id": provider_id,
        "encounter_type": encounter_type,
        "chief_complaint_code": chief,
        "exam_fee_cents": exam_fee,
        "refraction_fee_cents": refraction_fee,
        "status": "OPEN",
        "refraction_recorded": False,
    }
    stamp_create(record)
    db.encounters[record["id"]] = record
    return response.object_response(serialize.encounter(record), 201)


@bp.get("/encounters/<encounter_id>")
@require_roles("FrontDesk", "Optometrist", "Biller")
def get_encounter(encounter_id):
    record = db.encounters.get(encounter_id)
    if record is None:
        raise errors.not_found("Encounter not found")
    return response.object_response(serialize.encounter(record), 200)


@bp.get("/encounters")
@require_roles("FrontDesk", "Optometrist", "Biller")
def list_encounters():
    limit, offset = helpers.parse_pagination()
    patient_id = request.args.get("patient_id")
    provider_id = request.args.get("provider_id")
    status = request.args.get("status")
    records = list(db.encounters.values())
    if patient_id is not None:
        records = [r for r in records if r["patient_id"] == patient_id]
    if provider_id is not None:
        records = [r for r in records if r["provider_id"] == provider_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, total = helpers.paginate(records, limit, offset)
    return response.array_response(
        [serialize.encounter(r) for r in page], limit, offset, total, 200)


@bp.post("/encounters/<encounter_id>/finalize")
@require_roles("Optometrist")
def finalize_encounter(encounter_id):
    record = db.encounters.get(encounter_id)
    if record is None:
        raise errors.not_found("Encounter not found")
    if record["status"] != "REFRACTED":
        raise errors.invalid_state("Encounter must be REFRACTED to finalize")

    record["status"] = "FINALIZED"
    touch(record)

    if record["encounter_type"] == "ROUTINE_VISION":
        patient = db.patients.get(record["patient_id"])
        if patient is not None:
            today = clock.current_date()
            patient["last_routine_exam_date"] = today.isoformat()
            touch(patient)
            # Fulfill SENT reminders whose due_date has passed (bubble-up).
            _fulfill_reminders(patient["id"], today)

    return response.object_response(serialize.encounter(record), 200)


def _fulfill_reminders(patient_id, today):
    for r in db.recall_reminders.values():
        if r["patient_id"] != patient_id:
            continue
        if r["status"] != "SENT":
            continue
        due = r.get("due_date")
        if due is None:
            continue
        if clock.parse_date(due) is not None and today > clock.parse_date(due):
            r["status"] = "FULFILLED"
            touch(r)


@bp.post("/encounters/<encounter_id>/void")
@require_roles("FrontDesk")
def void_encounter(encounter_id):
    record = db.encounters.get(encounter_id)
    if record is None:
        raise errors.not_found("Encounter not found")
    if record["status"] != "OPEN":
        raise errors.invalid_state("Encounter must be OPEN to void")
    # no Prescription references this Encounter
    for rx in db.prescriptions.values():
        if rx["encounter_id"] == encounter_id:
            raise errors.invalid_state(
                "Encounter has a prescription and cannot be voided")

    record["status"] = "VOIDED"
    touch(record)
    return response.object_response(serialize.encounter(record), 200)
