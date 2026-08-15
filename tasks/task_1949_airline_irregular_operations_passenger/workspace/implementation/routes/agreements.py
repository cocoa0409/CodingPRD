"""Interline agreement CRUD + suspend toggle."""

from flask import Blueprint, request

import errors
from db import db
from middleware import authenticate, require_role
from response import success_list, success_object
from serializers import serialize_agreement
from services.core import stamp_new, touch
from validators import (
    get_json_body,
    get_json_body_optional,
    opt_query_enum,
    pagination_params,
    req_int,
    req_string,
)

bp = Blueprint("agreements", __name__)

AGREEMENT_STATUSES = {"ACTIVE", "SUSPENDED"}
CABINS = {"ECONOMY", "PREMIUM", "BUSINESS", "FIRST"}
AGREEMENT_READ_ROLES = ["OpsAdmin", "ReaccommodationAgent", "DutyManager"]


@bp.post("/irops/interline-agreements")
def create_agreement():
    caller = authenticate()
    require_role(caller, ["OpsAdmin"])
    body = get_json_body()
    partner_carrier = req_string(body, "partner_carrier")
    origin = req_string(body, "origin")
    destination = req_string(body, "destination")
    cabin_map = body.get("cabin_map")
    if not isinstance(cabin_map, dict):
        errors.raise_error(errors.ERR_INVALID_REQUEST, "cabin_map must be an object")
    for k, v in cabin_map.items():
        if k not in CABINS:
            errors.raise_error(errors.ERR_INVALID_ENUM,
                               "cabin_map key %r outside declared enum domain" % k)
        if not isinstance(v, str):
            errors.raise_error(errors.ERR_INVALID_REQUEST,
                               "cabin_map values must be strings")
    settlement_rate_pct = req_int(body, "settlement_rate_pct")
    if settlement_rate_pct < 0 or settlement_rate_pct > 100:
        errors.raise_error(errors.ERR_INVALID_REQUEST,
                           "settlement_rate_pct must be between 0 and 100")
    seats_quota = req_int(body, "seats_quota_per_flight")
    a = stamp_new({
        "partner_carrier": partner_carrier,
        "origin": origin,
        "destination": destination,
        "cabin_map": dict(cabin_map),
        "settlement_rate_pct": settlement_rate_pct,
        "seats_quota_per_flight": seats_quota,
        "agreement_status": "ACTIVE",
    })
    db.interline_agreements[a["id"]] = a
    return success_object(serialize_agreement(a), 201)


@bp.get("/irops/interline-agreements/<aid>")
def get_agreement(aid):
    caller = authenticate()
    require_role(caller, AGREEMENT_READ_ROLES)
    a = db.interline_agreements.get(aid)
    if a is None:
        errors.raise_error(errors.ERR_NOT_FOUND, "InterlineAgreement not found")
    return success_object(serialize_agreement(a), 200)


@bp.get("/irops/interline-agreements")
def list_agreements():
    caller = authenticate()
    require_role(caller, AGREEMENT_READ_ROLES)
    partner = request.args.get("partner_carrier")
    status = opt_query_enum("agreement_status", AGREEMENT_STATUSES)
    limit, offset = pagination_params()
    items = sorted(db.interline_agreements.values(), key=lambda a: a["created_at"])
    if partner is not None:
        items = [a for a in items if a["partner_carrier"] == partner]
    if status is not None:
        items = [a for a in items if a["agreement_status"] == status]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_agreement(a) for a in page], limit, offset, total)


@bp.post("/irops/interline-agreements/<aid>/suspend")
def suspend_agreement(aid):
    caller = authenticate()
    require_role(caller, ["OpsAdmin"])
    get_json_body_optional()
    a = db.interline_agreements.get(aid)
    if a is None:
        errors.raise_error(errors.ERR_NOT_FOUND, "InterlineAgreement not found")
    a["agreement_status"] = "SUSPENDED" if a["agreement_status"] == "ACTIVE" else "ACTIVE"
    touch(a)
    return success_object(serialize_agreement(a), 200)
