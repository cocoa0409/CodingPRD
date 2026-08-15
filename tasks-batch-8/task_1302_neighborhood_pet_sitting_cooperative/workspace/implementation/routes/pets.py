"""PetProfile endpoints: create/list/get/deactivate."""

from flask import Blueprint, request

import db
from errors import ApiError, ERR_FORBIDDEN, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from middleware import body, bool_filter, paginate, require_roles
from response import created, ok
from routes.members import get_member_or_404
from serializers import pet_view
from util import base_entity, touch

bp = Blueprint("pets", __name__)

SPECIES = {"DOG", "CAT", "BIRD", "RABBIT", "OTHER"}


def get_pet_or_404(pet_profile_id):
    pet = db.store["pets"].get(pet_profile_id)
    if pet is None:
        raise ApiError(ERR_NOT_FOUND, 404, f"PetProfile {pet_profile_id} does not exist")
    return pet


@bp.post("/coop/members/<member_id>/pet-profiles")
def create_pet(member_id):
    user_id, _ = require_roles("Member")
    member = get_member_or_404(member_id)
    if user_id != member["id"]:
        raise ApiError(
            ERR_FORBIDDEN, 403, "Only the owner member may create their pet profiles"
        )
    data = body()
    pet_name = data.get("pet_name")
    if not isinstance(pet_name, str) or not pet_name.strip():
        raise ApiError(ERR_INVALID_REQUEST, 400, "pet_name is required")
    species = data.get("species")
    if species not in SPECIES:
        raise ApiError(
            ERR_INVALID_REQUEST,
            400,
            "species must be one of DOG, CAT, BIRD, RABBIT, OTHER",
        )
    for field in (
        "routine_notes",
        "medical_notes",
        "emergency_vet_name",
        "emergency_vet_phone",
        "emergency_vet_address",
    ):
        if not isinstance(data.get(field), str):
            raise ApiError(ERR_INVALID_REQUEST, 400, f"{field} is required")
    liability_waiver_accepted = data.get("liability_waiver_accepted")
    if not isinstance(liability_waiver_accepted, bool):
        raise ApiError(
            ERR_INVALID_REQUEST, 400, "liability_waiver_accepted must be a boolean"
        )
    pet = base_entity()
    pet.update(
        {
            "owner_member_id": user_id,
            "pet_name": pet_name,
            "species": species,
            "routine_notes": data["routine_notes"],
            "medical_notes": data["medical_notes"],
            "emergency_vet_name": data["emergency_vet_name"],
            "emergency_vet_phone": data["emergency_vet_phone"],
            "emergency_vet_address": data["emergency_vet_address"],
            "liability_waiver_accepted": liability_waiver_accepted,
            "active": True,
        }
    )
    db.store["pets"][pet["id"]] = pet
    return created(pet_view(pet))


@bp.get("/coop/members/<member_id>/pet-profiles")
def list_pets(member_id):
    require_roles("CoopAdmin", "Member")
    get_member_or_404(member_id)
    items = [p for p in db.store["pets"].values() if p["owner_member_id"] == member_id]
    active = bool_filter(request.args.get("active"))
    if active is not None:
        items = [p for p in items if p["active"] == active]
    return paginate(items, pet_view)


@bp.get("/coop/pet-profiles/<pet_profile_id>")
def get_pet(pet_profile_id):
    require_roles("CoopAdmin", "Member")
    return ok(pet_view(get_pet_or_404(pet_profile_id)))


@bp.post("/coop/pet-profiles/<pet_profile_id>/deactivate")
def deactivate_pet(pet_profile_id):
    user_id, _ = require_roles("Member")
    pet = get_pet_or_404(pet_profile_id)
    if user_id != pet["owner_member_id"]:
        raise ApiError(
            ERR_FORBIDDEN, 403, "Only the owner may deactivate this pet profile"
        )
    pet["active"] = False
    touch(pet)
    return ok(pet_view(pet))
