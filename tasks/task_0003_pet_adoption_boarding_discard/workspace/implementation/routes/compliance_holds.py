"""Compliance hold endpoints."""

from flask import Blueprint, request
import db
from db import new_id, now_iso
from middleware import require_role, get_pagination
from response import success_object, success_list
from errors import (raise_error, ERR_HOLD_NOT_FOUND, ERR_ANIMAL_NOT_FOUND,
                    ERR_INVALID_STATE, ERR_INVALID_REQUEST)
from services.compliance import (maybe_transition_animal_on_hold,
                                  maybe_revert_animal_on_hold_resolve,
                                  recompute_animal_eligibility,
                                  recompute_shelter_compliance_score)

bp = Blueprint("compliance_holds", __name__)


def serialize_hold(h):
    return {k: v for k, v in h.items()}


@bp.route("/compliance-holds", methods=["POST"])
def create_hold():
    user_id, role = require_role("Veterinarian", "ShelterManager")
    body = request.get_json(force=True, silent=True) or {}

    required = ["animal_id", "hold_type", "reason", "severity"]
    for field in required:
        if field not in body or body[field] is None:
            raise_error(ERR_INVALID_REQUEST, f"Missing required field: {field}")

    animal = db.animals.get(body["animal_id"])
    if not animal:
        raise_error(ERR_ANIMAL_NOT_FOUND, "Animal not found")

    valid_types = ["VACCINATION_OVERDUE", "HEALTH_CONCERN", "BEHAVIOR_INCIDENT", "QUARANTINE"]
    if body["hold_type"] not in valid_types:
        raise_error(ERR_INVALID_REQUEST, f"Invalid hold_type: {body['hold_type']}")

    valid_severity = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    if body["severity"] not in valid_severity:
        raise_error(ERR_INVALID_REQUEST, f"Invalid severity: {body['severity']}")

    ts = now_iso()
    hold = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "animal_id": body["animal_id"],
        "hold_type": body["hold_type"],
        "reason": body["reason"],
        "imposed_by": user_id,
        "resolved_by": None,
        "resolution_notes": None,
        "severity": body["severity"],
        "status": "ACTIVE",
    }
    db.compliance_holds[hold["id"]] = hold

    # Side effects
    maybe_transition_animal_on_hold(body["animal_id"], body["severity"])
    recompute_shelter_compliance_score(animal["shelter_id"])

    return success_object(serialize_hold(hold), 201)


@bp.route("/compliance-holds", methods=["GET"])
def list_holds():
    require_role("ShelterManager", "CaseWorker", "Veterinarian")
    limit, offset = get_pagination()

    items = list(db.compliance_holds.values())
    animal_id = request.args.get("animal_id")
    status = request.args.get("status")
    severity = request.args.get("severity")
    if animal_id:
        items = [h for h in items if h["animal_id"] == animal_id]
    if status:
        items = [h for h in items if h["status"] == status]
    if severity:
        items = [h for h in items if h["severity"] == severity]

    items.sort(key=lambda x: x["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_hold(h) for h in page], total, limit, offset)


@bp.route("/compliance-holds/<holdId>", methods=["GET"])
def get_hold(holdId):
    require_role("ShelterManager", "CaseWorker", "Veterinarian")
    hold = db.compliance_holds.get(holdId)
    if not hold:
        raise_error(ERR_HOLD_NOT_FOUND, "Compliance hold not found")
    return success_object(serialize_hold(hold))


@bp.route("/compliance-holds/<holdId>/resolve", methods=["POST"])
def resolve_hold(holdId):
    user_id, role = require_role("ShelterManager")
    hold = db.compliance_holds.get(holdId)
    if not hold:
        raise_error(ERR_HOLD_NOT_FOUND, "Compliance hold not found")
    if hold["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE, "Hold must be ACTIVE to resolve")

    body = request.get_json(force=True, silent=True) or {}
    resolution_notes = body.get("resolution_notes")
    if not resolution_notes:
        raise_error(ERR_INVALID_REQUEST, "resolution_notes is required")

    hold["resolved_by"] = user_id
    hold["resolution_notes"] = resolution_notes
    hold["status"] = "RESOLVED"
    hold["updated_at"] = now_iso()
    hold["version"] += 1

    # Side effects
    animal = db.animals.get(hold["animal_id"])
    if animal:
        recompute_animal_eligibility(hold["animal_id"])
        maybe_revert_animal_on_hold_resolve(hold["animal_id"])
        recompute_shelter_compliance_score(animal["shelter_id"])

    return success_object(serialize_hold(hold))
