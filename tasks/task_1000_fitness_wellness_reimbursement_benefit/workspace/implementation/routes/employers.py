"""Employer endpoints."""
from flask import Blueprint, request

from db import STORE
from errors import err, ERR_EMPLOYER_NOT_FOUND, ERR_INVALID_REQUEST
from middleware import require_roles
from response import success, paginate
from services.core import new_entity, touch, serialize, sort_created
from util import body_json, req, as_str, check_enum

bp = Blueprint("employers", __name__)

FUNDING_MODELS = ("PREFUNDED", "PAY_AS_YOU_GO")


def get_employer(eid):
    e = STORE.employers.get(eid)
    if e is None:
        raise err(ERR_EMPLOYER_NOT_FOUND, 404, "employer id does not resolve")
    return e


@bp.post("/api/employers")
def create_employer():
    require_roles("BenefitsAdmin")
    body = body_json()
    name = as_str(req(body, "name"), "name")
    funding_model = check_enum(req(body, "funding_model"), FUNDING_MODELS, "funding_model")
    e = new_entity()
    e.update({"name": name, "funding_model": funding_model, "status": "ACTIVE"})
    STORE.employers[e["id"]] = e
    return success(serialize(e), 201)


@bp.get("/api/employers/<eid>")
def read_employer(eid):
    require_roles("BenefitsAdmin", "Auditor")
    return success(serialize(get_employer(eid)))


@bp.get("/api/employers")
def list_employers():
    require_roles("BenefitsAdmin", "Auditor")
    items = sort_created(STORE.employers.values())
    status = request.args.get("status")
    if status is not None:
        items = [e for e in items if e["status"] == status]
    return paginate([serialize(e) for e in items])


@bp.post("/api/employers/<eid>/suspend")
def suspend_employer(eid):
    require_roles("BenefitsAdmin")
    e = get_employer(eid)
    if e["status"] != "ACTIVE":
        raise err(ERR_INVALID_REQUEST, 409, "suspend requires employer ACTIVE")
    e["status"] = "SUSPENDED"
    touch(e)
    return success(serialize(e))


@bp.post("/api/employers/<eid>/reactivate")
def reactivate_employer(eid):
    require_roles("BenefitsAdmin")
    e = get_employer(eid)
    if e["status"] != "SUSPENDED":
        raise err(ERR_INVALID_REQUEST, 409, "reactivate requires employer SUSPENDED")
    e["status"] = "ACTIVE"
    touch(e)
    return success(serialize(e))
