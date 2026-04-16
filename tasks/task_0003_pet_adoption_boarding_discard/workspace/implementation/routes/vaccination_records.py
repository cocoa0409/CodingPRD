"""Vaccination record endpoints."""

from flask import Blueprint, request
import db
from db import new_id, now_iso
from middleware import require_role, get_pagination
from response import success_object, success_list
from errors import raise_error, ERR_ANIMAL_NOT_FOUND, ERR_VACCINATION_RECORD_NOT_FOUND, ERR_INVALID_REQUEST
from services.vaccination import update_animal_vaccination_compliant, is_vaccination_record_valid
from services.compliance import recompute_shelter_compliance_score

bp = Blueprint("vaccination_records", __name__)


def serialize_record(r):
    return {k: v for k, v in r.items()}


@bp.route("/vaccination-records", methods=["POST"])
def create_vaccination_record():
    user_id, role = require_role("Veterinarian")
    body = request.get_json(force=True, silent=True) or {}

    required = ["animal_id", "vaccine_name", "administered_date", "expiry_date", "batch_number", "veterinarian_name"]
    for field in required:
        if field not in body or body[field] is None:
            raise_error(ERR_INVALID_REQUEST, f"Missing required field: {field}")

    animal = db.animals.get(body["animal_id"])
    if not animal:
        raise_error(ERR_ANIMAL_NOT_FOUND, "Animal not found")

    ts = now_iso()
    record = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "animal_id": body["animal_id"],
        "vaccine_name": body["vaccine_name"],
        "administered_date": body["administered_date"],
        "expiry_date": body["expiry_date"],
        "batch_number": body["batch_number"],
        "veterinarian_name": body["veterinarian_name"],
        "is_valid": is_vaccination_record_valid({"expiry_date": body["expiry_date"]}),
    }
    db.vaccination_records[record["id"]] = record

    # Recompute animal vaccination_compliant
    update_animal_vaccination_compliant(body["animal_id"])
    # Recompute shelter compliance_score
    recompute_shelter_compliance_score(animal["shelter_id"])

    return success_object(serialize_record(record), 201)


@bp.route("/vaccination-records", methods=["GET"])
def list_vaccination_records():
    require_role("ShelterManager", "CaseWorker", "Veterinarian")
    limit, offset = get_pagination()

    items = list(db.vaccination_records.values())
    animal_id = request.args.get("animal_id")
    if animal_id:
        items = [r for r in items if r["animal_id"] == animal_id]

    items.sort(key=lambda x: x["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_record(r) for r in page], total, limit, offset)


@bp.route("/vaccination-records/<recordId>", methods=["GET"])
def get_vaccination_record(recordId):
    require_role("ShelterManager", "CaseWorker", "Veterinarian")
    record = db.vaccination_records.get(recordId)
    if not record:
        raise_error(ERR_VACCINATION_RECORD_NOT_FOUND, "Vaccination record not found")
    return success_object(serialize_record(record))
