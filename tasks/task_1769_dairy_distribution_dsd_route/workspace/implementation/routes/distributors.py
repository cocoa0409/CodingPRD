"""Distributor endpoints."""

from flask import Blueprint

from db import DB
from middleware import require_role, require_any
from util import (
    get_json_body, check_unknown_fields, require_fields, opt_int,
    base_fields, paginate, err,
)
from response import success_object
from errors import ERR_INVALID_REQUEST, ERR_DISTRIBUTOR_NOT_FOUND
from serializers import serialize_distributor

bp = Blueprint("distributors", __name__)


@bp.post("/dairy/distributors")
def create_distributor():
    require_role("TerritoryManager")
    body = get_json_body()
    check_unknown_fields(body, {"name", "license_number", "credit_terms_days"})
    require_fields(body, ["name", "license_number"])
    name = body["name"]
    if not isinstance(name, str):
        raise err(ERR_INVALID_REQUEST, "name must be a string")
    license_number = body["license_number"]
    if not isinstance(license_number, str):
        raise err(ERR_INVALID_REQUEST, "license_number must be a string")
    credit_terms_days = opt_int(body, "credit_terms_days", ge=0)
    if credit_terms_days is None:
        credit_terms_days = 7
    for d in DB.distributors.values():
        if d["license_number"] == license_number:
            raise err(ERR_INVALID_REQUEST, "license_number must be unique across distributors")
    d = base_fields()
    d.update({
        "name": name,
        "license_number": license_number,
        "credit_terms_days": credit_terms_days,
    })
    DB.distributors[d["id"]] = d
    return success_object(serialize_distributor(d), status=201)


@bp.get("/dairy/distributors/<distId>")
def get_distributor(distId):
    require_any()
    d = DB.distributors.get(distId)
    if d is None:
        raise err(ERR_DISTRIBUTOR_NOT_FOUND, "Distributor id not found")
    return success_object(serialize_distributor(d))
