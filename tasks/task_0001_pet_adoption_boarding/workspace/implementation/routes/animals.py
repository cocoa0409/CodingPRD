"""Animal, vaccination, and compliance routes."""

from flask import Blueprint, request

from db import store, new_id, now_dt, lock
from middleware import auth_required
from response import success_object, success_array
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_VERSION_CONFLICT,
    ERR_ANIMAL_NOT_FOUND,
)
from services.validation import (
    get_json_body, require_field, require_enum, pagination,
    get_shelter_or_404, get_animal_or_404, parse_required_dt,
)
from services.serializers import (
    serialize_animal, serialize_vaccination, serialize_compliance,
)

bp = Blueprint("animals", __name__)

SPECIES = {"DOG", "CAT", "RABBIT", "OTHER"}
SPECIAL_CARE = {"NONE", "MEDICAL", "BEHAVIORAL"}
VACCINE_TYPES = {"RABIES", "DISTEMPER", "PARVO", "BORDETELLA", "FELV"}


@bp.route("/shelters/<sid>/animals", methods=["POST"])
@auth_required(allowed_roles={"ShelterAdmin"})
def create_animal(sid):
    get_shelter_or_404(sid)
    body = get_json_body(required=True)
    name = require_field(body, "name", types=str)
    species = require_enum(body, "species", SPECIES)
    age = require_field(body, "age_months", types=int)
    if isinstance(age, bool) or age < 0:
        raise_err(ERR_INVALID_REQUEST, "age_months must be non-negative integer")
    tags = body.get("temperament_tags", [])
    if not isinstance(tags, list) or any(not isinstance(t, str) for t in tags):
        raise_err(ERR_INVALID_REQUEST, "temperament_tags must be a list of strings")
    fee_override = body.get("adoption_fee_override")
    if fee_override is not None:
        if isinstance(fee_override, bool) or not isinstance(fee_override, int) or fee_override < 0:
            raise_err(ERR_INVALID_REQUEST, "adoption_fee_override must be non-negative integer or null")
    special_care = body.get("special_care_level", "NONE")
    if special_care not in SPECIAL_CARE:
        raise_err(ERR_INVALID_REQUEST, "Invalid special_care_level")
    with lock:
        aid = new_id()
        now = now_dt()
        rec = {
            "id": aid,
            "shelter_id": sid,
            "name": name,
            "species": species,
            "age_months": age,
            "temperament_tags": list(tags),
            "adoption_fee_override": fee_override,
            "special_care_level": special_care,
            "intake_date": now,
            "status": "AVAILABLE",
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        store.animals[aid] = rec
    return success_object(serialize_animal(rec), status_code=201)


@bp.route("/shelters/<sid>/animals", methods=["GET"])
@auth_required(allowed_roles={"Any"})
def list_animals(sid):
    get_shelter_or_404(sid)
    limit, offset = pagination()
    status_f = request.args.get("status")
    species_f = request.args.get("species")
    animals = [a for a in store.animals.values() if a["shelter_id"] == sid]
    if status_f:
        animals = [a for a in animals if a["status"] == status_f]
    if species_f:
        animals = [a for a in animals if a["species"] == species_f]
    animals.sort(key=lambda r: r["created_at"])
    total = len(animals)
    page = animals[offset: offset + limit]
    return success_array([serialize_animal(a) for a in page], limit, offset, total)


@bp.route("/shelters/<sid>/animals/<aid>", methods=["GET"])
@auth_required(allowed_roles={"Any"})
def get_animal(sid, aid):
    get_shelter_or_404(sid)
    animal = get_animal_or_404(aid)
    if animal["shelter_id"] != sid:
        raise_err(ERR_ANIMAL_NOT_FOUND, "Animal does not belong to this shelter")
    return success_object(serialize_animal(animal))


@bp.route("/shelters/<sid>/animals/<aid>", methods=["PATCH"])
@auth_required(allowed_roles={"ShelterAdmin"})
def patch_animal(sid, aid):
    get_shelter_or_404(sid)
    animal = get_animal_or_404(aid)
    if animal["shelter_id"] != sid:
        raise_err(ERR_ANIMAL_NOT_FOUND, "Animal does not belong to this shelter")
    body = get_json_body(required=True)
    # OCC
    if "version" in body and body["version"] is not None:
        if body["version"] != animal["version"]:
            raise_err(ERR_VERSION_CONFLICT, "Stale version")
    # Allowed fields
    with lock:
        if "name" in body:
            if not isinstance(body["name"], str):
                raise_err(ERR_INVALID_REQUEST, "name must be a string")
            animal["name"] = body["name"]
        if "temperament_tags" in body:
            tags = body["temperament_tags"]
            if not isinstance(tags, list) or any(not isinstance(t, str) for t in tags):
                raise_err(ERR_INVALID_REQUEST, "temperament_tags must be list of strings")
            animal["temperament_tags"] = list(tags)
        if "adoption_fee_override" in body:
            v = body["adoption_fee_override"]
            if v is not None and (isinstance(v, bool) or not isinstance(v, int) or v < 0):
                raise_err(ERR_INVALID_REQUEST, "adoption_fee_override invalid")
            animal["adoption_fee_override"] = v
        if "special_care_level" in body:
            if body["special_care_level"] not in SPECIAL_CARE:
                raise_err(ERR_INVALID_REQUEST, "Invalid special_care_level")
            animal["special_care_level"] = body["special_care_level"]
        animal["updated_at"] = now_dt()
        animal["version"] += 1
    return success_object(serialize_animal(animal))


@bp.route("/shelters/<sid>/animals/<aid>/vaccinations", methods=["POST"])
@auth_required(allowed_roles={"ShelterAdmin", "Veterinarian"})
def record_vaccination(sid, aid):
    get_shelter_or_404(sid)
    animal = get_animal_or_404(aid)
    if animal["shelter_id"] != sid:
        raise_err(ERR_ANIMAL_NOT_FOUND, "Animal does not belong to this shelter")
    body = get_json_body(required=True)
    vtype = require_enum(body, "vaccine_type", VACCINE_TYPES)
    admin_date = parse_required_dt(body, "administered_date")
    expires_date = parse_required_dt(body, "expires_date")
    lot = require_field(body, "lot_number", types=str)
    with lock:
        vid = new_id()
        now = now_dt()
        rec = {
            "id": vid,
            "animal_id": aid,
            "vaccine_type": vtype,
            "administered_date": admin_date,
            "expires_date": expires_date,
            "lot_number": lot,
            "created_at": now,
        }
        store.vaccinations[vid] = rec
    return success_object(serialize_vaccination(rec), status_code=201)


@bp.route("/shelters/<sid>/animals/<aid>/vaccinations", methods=["GET"])
@auth_required(allowed_roles={"Any"})
def list_vaccinations(sid, aid):
    get_shelter_or_404(sid)
    animal = get_animal_or_404(aid)
    if animal["shelter_id"] != sid:
        raise_err(ERR_ANIMAL_NOT_FOUND, "Animal does not belong to this shelter")
    limit, offset = pagination()
    vtype_f = request.args.get("vaccine_type")
    recs = [v for v in store.vaccinations.values() if v["animal_id"] == aid]
    if vtype_f:
        recs = [v for v in recs if v["vaccine_type"] == vtype_f]
    recs.sort(key=lambda r: r["created_at"])
    total = len(recs)
    page = recs[offset: offset + limit]
    return success_array([serialize_vaccination(v) for v in page], limit, offset, total)


@bp.route("/shelters/<sid>/animals/<aid>/compliance", methods=["GET"])
@auth_required(allowed_roles={"Any"})
def get_compliance(sid, aid):
    get_shelter_or_404(sid)
    animal = get_animal_or_404(aid)
    if animal["shelter_id"] != sid:
        raise_err(ERR_ANIMAL_NOT_FOUND, "Animal does not belong to this shelter")
    return success_object(serialize_compliance(aid))
