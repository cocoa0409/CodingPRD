"""Animal endpoints."""
from flask import Blueprint, request

from db import store
from errors import err, err_not_found
from middleware import get_auth, require_roles, err_ownership
from response import success_object, success_list, paginate
from services.records import new_record, touch, public
from constants import SPECIES
from validate import get_body, validate_body

bp = Blueprint("animals", __name__)

ALL_ROLES = ["ProgramAdmin", "Handler", "Evaluator", "FacilityCoordinator", "ComplianceOfficer"]


def _get_animal(animal_id):
    a = store.animals.get(animal_id)
    if a is None:
        raise err_not_found("animal")
    return a


@bp.post("/v1/animals")
def create_animal():
    auth = get_auth()
    require_roles(auth, ["Handler"])
    body = validate_body(get_body(), {
        "name": ("string", True, None),
        "species": ("string", True, SPECIES),
        "breed": ("string", True, None),
        "date_of_birth": ("date", True, None),
    })
    rec = new_record(store.animals, {
        "handler_id": auth.user_id,
        "name": body["name"],
        "species": body["species"],
        "breed": body["breed"],
        "date_of_birth": body["date_of_birth"],
        "status": "REGISTERED",
        "welfare_hold_until": None,
        "welfare_hold_reason": None,
        "welfare_blocked_until": None,
        "forward_workload_minutes": 0,
        "audit_workload_minutes": 0,
    })
    return success_object(public(rec), 201)


@bp.get("/v1/animals/<animal_id>")
def get_animal(animal_id):
    auth = get_auth()
    require_roles(auth, ALL_ROLES)
    return success_object(public(_get_animal(animal_id)), 200)


@bp.get("/v1/animals")
def list_animals():
    auth = get_auth()
    require_roles(auth, ALL_ROLES)
    records = list(store.animals.values())
    handler_id = request.args.get("handler_id")
    status = request.args.get("status")
    species = request.args.get("species")
    if handler_id is not None:
        records = [r for r in records if r["handler_id"] == handler_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    if species is not None:
        records = [r for r in records if r["species"] == species]
    page, limit, offset, total = paginate(records, request.args)
    return success_list([public(r) for r in page], limit, offset, total)


@bp.post("/v1/animals/<animal_id>/retire")
def retire_animal(animal_id):
    auth = get_auth()
    require_roles(auth, ["Handler"])
    a = _get_animal(animal_id)
    if a["handler_id"] != auth.user_id:
        raise err_ownership()
    if a["status"] not in ("REGISTERED", "ACTIVE"):
        raise err("ERR_ANIMAL_NOT_RETIRABLE", 409, "Animal is not REGISTERED or ACTIVE")
    for team in store.teams.values():
        if team["animal_id"] == a["id"] and team["status"] in ("FORMING", "ACTIVE", "SUSPENDED"):
            raise err("ERR_ANIMAL_HAS_ACTIVE_TEAM", 409,
                      "Animal belongs to a non-dissolved team")
    a["status"] = "RETIRED"
    touch(a)
    return success_object(public(a), 200)


@bp.post("/v1/animals/<animal_id>/welfare-hold")
def welfare_hold(animal_id):
    auth = get_auth()
    require_roles(auth, ["ComplianceOfficer"])
    a = _get_animal(animal_id)
    body = validate_body(get_body(), {
        "hold_until": ("datetime", True, None),
        "reason": ("string", True, None),
    })
    if a["status"] != "ACTIVE":
        raise err("ERR_ANIMAL_NOT_ACTIVE", 409, "Animal is not ACTIVE")
    a["status"] = "WELFARE_HOLD"
    from util import parse_datetime, fmt_dt
    a["welfare_hold_until"] = fmt_dt(parse_datetime(body["hold_until"]))
    a["welfare_hold_reason"] = "MANUAL"
    touch(a)
    return success_object(public(a), 200)


@bp.post("/v1/animals/<animal_id>/welfare-release")
def welfare_release(animal_id):
    auth = get_auth()
    require_roles(auth, ["ComplianceOfficer"])
    a = _get_animal(animal_id)
    if a["status"] != "WELFARE_HOLD":
        raise err("ERR_ANIMAL_NOT_ON_HOLD", 409, "Animal is not in WELFARE_HOLD")
    a["status"] = "ACTIVE"
    a["welfare_hold_until"] = None
    a["welfare_hold_reason"] = None
    touch(a)
    return success_object(public(a), 200)
