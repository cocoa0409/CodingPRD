"""Pet endpoints (PRD §3.1, §4)."""
from flask import Blueprint

from db import db
from errors import err
from middleware import authenticate, require_owner_match, require_role
from response import array_response, object_response
from services.core import (append_audit, recompute_kennel_occupied_slots,
                           recompute_owner_active_license_count, stamp_create,
                           touch)
from services.license import _current_tag
from services.reqs import (body, paginate, parse_pagination, require_enum,
                          require_fields)
from services.views import (case_view, license_view, pet_view, report_view,
                           vaccination_view)

bp = Blueprint("pets", __name__)

ALL_ROLES = {"Owner", "LicensingClerk", "AnimalControlOfficer"}
SPECIES = {"DOG", "CAT"}


@bp.route("/pets", methods=["POST"])
def create_pet():
    _, role = authenticate()
    require_role(role, {"Owner", "LicensingClerk"})
    data = body()
    require_fields(data, ["owner_id", "name", "species", "breed", "birth_date"])
    require_enum(data["species"], SPECIES, "species")
    # is_altered defaults to false (SCAFFOLD §1.1)
    is_altered = data.get("is_altered", False)
    if not isinstance(is_altered, bool):
        raise err("ERR_INVALID_REQUEST", "is_altered must be a boolean.")
    # existence of owner FK
    if db.owners.get(data["owner_id"]) is None:
        raise err("ERR_NOT_FOUND", "Owner not found.")
    pet = {
        "owner_id": data["owner_id"],
        "name": data["name"],
        "species": data["species"],
        "breed": data["breed"],
        "is_altered": is_altered,
        "birth_date": data["birth_date"],
        "is_dangerous": False,
        "status": "ACTIVE",
    }
    stamp_create(pet)
    db.pets[pet["id"]] = pet
    return object_response(pet_view(pet), status=201)


@bp.route("/pets/<pet_id>", methods=["GET"])
def get_pet(pet_id):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    pet = db.pets.get(pet_id)
    if pet is None:
        raise err("ERR_NOT_FOUND", "Pet not found.")
    return object_response(pet_view(pet))


@bp.route("/pets/<pet_id>/mark-deceased", methods=["POST"])
def mark_deceased(pet_id):
    user_id, role = authenticate()
    require_role(role, {"Owner"})
    pet = db.pets.get(pet_id)
    if pet is None:
        raise err("ERR_NOT_FOUND", "Pet not found.")
    require_owner_match(role, user_id, pet["owner_id"])
    if pet["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Pet is not ACTIVE.")

    pet["status"] = "DECEASED"
    touch(pet)

    affected_kennels = set()
    for lic in [l for l in db.licenses.values() if l["pet_id"] == pet_id]:
        if lic["status"] in ("ACTIVE", "GRACE", "APPROVED"):
            tag = _current_tag(lic)
            if tag is not None:
                tag["status"] = "VOID"
                touch(tag)
            lic["status"] = "REVOKED"
            touch(lic)
            if lic.get("kennel_id"):
                affected_kennels.add(lic["kennel_id"])
    recompute_owner_active_license_count(pet["owner_id"])
    for kid in affected_kennels:
        recompute_kennel_occupied_slots(kid)
    append_audit("LICENSE", pet_id, "PET_DECEASED_LICENSES_REVOKED", role)
    return object_response(pet_view(pet))


def _list_pet_children(pet_id, role, collection, fk_field, view):
    require_role(role, ALL_ROLES)
    if db.pets.get(pet_id) is None:
        raise err("ERR_NOT_FOUND", "Pet not found.")
    limit, offset = parse_pagination()
    items = [r for r in collection.values() if r.get(fk_field) == pet_id]
    page, total = paginate(items, limit, offset)
    return array_response([view(r) for r in page], limit, offset, total)


@bp.route("/pets/<pet_id>/vaccination-records", methods=["GET"])
def list_pet_vaccinations(pet_id):
    _, role = authenticate()
    return _list_pet_children(pet_id, role, db.vaccination_records, "pet_id", vaccination_view)


@bp.route("/pets/<pet_id>/licenses", methods=["GET"])
def list_pet_licenses(pet_id):
    _, role = authenticate()
    return _list_pet_children(pet_id, role, db.licenses, "pet_id", license_view)


@bp.route("/pets/<pet_id>/dangerous-dog-cases", methods=["GET"])
def list_pet_cases(pet_id):
    _, role = authenticate()
    return _list_pet_children(pet_id, role, db.dangerous_dog_cases, "pet_id", case_view)


@bp.route("/pets/<pet_id>/lost-found-reports", methods=["GET"])
def list_pet_reports(pet_id):
    _, role = authenticate()
    return _list_pet_children(pet_id, role, db.lost_found_reports, "pet_id", report_view)
