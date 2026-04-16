"""Shelter endpoints."""

from flask import Blueprint, request
import db
from db import new_id, now_iso
from middleware import require_role, get_pagination
from response import success_object, success_list
from errors import raise_error, ERR_SHELTER_NOT_FOUND, ERR_INVALID_STATE, ERR_COMPLIANCE_HOLD_ACTIVE, ERR_INVALID_REQUEST
from services.compliance import has_active_critical_hold_in_shelter

bp = Blueprint("shelters", __name__)


def serialize_shelter(s):
    return {k: v for k, v in s.items()}


@bp.route("/shelters", methods=["POST"])
def create_shelter():
    user_id, role = require_role("ShelterManager")
    body = request.get_json(force=True, silent=True) or {}
    name = body.get("name")
    address = body.get("address")
    boarding_capacity = body.get("boarding_capacity")
    if not name or not address or boarding_capacity is None:
        raise_error(ERR_INVALID_REQUEST, "Missing required fields: name, address, boarding_capacity")

    tax_rate = body.get("tax_rate", 0.0)

    ts = now_iso()
    shelter = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "name": name,
        "address": address,
        "boarding_capacity": boarding_capacity,
        "current_boarding_count": 0,
        "adoption_count": 0,
        "compliance_score": 100.0,
        "revenue_balance": 0.0,
        "tax_rate": tax_rate,
        "status": "OPEN",
    }
    db.shelters[shelter["id"]] = shelter
    return success_object(serialize_shelter(shelter), 201)


@bp.route("/shelters", methods=["GET"])
def list_shelters():
    require_role("ShelterManager", "CaseWorker", "Veterinarian")
    limit, offset = get_pagination()
    items = sorted(db.shelters.values(), key=lambda x: x["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_shelter(s) for s in page], total, limit, offset)


@bp.route("/shelters/<shelterId>", methods=["GET"])
def get_shelter(shelterId):
    require_role("ShelterManager", "CaseWorker", "Veterinarian")
    shelter = db.shelters.get(shelterId)
    if not shelter:
        raise_error(ERR_SHELTER_NOT_FOUND, "Shelter not found")
    return success_object(serialize_shelter(shelter))


@bp.route("/shelters/<shelterId>/suspend", methods=["POST"])
def suspend_shelter(shelterId):
    user_id, role = require_role("ShelterManager")
    shelter = db.shelters.get(shelterId)
    if not shelter:
        raise_error(ERR_SHELTER_NOT_FOUND, "Shelter not found")
    if shelter["status"] != "OPEN":
        raise_error(ERR_INVALID_STATE, "Shelter must be OPEN to suspend")

    shelter["status"] = "SUSPENDED"
    shelter["updated_at"] = now_iso()
    shelter["version"] += 1
    return success_object(serialize_shelter(shelter))


@bp.route("/shelters/<shelterId>/reopen", methods=["POST"])
def reopen_shelter(shelterId):
    user_id, role = require_role("ShelterManager")
    shelter = db.shelters.get(shelterId)
    if not shelter:
        raise_error(ERR_SHELTER_NOT_FOUND, "Shelter not found")
    if shelter["status"] != "SUSPENDED":
        raise_error(ERR_INVALID_STATE, "Shelter must be SUSPENDED to reopen")

    if has_active_critical_hold_in_shelter(shelterId):
        raise_error(ERR_COMPLIANCE_HOLD_ACTIVE, "Cannot reopen: active CRITICAL compliance holds exist")

    shelter["status"] = "OPEN"
    shelter["updated_at"] = now_iso()
    shelter["version"] += 1
    return success_object(serialize_shelter(shelter))
