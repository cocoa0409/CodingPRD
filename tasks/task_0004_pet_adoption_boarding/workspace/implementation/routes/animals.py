from flask import Blueprint, request
from db import shelters, animals, compliance_holds, gen_id, now_iso
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_SHELTER_NOT_FOUND,
    ERR_ANIMAL_NOT_FOUND,
    ERR_VERSION_CONFLICT,
    ERR_INVALID_STATE,
    ERR_VACCINATION_NOT_COMPLIANT,
    ERR_COMPLIANCE_HOLD_ACTIVE,
    ERR_SHELTER_SUSPENDED,
)
from middleware import require_roles, parse_pagination
from response import success_response, list_response
from services.animal_service import (
    serialize_animal,
    vaccination_compliant,
    has_active_high_critical_hold,
)

animals_bp = Blueprint("animals", __name__)

VALID_SPECIES = {"DOG", "CAT", "RABBIT", "BIRD", "OTHER"}
VALID_TEMPERAMENTS = {"CALM", "MODERATE", "ENERGETIC", "AGGRESSIVE"}


@animals_bp.route("/petcare/animals", methods=["POST"])
def create_animal():
    require_roles("CaseWorker")
    body = request.get_json(silent=True) or {}

    shelter_id = body.get("shelter_id")
    name = body.get("name")
    species = body.get("species")
    breed = body.get("breed")
    age_months = body.get("age_months")
    weight_kg = body.get("weight_kg")
    temperament = body.get("temperament")
    special_needs = body.get("special_needs", [])

    if not shelter_id or not isinstance(shelter_id, str):
        raise_error(ERR_INVALID_REQUEST, "shelter_id is required")
    if shelter_id not in shelters:
        raise_error(ERR_SHELTER_NOT_FOUND, "Shelter not found")
    if not name or not isinstance(name, str):
        raise_error(ERR_INVALID_REQUEST, "name is required")
    if species not in VALID_SPECIES:
        raise_error(ERR_INVALID_REQUEST, "species is invalid")
    if not isinstance(breed, str):
        raise_error(ERR_INVALID_REQUEST, "breed is required")
    if not isinstance(age_months, int) or isinstance(age_months, bool) or age_months < 0:
        raise_error(ERR_INVALID_REQUEST, "age_months must be a non-negative integer")
    if not isinstance(weight_kg, (int, float)) or isinstance(weight_kg, bool) or weight_kg <= 0:
        raise_error(ERR_INVALID_REQUEST, "weight_kg must be > 0")
    if temperament not in VALID_TEMPERAMENTS:
        raise_error(ERR_INVALID_REQUEST, "temperament is invalid")
    if not isinstance(special_needs, list):
        raise_error(ERR_INVALID_REQUEST, "special_needs must be an array")

    aid = gen_id()
    ts = now_iso()
    animal = {
        "id": aid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "shelter_id": shelter_id,
        "name": name,
        "species": species,
        "breed": breed,
        "age_months": age_months,
        "weight_kg": weight_kg,
        "temperament": temperament,
        "special_needs": list(special_needs),
        "status": "INTAKE",
    }
    animals[aid] = animal
    return success_response(serialize_animal(animal), status_code=201)


@animals_bp.route("/petcare/animals", methods=["GET"])
def list_animals():
    require_roles("ShelterManager", "CaseWorker", "Veterinarian")
    limit, offset = parse_pagination()
    shelter_id = request.args.get("shelter_id")
    species = request.args.get("species")
    status = request.args.get("status")
    items = []
    for a in animals.values():
        if shelter_id and a["shelter_id"] != shelter_id:
            continue
        if species and a["species"] != species:
            continue
        if status and a["status"] != status:
            continue
        items.append(a)
    items.sort(key=lambda x: x["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return list_response([serialize_animal(x) for x in page], total, limit, offset)


@animals_bp.route("/petcare/animals/<animal_id>", methods=["GET"])
def get_animal(animal_id):
    require_roles("ShelterManager", "CaseWorker", "Veterinarian")
    a = animals.get(animal_id)
    if not a:
        raise_error(ERR_ANIMAL_NOT_FOUND, "Animal not found")
    return success_response(serialize_animal(a))


@animals_bp.route("/petcare/animals/<animal_id>", methods=["PATCH"])
def update_animal(animal_id):
    require_roles("CaseWorker")
    a = animals.get(animal_id)
    if not a:
        raise_error(ERR_ANIMAL_NOT_FOUND, "Animal not found")
    body = request.get_json(silent=True) or {}

    if "version" in body and body["version"] is not None:
        if body["version"] != a["version"]:
            raise_error(ERR_VERSION_CONFLICT, "version mismatch")

    if "name" in body:
        if not isinstance(body["name"], str) or not body["name"]:
            raise_error(ERR_INVALID_REQUEST, "name must be a non-empty string")
        a["name"] = body["name"]
    if "breed" in body:
        if not isinstance(body["breed"], str):
            raise_error(ERR_INVALID_REQUEST, "breed must be a string")
        a["breed"] = body["breed"]
    if "age_months" in body:
        v = body["age_months"]
        if not isinstance(v, int) or isinstance(v, bool) or v < 0:
            raise_error(ERR_INVALID_REQUEST, "age_months must be a non-negative integer")
        a["age_months"] = v
    if "weight_kg" in body:
        v = body["weight_kg"]
        if not isinstance(v, (int, float)) or isinstance(v, bool) or v <= 0:
            raise_error(ERR_INVALID_REQUEST, "weight_kg must be > 0")
        a["weight_kg"] = v
    if "temperament" in body:
        if body["temperament"] not in VALID_TEMPERAMENTS:
            raise_error(ERR_INVALID_REQUEST, "temperament is invalid")
        a["temperament"] = body["temperament"]
    if "special_needs" in body:
        if not isinstance(body["special_needs"], list):
            raise_error(ERR_INVALID_REQUEST, "special_needs must be an array")
        a["special_needs"] = list(body["special_needs"])

    a["updated_at"] = now_iso()
    a["version"] += 1
    return success_response(serialize_animal(a))


@animals_bp.route("/petcare/animals/<animal_id>/make-available", methods=["POST"])
def make_available(animal_id):
    require_roles("CaseWorker")
    a = animals.get(animal_id)
    if not a:
        raise_error(ERR_ANIMAL_NOT_FOUND, "Animal not found")
    shelter = shelters.get(a["shelter_id"])
    if not shelter:
        raise_error(ERR_SHELTER_NOT_FOUND, "Shelter not found")
    if shelter["status"] != "OPEN":
        raise_error(ERR_SHELTER_SUSPENDED, "Shelter is suspended")
    if a["status"] != "INTAKE":
        raise_error(ERR_INVALID_STATE, "Animal must be INTAKE to make available")
    if not vaccination_compliant(a, "adoption"):
        raise_error(ERR_VACCINATION_NOT_COMPLIANT, "Animal is not vaccination-compliant")
    if has_active_high_critical_hold(animal_id):
        raise_error(ERR_COMPLIANCE_HOLD_ACTIVE, "Animal has active HIGH/CRITICAL hold")
    a["status"] = "AVAILABLE"
    a["updated_at"] = now_iso()
    a["version"] += 1
    return success_response(serialize_animal(a))
