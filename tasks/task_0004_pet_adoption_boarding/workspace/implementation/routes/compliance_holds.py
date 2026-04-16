from flask import Blueprint, request
from db import compliance_holds, animals, gen_id, now_iso
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_ANIMAL_NOT_FOUND,
    ERR_HOLD_NOT_FOUND,
    ERR_INVALID_STATE,
)
from middleware import require_roles, parse_pagination, get_auth
from response import success_response, list_response
from services.fee_service import serialize_compliance_hold
from services.animal_service import active_hold_count

compliance_holds_bp = Blueprint("compliance_holds", __name__)

VALID_HOLD_TYPES = {"VACCINATION_OVERDUE", "HEALTH_CONCERN", "BEHAVIOR_INCIDENT", "QUARANTINE"}
VALID_SEVERITIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}


@compliance_holds_bp.route("/petcare/compliance-holds", methods=["POST"])
def create_hold():
    user_id, role = require_roles("Veterinarian", "ShelterManager")
    body = request.get_json(silent=True) or {}
    animal_id = body.get("animal_id")
    hold_type = body.get("hold_type")
    severity = body.get("severity")
    reason = body.get("reason")

    if not animal_id:
        raise_error(ERR_INVALID_REQUEST, "animal_id is required")
    if animal_id not in animals:
        raise_error(ERR_ANIMAL_NOT_FOUND, "Animal not found")
    if hold_type not in VALID_HOLD_TYPES:
        raise_error(ERR_INVALID_REQUEST, "hold_type is invalid")
    if severity not in VALID_SEVERITIES:
        raise_error(ERR_INVALID_REQUEST, "severity is invalid")
    if not reason or not isinstance(reason, str):
        raise_error(ERR_INVALID_REQUEST, "reason is required")

    imposed_role = "VETERINARIAN" if role == "Veterinarian" else "SHELTER_MANAGER"

    hid = gen_id()
    ts = now_iso()
    hold = {
        "id": hid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "animal_id": animal_id,
        "hold_type": hold_type,
        "severity": severity,
        "reason": reason,
        "imposed_by": user_id,
        "imposed_role": imposed_role,
        "resolved_by": None,
        "resolution_notes": None,
        "status": "ACTIVE",
    }
    compliance_holds[hid] = hold

    animal = animals.get(animal_id)
    if severity in ("HIGH", "CRITICAL") and animal:
        if animal["status"] in ("AVAILABLE", "BOARDING"):
            animal["status"] = "UNAVAILABLE"
            animal["updated_at"] = now_iso()
            animal["version"] += 1

    return success_response(serialize_compliance_hold(hold), status_code=201)


@compliance_holds_bp.route("/petcare/compliance-holds", methods=["GET"])
def list_holds():
    require_roles("ShelterManager", "CaseWorker", "Veterinarian")
    limit, offset = parse_pagination()
    animal_id = request.args.get("animal_id")
    status = request.args.get("status")
    severity = request.args.get("severity")
    hold_type = request.args.get("hold_type")
    items = []
    for h in compliance_holds.values():
        if animal_id and h["animal_id"] != animal_id:
            continue
        if status and h["status"] != status:
            continue
        if severity and h["severity"] != severity:
            continue
        if hold_type and h["hold_type"] != hold_type:
            continue
        items.append(h)
    items.sort(key=lambda x: x["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return list_response([serialize_compliance_hold(x) for x in page], total, limit, offset)


@compliance_holds_bp.route("/petcare/compliance-holds/<hold_id>", methods=["GET"])
def get_hold(hold_id):
    require_roles("ShelterManager", "CaseWorker", "Veterinarian")
    h = compliance_holds.get(hold_id)
    if not h:
        raise_error(ERR_HOLD_NOT_FOUND, "Hold not found")
    return success_response(serialize_compliance_hold(h))


@compliance_holds_bp.route("/petcare/compliance-holds/<hold_id>/resolve", methods=["POST"])
def resolve_hold(hold_id):
    user_id, _ = require_roles("ShelterManager")
    h = compliance_holds.get(hold_id)
    if not h:
        raise_error(ERR_HOLD_NOT_FOUND, "Hold not found")
    if h["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE, "Hold must be ACTIVE")
    body = request.get_json(silent=True) or {}
    notes = body.get("resolution_notes")
    if not notes or not isinstance(notes, str):
        raise_error(ERR_INVALID_REQUEST, "resolution_notes is required")

    h["status"] = "RESOLVED"
    h["resolved_by"] = user_id
    h["resolution_notes"] = notes
    h["updated_at"] = now_iso()
    h["version"] += 1

    # Potentially revert animal back to AVAILABLE
    animal = animals.get(h["animal_id"])
    if animal and animal["status"] == "UNAVAILABLE":
        # Check no remaining ACTIVE HIGH/CRITICAL holds
        remaining = any(
            x["animal_id"] == animal["id"] and x["status"] == "ACTIVE"
            and x["severity"] in ("HIGH", "CRITICAL")
            for x in compliance_holds.values()
        )
        if not remaining:
            animal["status"] = "AVAILABLE"
            animal["updated_at"] = now_iso()
            animal["version"] += 1

    return success_response(serialize_compliance_hold(h))
