"""Federal crop policy registry endpoints (PRD 3.3)."""

from __future__ import annotations

from decimal import Decimal

from flask import Blueprint

import db
from errors import raise_err, ERR_INVALID_REQUEST, ERR_INVALID_DATE_RANGE, ERR_INVALID_STATE
from middleware import require_roles
from response import success_object, success_list
from routes.common import resolve_carrier, resolve_federal, resolve_grower
from serializers import federal_view
from util import (
    get_json_body, reject_unknown_fields, require_string, require_int,
    require_datetime, is_number, parse_pagination, paginate, sort_created,
    query_arg, dt,
)

bp = Blueprint("federal", __name__)

ALL_ROLES = ("PlatformAdmin", "Underwriter", "Policyholder", "Adjuster", "ClaimsApprover")
LIST_ROLES = ("PlatformAdmin", "Underwriter", "ClaimsApprover")

CREATE_FIELDS = {
    "grower_id", "fci_policy_number", "coverage_level_pct", "crop_code",
    "county_code", "effective_date", "expiration_date", "liability_cents",
}


@bp.route("/carriers/<carrierId>/federal-crop-policies", methods=["POST"])
@require_roles("Underwriter")
def create_federal(carrierId: str, _user_id: str, _role: str):
    carrier = resolve_carrier(carrierId)
    body = get_json_body()
    reject_unknown_fields(body, CREATE_FIELDS)
    grower_id = require_string(body, "grower_id")
    fci_policy_number = require_string(body, "fci_policy_number")
    level = body.get("coverage_level_pct")
    if not is_number(level):
        raise_err(ERR_INVALID_REQUEST, "coverage_level_pct must be a number")
    level_dec = Decimal(str(level))
    if level_dec < Decimal("0.50") or level_dec > Decimal("0.85"):
        raise_err(ERR_INVALID_REQUEST,
                  "coverage_level_pct must be between 0.50 and 0.85 inclusive")
    crop_code = require_string(body, "crop_code")
    county_code = require_string(body, "county_code")
    effective_date = require_datetime(body, "effective_date")
    expiration_date = require_datetime(body, "expiration_date")
    if dt(expiration_date) <= dt(effective_date):
        raise_err(ERR_INVALID_DATE_RANGE,
                  "expiration_date must fall after effective_date")
    liability = require_int(body, "liability_cents", minimum=0)

    resolve_grower(carrier["id"], grower_id)  # body reference must exist (404)

    fed = db.stamp_new({
        "carrier_id": carrier["id"],
        "grower_id": grower_id,
        "fci_policy_number": fci_policy_number,
        "coverage_level_pct": level,
        "crop_code": crop_code,
        "county_code": county_code,
        "effective_date": effective_date,
        "expiration_date": expiration_date,
        "liability_cents": liability,
        "status": "ACTIVE",
    }, carrier["current_utc"])
    db.federal_policies[fed["id"]] = fed
    return success_object(federal_view(fed), 201)


@bp.route("/carriers/<carrierId>/federal-crop-policies", methods=["GET"])
@require_roles(*LIST_ROLES)
def list_federal(carrierId: str, _user_id: str, _role: str):
    carrier = resolve_carrier(carrierId)
    items = [f for f in db.federal_policies.values() if f["carrier_id"] == carrier["id"]]
    grower_id = query_arg("grower_id")
    status = query_arg("status")
    if grower_id is not None:
        items = [f for f in items if f["grower_id"] == grower_id]
    if status is not None:
        items = [f for f in items if f["status"] == status]
    items = sort_created(items)
    limit, offset = parse_pagination()
    page, total = paginate(items, limit, offset)
    return success_list([federal_view(f) for f in page], limit, offset, total)


@bp.route("/carriers/<carrierId>/federal-crop-policies/<fciId>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_federal(carrierId: str, fciId: str, _user_id: str, _role: str):
    carrier = resolve_carrier(carrierId)
    fed = resolve_federal(carrier["id"], fciId)
    return success_object(federal_view(fed))


@bp.route("/carriers/<carrierId>/federal-crop-policies/<fciId>/cancel", methods=["POST"])
@require_roles("Underwriter")
def cancel_federal(carrierId: str, fciId: str, _user_id: str, _role: str):
    carrier = resolve_carrier(carrierId)
    fed = resolve_federal(carrier["id"], fciId)
    body = get_json_body()
    reject_unknown_fields(body, set())

    if fed["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "Only an ACTIVE federal crop policy can be cancelled")
    fed["status"] = "CANCELLED"
    db.touch(fed, carrier["current_utc"])
    return success_object(federal_view(fed))
