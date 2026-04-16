from flask import Blueprint, request
from db import adopters, shelters, adoption_applications, home_visits, animals, gen_id, now_iso
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_SHELTER_NOT_FOUND,
    ERR_ADOPTER_NOT_FOUND,
    ERR_VERSION_CONFLICT,
    ERR_INVALID_STATE,
)
from middleware import require_roles, parse_pagination
from response import success_response, list_response
from services.animal_service import serialize_adopter, serialize_application, serialize_home_visit

adopters_bp = Blueprint("adopters", __name__)

VALID_HOME_TYPES = {"HOUSE", "APARTMENT", "FARM", "OTHER"}


@adopters_bp.route("/petcare/adopters", methods=["POST"])
def create_adopter():
    require_roles("CaseWorker")
    body = request.get_json(silent=True) or {}

    shelter_id = body.get("shelter_id")
    full_name = body.get("full_name")
    email = body.get("email")
    phone = body.get("phone")
    home_type = body.get("home_type")
    has_yard = body.get("has_yard")
    has_other_pets = body.get("has_other_pets")
    other_pet_species = body.get("other_pet_species", [])

    if not shelter_id or not isinstance(shelter_id, str):
        raise_error(ERR_INVALID_REQUEST, "shelter_id is required")
    if shelter_id not in shelters:
        raise_error(ERR_SHELTER_NOT_FOUND, "Shelter not found")
    if not full_name or not isinstance(full_name, str):
        raise_error(ERR_INVALID_REQUEST, "full_name is required")
    if not email or not isinstance(email, str):
        raise_error(ERR_INVALID_REQUEST, "email is required")
    if not phone or not isinstance(phone, str):
        raise_error(ERR_INVALID_REQUEST, "phone is required")
    if home_type not in VALID_HOME_TYPES:
        raise_error(ERR_INVALID_REQUEST, "home_type is invalid")
    if not isinstance(has_yard, bool):
        raise_error(ERR_INVALID_REQUEST, "has_yard must be boolean")
    if not isinstance(has_other_pets, bool):
        raise_error(ERR_INVALID_REQUEST, "has_other_pets must be boolean")
    if not isinstance(other_pet_species, list):
        raise_error(ERR_INVALID_REQUEST, "other_pet_species must be an array")

    aid = gen_id()
    ts = now_iso()
    adopter = {
        "id": aid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "shelter_id": shelter_id,
        "full_name": full_name,
        "email": email,
        "phone": phone,
        "home_type": home_type,
        "has_yard": has_yard,
        "has_other_pets": has_other_pets,
        "other_pet_species": list(other_pet_species),
        "status": "ACTIVE",
    }
    adopters[aid] = adopter
    return success_response(serialize_adopter(adopter), status_code=201)


