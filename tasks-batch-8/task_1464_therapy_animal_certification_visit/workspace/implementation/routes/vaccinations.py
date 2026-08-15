"""Vaccination record endpoints."""
from flask import Blueprint, request

from db import store
from errors import err, err_not_found
from middleware import get_auth, require_roles, err_ownership
from response import success_object, success_list, paginate
from services.records import new_record, touch, public
from constants import VACCINE_TYPES
from validate import get_body, validate_body

bp = Blueprint("vaccinations", __name__)

ALL_ROLES = ["ProgramAdmin", "Handler", "Evaluator", "FacilityCoordinator", "ComplianceOfficer"]


def _get_record(rec_id):
    r = store.vaccinations.get(rec_id)
    if r is None:
        raise err_not_found("vaccination")
    return r


@bp.post("/v1/vaccination-records")
def create_vaccination():
    auth = get_auth()
    require_roles(auth, ["Handler"])
    body = validate_body(get_body(), {
        "animal_id": ("string", True, None),
        "vaccine_type": ("string", True, VACCINE_TYPES),
        "administered_on": ("date", True, None),
        "valid_until": ("date", True, None),
        "veterinarian_name": ("string", True, None),
        "clinic_name": ("string", False, None),
    })
    # Existence of the referenced animal, then ownership.
    animal = store.animals.get(body["animal_id"])
    if animal is None:
        raise err_not_found("animal")
    if animal["handler_id"] != auth.user_id:
        raise err_ownership()
    rec = new_record(store.vaccinations, {
        "animal_id": body["animal_id"],
        "vaccine_type": body["vaccine_type"],
        "administered_on": body["administered_on"],
        "valid_until": body["valid_until"],
        "veterinarian_name": body["veterinarian_name"],
        "clinic_name": body.get("clinic_name"),
        "status": "VALID",
    })
    return success_object(public(rec), 201)


@bp.get("/v1/vaccination-records/<rec_id>")
def get_vaccination(rec_id):
    auth = get_auth()
    require_roles(auth, ALL_ROLES)
    return success_object(public(_get_record(rec_id)), 200)


@bp.get("/v1/vaccination-records")
def list_vaccinations():
    auth = get_auth()
    require_roles(auth, ALL_ROLES)
    records = list(store.vaccinations.values())
    animal_id = request.args.get("animal_id")
    status = request.args.get("status")
    vaccine_type = request.args.get("vaccine_type")
    if animal_id is not None:
        records = [r for r in records if r["animal_id"] == animal_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    if vaccine_type is not None:
        records = [r for r in records if r["vaccine_type"] == vaccine_type]
    page, limit, offset, total = paginate(records, request.args)
    return success_list([public(r) for r in page], limit, offset, total)


@bp.post("/v1/vaccination-records/<rec_id>/void")
def void_vaccination(rec_id):
    auth = get_auth()
    require_roles(auth, ["ComplianceOfficer"])
    rec = _get_record(rec_id)
    validate_body(get_body(), {"reason": ("string", True, None)})
    if rec["status"] != "VALID":
        raise err("ERR_VACCINATION_NOT_VALID", 409, "Vaccination record is not VALID")
    rec["status"] = "VOIDED"
    touch(rec)
    return success_object(public(rec), 200)
