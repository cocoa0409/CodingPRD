"""Evaluator endpoints."""
from flask import Blueprint, request

from db import store
from errors import err_not_found, err_invalid_request, err_invalid_enum
from middleware import get_auth, require_roles
from response import success_object, success_list, paginate
from services.records import new_record, touch, public
from constants import SPECIES, EVALUATOR_STATUSES
from validate import get_body, validate_body

bp = Blueprint("evaluators", __name__)

ALL_ROLES = ["ProgramAdmin", "Handler", "Evaluator", "FacilityCoordinator", "ComplianceOfficer"]


def _validate_specializations(value):
    if not isinstance(value, list) or not value:
        raise err_invalid_request("specializations must be a non-empty array")
    for item in value:
        if item not in SPECIES:
            raise err_invalid_enum("specializations", item)
    return value


def _validate_cap(value):
    if not isinstance(value, int) or isinstance(value, bool) or not (1 <= value <= 8):
        raise err_invalid_request("max_evaluations_per_day must be an integer in 1..8")
    return value


def _get_evaluator(evaluator_id):
    e = store.evaluators.get(evaluator_id)
    if e is None:
        raise err_not_found("evaluator")
    return e


@bp.post("/v1/evaluators")
def create_evaluator():
    auth = get_auth()
    require_roles(auth, ["ProgramAdmin"])
    body = validate_body(get_body(), {
        "full_name": ("string", True, None),
        "email": ("string", True, None),
        "region_code": ("string", True, None),
        "specializations": ("array", True, None),
        "max_evaluations_per_day": ("integer", False, None),
    })
    specs = _validate_specializations(body["specializations"])
    cap = 4
    if "max_evaluations_per_day" in body:
        cap = _validate_cap(body["max_evaluations_per_day"])
    rec = new_record(store.evaluators, {
        "full_name": body["full_name"],
        "email": body["email"],
        "region_code": body["region_code"],
        "specializations": specs,
        "max_evaluations_per_day": cap,
        "status": "ACTIVE",
    })
    return success_object(public(rec), 201)


@bp.get("/v1/evaluators/<evaluator_id>")
def get_evaluator(evaluator_id):
    auth = get_auth()
    require_roles(auth, ALL_ROLES)
    return success_object(public(_get_evaluator(evaluator_id)), 200)


@bp.get("/v1/evaluators")
def list_evaluators():
    auth = get_auth()
    require_roles(auth, ALL_ROLES)
    records = list(store.evaluators.values())
    status = request.args.get("status")
    region_code = request.args.get("region_code")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    if region_code is not None:
        records = [r for r in records if r["region_code"] == region_code]
    page, limit, offset, total = paginate(records, request.args)
    return success_list([public(r) for r in page], limit, offset, total)


@bp.patch("/v1/evaluators/<evaluator_id>")
def patch_evaluator(evaluator_id):
    auth = get_auth()
    require_roles(auth, ["ProgramAdmin"])
    e = _get_evaluator(evaluator_id)
    body = validate_body(get_body(), {
        "status": ("string", False, EVALUATOR_STATUSES),
        "specializations": ("array", False, None),
        "max_evaluations_per_day": ("integer", False, None),
    }, partial=True)
    changed = False
    if "status" in body and body["status"] != e["status"]:
        e["status"] = body["status"]
        changed = True
    if "specializations" in body:
        e["specializations"] = _validate_specializations(body["specializations"])
        changed = True
    if "max_evaluations_per_day" in body:
        e["max_evaluations_per_day"] = _validate_cap(body["max_evaluations_per_day"])
        changed = True
    if changed:
        touch(e)
    return success_object(public(e), 200)