@adopters_bp.route("/petcare/adopters", methods=["GET"])
def list_adopters():
    require_roles("ShelterManager", "CaseWorker")
    limit, offset = parse_pagination()
    shelter_id = request.args.get("shelter_id")
    status = request.args.get("status")
    items = []
    for a in adopters.values():
        if shelter_id and a["shelter_id"] != shelter_id:
            continue
        if status and a["status"] != status:
            continue
        items.append(a)
    items.sort(key=lambda x: x["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return list_response([serialize_adopter(x) for x in page], total, limit, offset)


@adopters_bp.route("/petcare/adopters/<adopter_id>", methods=["GET"])
def get_adopter(adopter_id):
    require_roles("ShelterManager", "CaseWorker")
    a = adopters.get(adopter_id)
    if not a:
        raise_error(ERR_ADOPTER_NOT_FOUND, "Adopter not found")
    return success_response(serialize_adopter(a))


@adopters_bp.route("/petcare/adopters/<adopter_id>", methods=["PATCH"])
def update_adopter(adopter_id):
    require_roles("CaseWorker")
    a = adopters.get(adopter_id)
    if not a:
        raise_error(ERR_ADOPTER_NOT_FOUND, "Adopter not found")
    body = request.get_json(silent=True) or {}

    if "version" in body and body["version"] is not None:
        if body["version"] != a["version"]:
            raise_error(ERR_VERSION_CONFLICT, "version mismatch")

    if "full_name" in body:
        if not isinstance(body["full_name"], str) or not body["full_name"]:
            raise_error(ERR_INVALID_REQUEST, "full_name must be non-empty string")
        a["full_name"] = body["full_name"]
    if "email" in body:
        if not isinstance(body["email"], str) or not body["email"]:
            raise_error(ERR_INVALID_REQUEST, "email must be non-empty string")
        a["email"] = body["email"]
    if "phone" in body:
        if not isinstance(body["phone"], str):
            raise_error(ERR_INVALID_REQUEST, "phone must be string")
        a["phone"] = body["phone"]
    if "home_type" in body:
        if body["home_type"] not in VALID_HOME_TYPES:
            raise_error(ERR_INVALID_REQUEST, "home_type is invalid")
        a["home_type"] = body["home_type"]
    if "has_yard" in body:
        if not isinstance(body["has_yard"], bool):
            raise_error(ERR_INVALID_REQUEST, "has_yard must be boolean")
        a["has_yard"] = body["has_yard"]
    if "has_other_pets" in body:
        if not isinstance(body["has_other_pets"], bool):
            raise_error(ERR_INVALID_REQUEST, "has_other_pets must be boolean")
        a["has_other_pets"] = body["has_other_pets"]
    if "other_pet_species" in body:
        if not isinstance(body["other_pet_species"], list):
            raise_error(ERR_INVALID_REQUEST, "other_pet_species must be an array")
        a["other_pet_species"] = list(body["other_pet_species"])

    a["updated_at"] = now_iso()
    a["version"] += 1
    return success_response(serialize_adopter(a))


@adopters_bp.route("/petcare/adopters/<adopter_id>/blacklist", methods=["POST"])
def blacklist_adopter(adopter_id):
    require_roles("ShelterManager")
    a = adopters.get(adopter_id)
    if not a:
        raise_error(ERR_ADOPTER_NOT_FOUND, "Adopter not found")
    body = request.get_json(silent=True) or {}
    reason = body.get("reason")
    if not reason or not isinstance(reason, str):
        raise_error(ERR_INVALID_REQUEST, "reason is required")
    if a["status"] == "BLACKLISTED":
        raise_error(ERR_INVALID_STATE, "Adopter is already BLACKLISTED")
    a["status"] = "BLACKLISTED"
    a["blacklist_reason"] = reason
    a["updated_at"] = now_iso()
    a["version"] += 1

    # Cascade: withdraw all non-terminal applications by this adopter
    non_terminal = {"SUBMITTED", "UNDER_REVIEW", "HOME_VISIT_REQUIRED",
                     "HOME_VISIT_SCHEDULED", "REVIEWED"}
    for app in list(adoption_applications.values()):
        if app["adopter_id"] != adopter_id:
            continue
        if app["status"] not in non_terminal:
            continue
        # Cancel linked home visit if SCHEDULED
        hv_id = app.get("home_visit_id")
        if hv_id:
            hv = home_visits.get(hv_id)
            if hv and hv["status"] == "SCHEDULED":
                hv["status"] = "CANCELLED"
                hv["updated_at"] = now_iso()
                hv["version"] += 1
        # Revert animal from ADOPTION_PENDING if applicable
        animal = animals.get(app["animal_id"])
        if animal and animal["status"] == "ADOPTION_PENDING":
            animal["status"] = "AVAILABLE"
            animal["updated_at"] = now_iso()
            animal["version"] += 1
        app["status"] = "WITHDRAWN"
        app["home_visit_id"] = None
        app["updated_at"] = now_iso()
        app["version"] += 1

    return success_response(serialize_adopter(a))
