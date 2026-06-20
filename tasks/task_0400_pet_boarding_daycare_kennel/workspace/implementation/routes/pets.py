"""Pet, temperament review, and vaccination endpoints (PRD §3.2–§3.4)."""
from flask import Blueprint, g

import errors
import response
from db import db, new_id, now_iso
from middleware import require_roles
from services import serialize
from services.common import (stamp_create, touch, get_body, require_fields,
                             require_enum, parse_date)
from services.query import paginate_params, sort_by_created, apply_page, owner_guard
from services.pet import size_class_for_weight, recompute_vaccination_status
from routes.owners import get_owner_or_404

bp = Blueprint("pets", __name__)

SPECIES = {"DOG", "CAT"}
TEMPERAMENTS = {"CALM", "PLAYFUL", "REACTIVE"}
VACCINES = {"RABIES", "DHPP", "BORDETELLA", "FVRCP"}
DECISIONS = {"CLEAR", "FLAG"}


def get_pet_or_404(pid):
    p = db.pets.get(pid)
    if p is None:
        raise errors.err_not_found()
    return p


def _pet_owner_guard(pet):
    if g.role == "Owner" and g.user_id != pet["owner_id"]:
        raise errors.err_not_resource_owner()


@bp.route("/owners/<oid>/pets", methods=["POST"])
@require_roles("FacilityManager", "FacilityStaff", "Owner")
def create_pet(oid):
    owner = get_owner_or_404(oid)
    owner_guard(oid)
    body = get_body()
    require_fields(body, ["name", "species", "weight_kg"])

    name = body["name"]
    if not isinstance(name, str) or name == "":
        raise errors.err_invalid_request("name must be a non-empty string.")
    species = body["species"]
    require_enum(species, SPECIES, "species")
    weight_kg = body["weight_kg"]
    if isinstance(weight_kg, bool) or not isinstance(weight_kg, (int, float)):
        raise errors.err_invalid_request("weight_kg must be a number.")
    if weight_kg <= 0:
        raise errors.err_invalid_request("weight_kg must be > 0.")
    temperament = body.get("temperament", "CALM")
    require_enum(temperament, TEMPERAMENTS, "temperament")

    pet = {
        "owner_id": oid,
        "facility_id": owner["facility_id"],
        "name": name,
        "species": species,
        "weight_kg": weight_kg,
        "temperament": temperament,
        "size_class": size_class_for_weight(weight_kg),
        "vaccination_status": "MISSING",
        "temperament_clearance": "UNREVIEWED",
    }
    stamp_create(pet)
    db.pets[pet["id"]] = pet
    return response.success(serialize.pet(pet), status=201)


@bp.route("/pets/<pid>", methods=["GET"])
@require_roles("FacilityManager", "FacilityStaff", "Owner")
def get_pet(pid):
    p = get_pet_or_404(pid)
    _pet_owner_guard(p)
    return response.success(serialize.pet(p), status=200)


@bp.route("/owners/<oid>/pets", methods=["GET"])
@require_roles("FacilityManager", "FacilityStaff", "Owner")
def list_pets(oid):
    get_owner_or_404(oid)
    owner_guard(oid)
    limit, offset = paginate_params()
    items = [p for p in db.pets.values() if p["owner_id"] == oid]
    items = sort_by_created(items)
    page, total = apply_page(items, limit, offset)
    return response.list_success([serialize.pet(p) for p in page], limit, offset, total)


@bp.route("/pets/<pid>/review", methods=["POST"])
@require_roles("FacilityManager", "FacilityStaff")
def review_pet(pid):
    p = get_pet_or_404(pid)
    body = get_body()
    require_fields(body, ["decision"])
    decision = body["decision"]
    require_enum(decision, DECISIONS, "decision")

    if decision == "CLEAR":
        p["temperament_clearance"] = "CLEARED"
    else:
        p["temperament_clearance"] = "FLAGGED"
    touch(p)
    return response.success(serialize.pet(p), status=200)


@bp.route("/pets/<pid>/vaccinations", methods=["POST"])
@require_roles("FacilityManager", "FacilityStaff", "Owner")
def add_vaccination(pid):
    p = get_pet_or_404(pid)
    _pet_owner_guard(p)
    body = get_body()
    require_fields(body, ["vaccine", "administered_on", "expires_on"])
    vaccine = body["vaccine"]
    require_enum(vaccine, VACCINES, "vaccine")
    administered_on = body["administered_on"]
    expires_on = body["expires_on"]
    parse_date(administered_on)
    parse_date(expires_on)

    # Supersede prior non-superseded record for the same vaccine.
    for rec in db.vaccination_records.values():
        if rec["pet_id"] == pid and rec["vaccine"] == vaccine and not rec.get("superseded"):
            rec["superseded"] = True

    rec = {
        "pet_id": pid,
        "vaccine": vaccine,
        "administered_on": administered_on,
        "expires_on": expires_on,
        "superseded": False,
    }
    # VaccinationRecord: id + created_at only (no updated_at/version).
    rec["id"] = new_id()
    rec["created_at"] = now_iso()
    db.vaccination_records[rec["id"]] = rec

    recompute_vaccination_status(p)
    return response.success(serialize.vaccination(rec), status=201)


@bp.route("/pets/<pid>/vaccinations", methods=["GET"])
@require_roles("FacilityManager", "FacilityStaff", "Owner")
def list_vaccinations(pid):
    p = get_pet_or_404(pid)
    _pet_owner_guard(p)
    limit, offset = paginate_params()
    items = [r for r in db.vaccination_records.values() if r["pet_id"] == pid]
    items = sort_by_created(items)
    page, total = apply_page(items, limit, offset)
    return response.list_success([serialize.vaccination(r) for r in page],
                                 limit, offset, total)
