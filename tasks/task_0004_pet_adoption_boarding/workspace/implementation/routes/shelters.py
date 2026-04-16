from flask import Blueprint, request
from db import shelters, animals, compliance_holds, gen_id, now_iso
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_SHELTER_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_CRITICAL_HOLD_PRESENT,
)
from middleware import require_roles, parse_pagination, get_auth
from response import success_response, list_response
from services.animal_service import serialize_shelter

shelters_bp = Blueprint("shelters", __name__)


@shelters_bp.route("/petcare/shelters", methods=["POST"])
def create_shelter():
    require_roles("ShelterManager")
    body = request.get_json(silent=True) or {}

    name = body.get("name")
    address = body.get("address")
    contact_email = body.get("contact_email")
    boarding_capacity = body.get("boarding_capacity")
    tax_rate = body.get("tax_rate")

    if not name or not isinstance(name, str):
        raise_error(ERR_INVALID_REQUEST, "name is required")
    if not address or not isinstance(address, str):
        raise_error(ERR_INVALID_REQUEST, "address is required")
    if not contact_email or not isinstance(contact_email, str):
        raise_error(ERR_INVALID_REQUEST, "contact_email is required")
    if not isinstance(boarding_capacity, int) or isinstance(boarding_capacity, bool):
        raise_error(ERR_INVALID_REQUEST, "boarding_capacity must be an integer")
    if boarding_capacity < 1:
        raise_error(ERR_INVALID_REQUEST, "boarding_capacity must be >= 1")
    if not isinstance(tax_rate, (int, float)) or isinstance(tax_rate, bool):
        raise_error(ERR_INVALID_REQUEST, "tax_rate must be numeric")
    if tax_rate < 0 or tax_rate > 0.30:
        raise_error(ERR_INVALID_REQUEST, "tax_rate must be between 0 and 0.30")

    sid = gen_id()
    ts = now_iso()
    shelter = {
        "id": sid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "name": name,
        "address": address,
        "contact_email": contact_email,
        "boarding_capacity": boarding_capacity,
        "tax_rate": tax_rate,
        "status": "OPEN",
    }
    shelters[sid] = shelter
    return success_response(serialize_shelter(shelter), status_code=201)


@shelters_bp.route("/petcare/shelters", methods=["GET"])
def list_shelters():
    require_roles("ShelterManager", "CaseWorker", "Veterinarian")
    limit, offset = parse_pagination()
    status = request.args.get("status")
    items = [s for s in shelters.values() if (not status or s["status"] == status)]
    items.sort(key=lambda x: x["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return list_response([serialize_shelter(s) for s in page], total, limit, offset)


@shelters_bp.route("/petcare/shelters/<shelter_id>", methods=["GET"])
def get_shelter(shelter_id):
    require_roles("ShelterManager", "CaseWorker", "Veterinarian")
    shelter = shelters.get(shelter_id)
    if not shelter:
        raise_error(ERR_SHELTER_NOT_FOUND, "Shelter not found")
    return success_response(serialize_shelter(shelter))


@shelters_bp.route("/petcare/shelters/<shelter_id>/suspend", methods=["POST"])
def suspend_shelter(shelter_id):
    require_roles("ShelterManager")
    shelter = shelters.get(shelter_id)
    if not shelter:
        raise_error(ERR_SHELTER_NOT_FOUND, "Shelter not found")
    if shelter["status"] != "OPEN":
        raise_error(ERR_INVALID_STATE, "Shelter must be OPEN to suspend")
    shelter["status"] = "SUSPENDED"
    shelter["updated_at"] = now_iso()
    shelter["version"] += 1
    return success_response(serialize_shelter(shelter))


@shelters_bp.route("/petcare/shelters/<shelter_id>/reopen", methods=["POST"])
def reopen_shelter(shelter_id):
    require_roles("ShelterManager")
    shelter = shelters.get(shelter_id)
    if not shelter:
        raise_error(ERR_SHELTER_NOT_FOUND, "Shelter not found")
    if shelter["status"] != "SUSPENDED":
        raise_error(ERR_INVALID_STATE, "Shelter must be SUSPENDED to reopen")
    # Check no animal has ACTIVE CRITICAL hold
    for a in animals.values():
        if a["shelter_id"] != shelter_id:
            continue
        for h in compliance_holds.values():
            if (h["animal_id"] == a["id"] and h["status"] == "ACTIVE"
                    and h["severity"] == "CRITICAL"):
                raise_error(ERR_CRITICAL_HOLD_PRESENT,
                            "Cannot reopen: critical hold present")
    shelter["status"] = "OPEN"
    shelter["updated_at"] = now_iso()
    shelter["version"] += 1
    return success_response(serialize_shelter(shelter))
