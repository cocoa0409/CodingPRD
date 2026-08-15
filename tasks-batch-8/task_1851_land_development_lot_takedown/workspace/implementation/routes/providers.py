"""UtilityProvider endpoints (PRD 3.9): provider registration."""
from flask import Blueprint, request

from db import db
from errors import raise_error, ERR_DUPLICATE_PROVIDER_NAME
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response, public
from services.core import new_record
from validate import get_body, req_enum, req_int, req_str

bp = Blueprint("providers", __name__)

UTILITY_TYPES = {"WATER", "SEWER", "ELECTRIC"}


@bp.post("/utility-providers")
def create_provider():
    authorized(["MunicipalClerk"])
    body = get_body()
    provider_name = req_str(body, "provider_name")
    utility_type = req_enum(body, "utility_type", UTILITY_TYPES)
    max_per_day = req_int(body, "max_connections_per_day", minimum=1)
    # Priority 9: provider name unique
    for other in db["providers"].values():
        if other["provider_name"] == provider_name:
            raise_error(ERR_DUPLICATE_PROVIDER_NAME, "provider_name already registered")
    rec = new_record("providers", {
        "provider_name": provider_name,
        "utility_type": utility_type,
        "max_connections_per_day": max_per_day,
    })
    return success_object(public(rec), status=201)


@bp.get("/utility-providers")
def list_providers():
    return list_response("providers", {"utility_type": request.args.get("utility_type")})


@bp.get("/utility-providers/<rid>")
def get_provider(rid):
    return get_one("providers", rid)
