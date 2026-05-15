"""Pet endpoints."""
from __future__ import annotations

from flask import Blueprint, request

from app.auth import assert_customer_owns, require_role
from app.calculations import compute_life_stage
from app.errors import api_error
from app.pagination import paginate, parse_pagination, sort_by_created_at
from app.response import success_array, success_object
from app.store import store
from app.utils import is_int, is_nonempty_str, is_number, logical_now_iso, new_id, parse_iso_date


bp = Blueprint("pets", __name__)


VALID_SPECIES = {"DOG", "CAT"}
VALID_ACTIVITY = {"LOW", "MODERATE", "HIGH"}
VALID_HEALTH = {"KIDNEY", "DIABETES", "DENTAL"}


def _validate_string_array(value, field_name):
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        raise api_error("ERR_INVALID_REQUEST", f"{field_name} must be array of strings")
    return list(value)


def _validate_health(value):
    arr = _validate_string_array(value, "health_conditions")
    for token in arr:
        if token not in VALID_HEALTH:
            raise api_error("ERR_INVALID_REQUEST", f"Invalid health_condition: {token}")
    return arr


def _ensure_customer_exists_and_owned(customer_id, user_id, role):
    cust = store.customers.get(customer_id)
    if not cust:
        raise api_error("ERR_CUSTOMER_NOT_FOUND", "Customer not found")
    assert_customer_owns(customer_id, user_id, role)
    return cust


def _ensure_pet_under_customer(customer_id, pet_id, user_id, role):
    cust = _ensure_customer_exists_and_owned(customer_id, user_id, role)
    pet = store.pets.get(pet_id)
    if not pet or pet.get("customer_id") != customer_id:
        raise api_error("ERR_PET_NOT_FOUND", "Pet not found")
    return cust, pet


@bp.route("/customers/<customer_id>/pets", methods=["POST"])
@require_role("Customer")
def create_pet(customer_id, user_id: str, role: str):
    _ensure_customer_exists_and_owned(customer_id, user_id, role)
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        raise api_error("ERR_INVALID_REQUEST", "Body must be JSON object")

    name = body.get("name")
    species = body.get("species")
    breed = body.get("breed")
    birthdate = body.get("birthdate")
    weight_kg = body.get("weight_kg")
    activity_level = body.get("activity_level")

    if not is_nonempty_str(name):
        raise api_error("ERR_INVALID_REQUEST", "name is required")
    if species not in VALID_SPECIES:
        raise api_error("ERR_INVALID_REQUEST", "species must be DOG or CAT")
    if not is_nonempty_str(breed):
        raise api_error("ERR_INVALID_REQUEST", "breed is required")
    if parse_iso_date(birthdate) is None:
        raise api_error("ERR_INVALID_REQUEST", "birthdate must be ISO date YYYY-MM-DD")
    if not is_number(weight_kg) or float(weight_kg) <= 0 or float(weight_kg) > 100:
        raise api_error("ERR_INVALID_REQUEST", "weight_kg must be in (0, 100]")
    if activity_level not in VALID_ACTIVITY:
        raise api_error("ERR_INVALID_REQUEST", "activity_level must be LOW|MODERATE|HIGH")

    allergies = _validate_string_array(body.get("allergies"), "allergies")
    intolerances = _validate_string_array(body.get("intolerances"), "intolerances")
    preferences = _validate_string_array(body.get("dietary_preferences"), "dietary_preferences")
    aversions = _validate_string_array(body.get("dietary_aversions"), "dietary_aversions")
    health = _validate_health(body.get("health_conditions"))

    pet_id = new_id()
    now = logical_now_iso()
    pet = {
        "id": pet_id,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "customer_id": customer_id,
        "name": name,
        "species": species,
        "breed": breed,
        "birthdate": birthdate,
        "weight_kg": float(weight_kg),
        "activity_level": activity_level,
        "allergies": allergies,
        "intolerances": intolerances,
        "dietary_preferences": preferences,
        "dietary_aversions": aversions,
        "health_conditions": health,
        "life_stage": compute_life_stage(species, birthdate),
        "photo_gallery": [],
        "status": "ACTIVE",
        "adjustment_history": [],
    }
    store.pets[pet_id] = pet
    return success_object(pet, status=201)


