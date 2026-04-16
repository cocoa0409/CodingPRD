"""Adopter endpoints."""

from flask import Blueprint, request
import db
from db import new_id, now_iso
from middleware import require_role, get_pagination
from response import success_object, success_list
from errors import (raise_error, ERR_ADOPTER_NOT_FOUND, ERR_SHELTER_NOT_FOUND,
                    ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_STALE_DATA)

bp = Blueprint("adopters", __name__)


def serialize_adopter(a):
    return {k: v for k, v in a.items()}


@bp.route("/adopters", methods=["POST"])
def create_adopter():
    user_id, role = require_role("CaseWorker")
    body = request.get_json(force=True, silent=True) or {}

    required = ["shelter_id", "full_name", "email", "phone", "home_type", "has_yard", "has_other_pets"]
    for field in required:
        if field not in body or body[field] is None:
            raise_error(ERR_INVALID_REQUEST, f"Missing required field: {field}")

    shelter = db.shelters.get(body["shelter_id"])
    if not shelter:
        raise_error(ERR_SHELTER_NOT_FOUND, "Shelter not found")

    ts = now_iso()
    adopter = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "shelter_id": body["shelter_id"],
        "full_name": body["full_name"],
        "email": body["email"],
        "phone": body["phone"],
        "home_type": body["home_type"],
        "has_yard": body["has_yard"],
        "has_other_pets": body["has_other_pets"],
        "other_pet_species": body.get("other_pet_species", []),
        "adoption_history_count": 0,
        "home_visit_passed": False,
        "status": "ACTIVE",
    }
    db.adopters[adopter["id"]] = adopter
    return success_object(serialize_adopter(adopter), 201)


@bp.route("/adopters", methods=["GET"])
def list_adopters():
    require_role("ShelterManager", "CaseWorker")
    limit, offset = get_pagination()

    items = list(db.adopters.values())
    shelter_id = request.args.get("shelter_id")
    status = request.args.get("status")
    if shelter_id:
        items = [a for a in items if a["shelter_id"] == shelter_id]
    if status:
        items = [a for a in items if a["status"] == status]

    items.sort(key=lambda x: x["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_adopter(a) for a in page], total, limit, offset)


@bp.route("/adopters/<adopterId>", methods=["GET"])
def get_adopter(adopterId):
    require_role("ShelterManager", "CaseWorker")
    adopter = db.adopters.get(adopterId)
    if not adopter:
        raise_error(ERR_ADOPTER_NOT_FOUND, "Adopter not found")
    return success_object(serialize_adopter(adopter))


@bp.route("/adopters/<adopterId>", methods=["PATCH"])
def update_adopter(adopterId):
    user_id, role = require_role("CaseWorker")
    adopter = db.adopters.get(adopterId)
    if not adopter:
        raise_error(ERR_ADOPTER_NOT_FOUND, "Adopter not found")

    body = request.get_json(force=True, silent=True) or {}

    if "version" in body and body["version"] is not None:
        if body["version"] != adopter["version"]:
            raise_error(ERR_STALE_DATA, "Resource has been modified")

    updatable = ["full_name", "email", "phone", "home_type", "has_yard", "has_other_pets", "other_pet_species"]
    for field in updatable:
        if field in body:
            adopter[field] = body[field]

    adopter["updated_at"] = now_iso()
    adopter["version"] += 1
    return success_object(serialize_adopter(adopter))


@bp.route("/adopters/<adopterId>/blacklist", methods=["POST"])
def blacklist_adopter(adopterId):
    user_id, role = require_role("ShelterManager")
    adopter = db.adopters.get(adopterId)
    if not adopter:
        raise_error(ERR_ADOPTER_NOT_FOUND, "Adopter not found")
    if adopter["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE, "Adopter must be ACTIVE to blacklist")

    adopter["status"] = "BLACKLISTED"
    adopter["updated_at"] = now_iso()
    adopter["version"] += 1

    # Withdraw all SUBMITTED or UNDER_REVIEW applications for this adopter
    for app in db.adoption_applications.values():
        if app["adopter_id"] == adopterId and app["status"] in ("SUBMITTED", "UNDER_REVIEW"):
            app["status"] = "WITHDRAWN"
            app["updated_at"] = now_iso()
            app["version"] += 1

    return success_object(serialize_adopter(adopter))
