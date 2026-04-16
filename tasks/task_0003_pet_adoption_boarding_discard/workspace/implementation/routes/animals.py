"""Animal endpoints."""

from flask import Blueprint, request
import db
from db import new_id, now_iso
from middleware import require_role, get_pagination
from response import success_object, success_list
from errors import (raise_error, ERR_ANIMAL_NOT_FOUND, ERR_SHELTER_NOT_FOUND,
                    ERR_INVALID_STATE, ERR_VACCINATION_NOT_COMPLIANT,
                    ERR_COMPLIANCE_HOLD_ACTIVE, ERR_INVALID_REQUEST, ERR_STALE_DATA)
from services.vaccination import check_vaccination_compliant, update_animal_vaccination_compliant
from services.compliance import (has_active_high_critical_hold, recompute_animal_eligibility,
                                  recompute_boarding_compatible_tags, recompute_shelter_compliance_score)

bp = Blueprint("animals", __name__)


def serialize_animal(a):
    return {k: v for k, v in a.items()}


@bp.route("/animals", methods=["POST"])
def create_animal():
    user_id, role = require_role("CaseWorker")
    body = request.get_json(force=True, silent=True) or {}

    required = ["shelter_id", "name", "species", "breed", "age_months", "weight_kg", "temperament"]
    for field in required:
        if field not in body or body[field] is None:
            raise_error(ERR_INVALID_REQUEST, f"Missing required field: {field}")

    shelter = db.shelters.get(body["shelter_id"])
    if not shelter:
        raise_error(ERR_SHELTER_NOT_FOUND, "Shelter not found")

    valid_species = ["DOG", "CAT", "RABBIT", "BIRD", "OTHER"]
    if body["species"] not in valid_species:
        raise_error(ERR_INVALID_REQUEST, f"Invalid species: {body['species']}")

    valid_temp = ["CALM", "MODERATE", "ENERGETIC", "AGGRESSIVE"]
    if body["temperament"] not in valid_temp:
        raise_error(ERR_INVALID_REQUEST, f"Invalid temperament: {body['temperament']}")

    ts = now_iso()
    animal = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "shelter_id": body["shelter_id"],
        "name": body["name"],
        "species": body["species"],
        "breed": body["breed"],
        "age_months": body["age_months"],
        "weight_kg": body["weight_kg"],
        "temperament": body["temperament"],
        "special_needs": body.get("special_needs", []),
        "vaccination_compliant": False,
        "adoption_eligible": False,
        "boarding_compatible_tags": [],
        "status": "INTAKE",
    }
    db.animals[animal["id"]] = animal
    update_animal_vaccination_compliant(animal["id"])
    recompute_boarding_compatible_tags(animal["id"])
    recompute_shelter_compliance_score(body["shelter_id"])
    return success_object(serialize_animal(animal), 201)


@bp.route("/animals", methods=["GET"])
def list_animals():
    require_role("ShelterManager", "CaseWorker", "Veterinarian")
    limit, offset = get_pagination()

    items = list(db.animals.values())
    # Apply filters
    shelter_id = request.args.get("shelter_id")
    species = request.args.get("species")
    status = request.args.get("status")
    if shelter_id:
        items = [a for a in items if a["shelter_id"] == shelter_id]
    if species:
        items = [a for a in items if a["species"] == species]
    if status:
        items = [a for a in items if a["status"] == status]

    items.sort(key=lambda x: x["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_animal(a) for a in page], total, limit, offset)


@bp.route("/animals/<animalId>", methods=["GET"])
def get_animal(animalId):
    require_role("ShelterManager", "CaseWorker", "Veterinarian")
    animal = db.animals.get(animalId)
    if not animal:
        raise_error(ERR_ANIMAL_NOT_FOUND, "Animal not found")
    return success_object(serialize_animal(animal))


@bp.route("/animals/<animalId>", methods=["PATCH"])
def update_animal(animalId):
    user_id, role = require_role("CaseWorker")
    animal = db.animals.get(animalId)
    if not animal:
        raise_error(ERR_ANIMAL_NOT_FOUND, "Animal not found")

    body = request.get_json(force=True, silent=True) or {}

    # Optimistic concurrency
    if "version" in body and body["version"] is not None:
        if body["version"] != animal["version"]:
            raise_error(ERR_STALE_DATA, "Resource has been modified")

    updatable = ["name", "breed", "age_months", "weight_kg", "temperament", "special_needs"]
    for field in updatable:
        if field in body:
            animal[field] = body[field]

    animal["updated_at"] = now_iso()
    animal["version"] += 1
    recompute_boarding_compatible_tags(animalId)
    recompute_animal_eligibility(animalId)
    return success_object(serialize_animal(animal))


@bp.route("/animals/<animalId>/make-available", methods=["POST"])
def make_available(animalId):
    user_id, role = require_role("CaseWorker")
    animal = db.animals.get(animalId)
    if not animal:
        raise_error(ERR_ANIMAL_NOT_FOUND, "Animal not found")
    if animal["status"] != "INTAKE":
        raise_error(ERR_INVALID_STATE, "Animal must be in INTAKE status")

    if not animal.get("vaccination_compliant", False):
        raise_error(ERR_VACCINATION_NOT_COMPLIANT, "Animal does not have all required vaccinations up-to-date")

    if has_active_high_critical_hold(animalId):
        raise_error(ERR_COMPLIANCE_HOLD_ACTIVE, "Animal has an active HIGH or CRITICAL compliance hold")

    animal["status"] = "AVAILABLE"
    animal["updated_at"] = now_iso()
    animal["version"] += 1
    recompute_animal_eligibility(animalId)
    recompute_boarding_compatible_tags(animalId)
    recompute_shelter_compliance_score(animal["shelter_id"])
    return success_object(serialize_animal(animal))