@bp.route("/customers/<customer_id>/pets", methods=["GET"])
@require_role("Customer", "AdminOps")
def list_pets(customer_id, user_id: str, role: str):
    _ensure_customer_exists_and_owned(customer_id, user_id, role)
    limit, offset = parse_pagination()
    pets = [p for p in store.pets.values() if p.get("customer_id") == customer_id]
    pets = sort_by_created_at(pets)
    page, total = paginate(pets, limit, offset)
    return success_array(page, limit, offset, total)


@bp.route("/customers/<customer_id>/pets/<pet_id>", methods=["GET"])
@require_role("Customer", "AdminOps")
def get_pet(customer_id, pet_id, user_id: str, role: str):
    _, pet = _ensure_pet_under_customer(customer_id, pet_id, user_id, role)
    return success_object(pet)


@bp.route("/customers/<customer_id>/pets/<pet_id>", methods=["PATCH"])
@require_role("Customer")
def update_pet(customer_id, pet_id, user_id: str, role: str):
    _, pet = _ensure_pet_under_customer(customer_id, pet_id, user_id, role)
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        raise api_error("ERR_INVALID_REQUEST", "Body must be JSON object")
    if "birthdate" in body:
        raise api_error("ERR_INVALID_REQUEST", "birthdate is immutable")

    if "weight_kg" in body:
        w = body["weight_kg"]
        if not is_number(w) or float(w) <= 0 or float(w) > 100:
            raise api_error("ERR_INVALID_REQUEST", "weight_kg must be in (0, 100]")
    if "activity_level" in body and body["activity_level"] not in VALID_ACTIVITY:
        raise api_error("ERR_INVALID_REQUEST", "activity_level invalid")
    for f in ("allergies", "intolerances", "dietary_preferences", "dietary_aversions"):
        if f in body:
            _validate_string_array(body[f], f)
    if "health_conditions" in body:
        _validate_health(body["health_conditions"])

    if "version" in body:
        if not is_int(body["version"]):
            raise api_error("ERR_INVALID_REQUEST", "version must be integer")
        if body["version"] != pet.get("version"):
            raise api_error("ERR_VERSION_CONFLICT", "version mismatch")

    for f in (
        "weight_kg",
        "activity_level",
        "allergies",
        "intolerances",
        "dietary_preferences",
        "dietary_aversions",
        "health_conditions",
    ):
        if f in body:
            pet[f] = body[f] if f != "weight_kg" else float(body[f])
    # Recompute life_stage in case clock moved or new species was set (species immutable here)
    pet["life_stage"] = compute_life_stage(pet["species"], pet["birthdate"])
    pet["updated_at"] = logical_now_iso()
    pet["version"] = pet.get("version", 1) + 1
    return success_object(pet)


@bp.route("/customers/<customer_id>/pets/<pet_id>/photos", methods=["POST"])
@require_role("Customer")
def add_photo(customer_id, pet_id, user_id: str, role: str):
    _, pet = _ensure_pet_under_customer(customer_id, pet_id, user_id, role)
    body = request.get_json(silent=True) or {}
    url = body.get("url") if isinstance(body, dict) else None
    if not is_nonempty_str(url):
        raise api_error("ERR_INVALID_REQUEST", "url is required")
    now = logical_now_iso()
    pet["photo_gallery"].append({"photo_id": new_id(), "url": url, "uploaded_at": now})
    pet["updated_at"] = now
    pet["version"] = pet.get("version", 1) + 1
    return success_object(pet, status=201)
