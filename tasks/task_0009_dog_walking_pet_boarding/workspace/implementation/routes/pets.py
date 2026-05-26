"""Pet routes."""
from __future__ import annotations

from flask import Blueprint, request

import db
import response
from errors import ApiError, ERR_INVALID_REQUEST
from middleware import require_auth
from services.common import (
    get_json_body,
    new_common_fields,
    optional_str,
    paginate,
    parse_pagination,
    require_enum,
    require_number,
    require_str,
    sorted_by_created_at,
)
from services.lookup import fk_owner, get_pet_or_404

bp = Blueprint("pets", __name__)


_SPECIES = {"DOG", "CAT"}


def pet_to_dict(p: dict) -> dict:
    return {
        "id": p["id"],
        "owner_id": p["owner_id"],
        "name": p["name"],
        "species": p["species"],
        "weight_kg": p["weight_kg"],
        "medical_notes": p["medical_notes"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


@bp.post("/api/v1/pets")
@require_auth(roles=["Owner"])
def create_pet():
    body = get_json_body()
    owner_id = require_str(body, "owner_id")
    name = require_str(body, "name")
    species = require_enum(body, "species", _SPECIES)
    weight_kg = require_number(body, "weight_kg")
    medical_notes = optional_str(body, "medical_notes", "")

    if weight_kg <= 0:
        raise ApiError(ERR_INVALID_REQUEST, "weight_kg must be > 0.")

    fk_owner(owner_id)

    with db.lock:
        pet = {
            **new_common_fields(),
            "owner_id": owner_id,
            "name": name,
            "species": species,
            "weight_kg": weight_kg,
            "medical_notes": medical_notes,
        }
        db.pets[pet["id"]] = pet
    return response.ok(pet_to_dict(pet), status=201)


@bp.get("/api/v1/pets/<pid>")
@require_auth(roles=["Owner", "Sitter", "PlatformAdmin", "ClaimsAdjuster"])
def get_pet(pid: str):
    p = get_pet_or_404(pid)
    return response.ok(pet_to_dict(p))


@bp.get("/api/v1/pets")
@require_auth(roles=["Owner", "Sitter", "PlatformAdmin", "ClaimsAdjuster"])
def list_pets():
    limit, offset = parse_pagination()
    owner_id = request.args.get("owner_id")

    items = list(db.pets.values())
    if owner_id is not None:
        items = [p for p in items if p["owner_id"] == owner_id]
    items = sorted_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return response.list_ok([pet_to_dict(p) for p in page], limit, offset, total)
