from flask import Blueprint, request
from db import (
    animals,
    vaccination_records,
    gen_id,
    now_iso,
    utc_now,
    parse_iso,
)
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_INVALID_DATES,
    ERR_ANIMAL_NOT_FOUND,
    ERR_VACCINATION_RECORD_NOT_FOUND,
)
from middleware import require_roles, parse_pagination, get_auth
from response import success_response, list_response
from services.animal_service import serialize_vaccination

vaccination_records_bp = Blueprint("vaccination_records", __name__)

VALID_VACCINES = {"RABIES", "DHPP", "FVRCP", "BORDETELLA", "RHDV", "OTHER"}


@vaccination_records_bp.route("/petcare/vaccination-records", methods=["POST"])
def create_vaccination_record():
    user_id, _ = require_roles("Veterinarian")
    body = request.get_json(silent=True) or {}

    animal_id = body.get("animal_id")
    vaccine_name = body.get("vaccine_name")
    administered_date = body.get("administered_date")
    expiry_date = body.get("expiry_date")
    batch_number = body.get("batch_number")

    if not animal_id or not isinstance(animal_id, str):
        raise_error(ERR_INVALID_REQUEST, "animal_id is required")
    if animal_id not in animals:
        raise_error(ERR_ANIMAL_NOT_FOUND, "Animal not found")
    if vaccine_name not in VALID_VACCINES:
        raise_error(ERR_INVALID_REQUEST, "vaccine_name is invalid")
    if not administered_date:
        raise_error(ERR_INVALID_REQUEST, "administered_date is required")
    if not expiry_date:
        raise_error(ERR_INVALID_REQUEST, "expiry_date is required")
    if not isinstance(batch_number, str) or not batch_number:
        raise_error(ERR_INVALID_REQUEST, "batch_number is required")

    adm_dt = parse_iso(administered_date)
    exp_dt = parse_iso(expiry_date)
    if adm_dt is None or exp_dt is None:
        raise_error(ERR_INVALID_DATES, "Invalid date format")
    now = utc_now()
    if adm_dt > now:
        raise_error(ERR_INVALID_DATES, "administered_date must be <= current time")
    if exp_dt <= adm_dt:
        raise_error(ERR_INVALID_DATES, "expiry_date must be strictly greater than administered_date")

    rid = gen_id()
    ts = now_iso()
    rec = {
        "id": rid,
        "created_at": ts,
        "animal_id": animal_id,
        "vaccine_name": vaccine_name,
        "administered_date": administered_date,
        "expiry_date": expiry_date,
        "batch_number": batch_number,
        "veterinarian_id": user_id,
    }
    vaccination_records[rid] = rec
    return success_response(serialize_vaccination(rec), status_code=201)


@vaccination_records_bp.route("/petcare/vaccination-records", methods=["GET"])
def list_vaccination_records():
    require_roles("ShelterManager", "CaseWorker", "Veterinarian")
    limit, offset = parse_pagination()
    animal_id = request.args.get("animal_id")
    vaccine_name = request.args.get("vaccine_name")
    items = []
    for r in vaccination_records.values():
        if animal_id and r["animal_id"] != animal_id:
            continue
        if vaccine_name and r["vaccine_name"] != vaccine_name:
            continue
        items.append(r)
    items.sort(key=lambda x: x["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return list_response([serialize_vaccination(x) for x in page], total, limit, offset)


@vaccination_records_bp.route("/petcare/vaccination-records/<record_id>", methods=["GET"])
def get_vaccination_record(record_id):
    require_roles("ShelterManager", "CaseWorker", "Veterinarian")
    r = vaccination_records.get(record_id)
    if not r:
        raise_error(ERR_VACCINATION_RECORD_NOT_FOUND, "Vaccination record not found")
    return success_response(serialize_vaccination(r))
