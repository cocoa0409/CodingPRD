"""Pet routes (PRD §3.2)."""
from __future__ import annotations

from datetime import date

from flask import Blueprint, g, request

import db
from clock import today_utc_date
from errors import err
from middleware import authenticate, require_roles
from response import error_response, success_array, success_object
from services.common import bump, init_full
from validators import (
    parse_date,
    require_int,
    require_str,
    validate_pagination,
)

bp = Blueprint("pets", __name__)


@bp.before_request
def _auth():
    authenticate()


@bp.post("/pets")
def create_pet():
    require_roles("OwnerService", "PlatformAdmin", "TriageNurse")
    payload = request.get_json(silent=True) or {}
    owner_id = payload.get("owner_id")
    if not isinstance(owner_id, str):
        raise err("ERR_VALIDATION_FAILED", "owner_id is required")
    name = require_str(payload, "name", min_len=1, max_len=60)
    species = payload.get("species")
    if species not in {"DOG", "CAT", "RABBIT", "BIRD", "OTHER"}:
        raise err("ERR_VALIDATION_FAILED", "species must be one of DOG/CAT/RABBIT/BIRD/OTHER")
    bd_str = payload.get("birth_date")
    if not isinstance(bd_str, str):
        raise err("ERR_VALIDATION_FAILED", "birth_date is required")
    bd = parse_date(bd_str)
    if bd > today_utc_date():
        raise err("ERR_VALIDATION_FAILED", "birth_date must be <= today")
    weight = payload.get("weight_kg")
    if isinstance(weight, bool) or not isinstance(weight, (int, float)):
        raise err("ERR_VALIDATION_FAILED", "weight_kg must be a number")
    weight_f = float(weight)
    if weight_f < 0.05 or weight_f > 200:
        raise err("ERR_VALIDATION_FAILED", "weight_kg out of range [0.05, 200]")
    # Up to 2 decimal places.
    if isinstance(weight, float):
        if round(weight_f * 100) - (weight_f * 100) > 1e-9:
            # Allow up to 2 decimal places by rejecting more precise inputs.
            # We use a tolerant check.
            cents = round(weight_f * 100)
            if abs(weight_f * 100 - cents) > 1e-6:
                raise err("ERR_VALIDATION_FAILED", "weight_kg must have at most 2 decimal places")
    with db.GLOBAL_LOCK:
        if owner_id not in db.owners:
            raise err("ERR_REFERENCE_NOT_FOUND", f"owner_id {owner_id} not found")
        pet = {
            "owner_id": owner_id,
            "name": name,
            "species": species,
            "birth_date": bd_str,
            "weight_kg": weight_f,
            "medical_history": [],
            "archived": False,
        }
        init_full(pet)
        db.pets[pet["id"]] = pet
        return success_object(_pet_view(pet), status=201)


@bp.get("/pets/<pet_id>")
def get_pet(pet_id):
    require_roles(
        "OwnerService", "TriageNurse", "DraftingVet", "ReviewingVet",
        "Pharmacist", "Cashier", "PlatformAdmin",
    )
    with db.GLOBAL_LOCK:
        p = db.pets.get(pet_id)
        if not p:
            raise err("ERR_NOT_FOUND", f"Pet {pet_id} not found")
        return success_object(_pet_view(p))


@bp.patch("/pets/<pet_id>")
def update_pet(pet_id):
    require_roles("TriageNurse", "DraftingVet", "OwnerService")
    payload = request.get_json(silent=True) or {}
    with db.GLOBAL_LOCK:
        p = db.pets.get(pet_id)
        if not p:
            raise err("ERR_NOT_FOUND", f"Pet {pet_id} not found")
        # OCC check (optional)
        if "version" in payload:
            v = payload.get("version")
            if not isinstance(v, int) or v != p.get("version"):
                raise err("ERR_STALE_VERSION", "version mismatch")
        if "weight_kg" in payload:
            w = payload["weight_kg"]
            if isinstance(w, bool) or not isinstance(w, (int, float)):
                raise err("ERR_VALIDATION_FAILED", "weight_kg must be a number")
            wf = float(w)
            if wf < 0.05 or wf > 200:
                raise err("ERR_VALIDATION_FAILED", "weight_kg out of range")
            p["weight_kg"] = wf
        if "name" in payload:
            n = payload["name"]
            if not isinstance(n, str) or not (1 <= len(n) <= 60):
                raise err("ERR_VALIDATION_FAILED", "name out of range")
            p["name"] = n
        bump(p)
        return success_object(_pet_view(p))


@bp.delete("/pets/<pet_id>")
def archive_pet(pet_id):
    require_roles("PlatformAdmin")
    with db.GLOBAL_LOCK:
        p = db.pets.get(pet_id)
        if not p:
            raise err("ERR_NOT_FOUND", f"Pet {pet_id} not found")
        p["archived"] = True
        bump(p)
        return success_object(_pet_view(p))


@bp.get("/pets/<pet_id>/visits")
def list_pet_visits(pet_id):
    require_roles("OwnerService", "TriageNurse", "DraftingVet", "PlatformAdmin")
    limit, offset = validate_pagination(request.args)
    with db.GLOBAL_LOCK:
        p = db.pets.get(pet_id)
        if not p:
            raise err("ERR_NOT_FOUND", f"Pet {pet_id} not found")
        from routes.visits import visit_view  # avoid circular at import
        all_visits = [v for v in db.visits.values() if v.get("pet_id") == pet_id]
        # Newest first per PRD §3.2.
        all_visits.sort(key=lambda v: v.get("created_at", ""), reverse=True)
        total = len(all_visits)
        page = all_visits[offset:offset + limit]
        return success_array(
            [visit_view(v) for v in page],
            limit=limit, offset=offset, total_count=total,
        )


def _pet_view(p):
    return {
        "id": p["id"],
        "owner_id": p["owner_id"],
        "name": p["name"],
        "species": p["species"],
        "birth_date": p["birth_date"],
        "weight_kg": p["weight_kg"],
        "medical_history": list(p.get("medical_history", [])),
        "archived": bool(p.get("archived", False)),
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def pet_view(p):
    return _pet_view(p)
