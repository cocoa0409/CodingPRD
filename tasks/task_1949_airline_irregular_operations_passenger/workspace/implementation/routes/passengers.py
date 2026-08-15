"""Passenger registration and reads."""

from flask import Blueprint

import errors
from db import db
from middleware import ALL_ROLES, authenticate, require_role
from response import success_list, success_object
from serializers import serialize_passenger
from services.core import stamp_new
from validators import (
    get_json_body,
    opt_enum,
    opt_query_enum,
    pagination_params,
    req_string,
)

bp = Blueprint("passengers", __name__)

LOYALTY_TIERS = {"NONE", "SILVER", "GOLD", "PLATINUM"}
SSR_CODES = {"UMNR", "WCHR", "PETC"}


@bp.post("/irops/passengers")
def create_passenger():
    caller = authenticate()
    require_role(caller, ["ReaccommodationAgent", "OpsController"])
    body = get_json_body()
    full_name = req_string(body, "full_name")
    contact_email = req_string(body, "contact_email")
    loyalty_tier = opt_enum(body, "loyalty_tier", LOYALTY_TIERS, "NONE")
    codes = body.get("special_service_codes", [])
    if codes is None:
        codes = []
    if not isinstance(codes, list):
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           "special_service_codes must be an array")
    for c in codes:
        if not isinstance(c, str):
            errors.raise_error(errors.ERR_INVALID_REQUEST,
                               "special_service_codes entries must be strings")
        if c not in SSR_CODES:
            errors.raise_error(errors.ERR_INVALID_ENUM,
                               "special_service_codes value %r outside declared domain" % c)
    p = stamp_new({
        "full_name": full_name,
        "loyalty_tier": loyalty_tier,
        "special_service_codes": list(codes),
        "contact_email": contact_email,
    })
    db.passengers[p["id"]] = p
    return success_object(serialize_passenger(p), 201)


@bp.get("/irops/passengers/<pid>")
def get_passenger(pid):
    caller = authenticate()
    require_role(caller, ALL_ROLES)
    p = db.passengers.get(pid)
    if p is None:
        errors.raise_error(errors.ERR_NOT_FOUND, "Passenger not found")
    if caller.is_passenger and p["id"] != caller.user_id:
        errors.raise_error(errors.ERR_FORBIDDEN_OWNERSHIP,
                           "Passenger may only read their own record")
    return success_object(serialize_passenger(p), 200)


@bp.get("/irops/passengers")
def list_passengers():
    caller = authenticate()
    require_role(caller, ["ReaccommodationAgent", "OpsController", "DutyManager", "OpsAdmin"])
    tier = opt_query_enum("loyalty_tier", LOYALTY_TIERS)
    limit, offset = pagination_params()
    items = sorted(db.passengers.values(), key=lambda p: p["created_at"])
    if tier is not None:
        items = [p for p in items if p["loyalty_tier"] == tier]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_passenger(p) for p in page], limit, offset, total)
