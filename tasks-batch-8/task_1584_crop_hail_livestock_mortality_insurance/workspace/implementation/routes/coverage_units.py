"""Coverage unit endpoints (PRD 3.4)."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import raise_err, ERR_INVALID_REQUEST, ERR_INVALID_STATE
from middleware import require_roles
from response import success_object, success_list
from routes.common import resolve_carrier, resolve_policy, resolve_unit
from serializers import coverage_unit_view
from services import core
from util import (
    get_json_body, reject_unknown_fields, require_enum, require_int,
    optional_string, optional_int, parse_pagination, paginate, sort_created,
    query_arg, dt,
)

bp = Blueprint("coverage_units", __name__)

ALL_ROLES = ("PlatformAdmin", "Underwriter", "Policyholder", "Adjuster", "ClaimsApprover")
SPECIES = {"CATTLE", "SWINE", "POULTRY", "EQUINE", "SHEEP"}

CREATE_FIELDS = {
    "county_code", "crop_code", "declared_acres",
    "species", "declared_head_count", "per_head_value_cents",
}


@bp.route("/carriers/<carrierId>/policies/<policyId>/coverage-units", methods=["POST"])
@require_roles("Underwriter")
def create_coverage_unit(carrierId: str, policyId: str, _user_id: str, _role: str):
    carrier = resolve_carrier(carrierId)
    policy = resolve_policy(carrier["id"], policyId)
    body = get_json_body()
    reject_unknown_fields(body, CREATE_FIELDS)

    if policy["lifecycle_state"] != "APPLICATION":
        raise_err(ERR_INVALID_STATE,
                  "Coverage units are added while the policy is an application")

    county_code = optional_string(body, "county_code")
    crop_code = optional_string(body, "crop_code")
    declared_acres = optional_int(body, "declared_acres")
    species = None
    if "species" in body and body["species"] is not None:
        species = require_enum(body, "species", SPECIES)
    declared_head_count = optional_int(body, "declared_head_count")
    per_head_value_cents = optional_int(body, "per_head_value_cents")

    if policy["policy_kind"] == "CROP_HAIL":
        if county_code is None or county_code == "":
            raise_err(ERR_INVALID_REQUEST, "county_code is required for crop-hail units")
        if crop_code is None or crop_code == "":
            raise_err(ERR_INVALID_REQUEST, "crop_code is required for crop-hail units")
        if declared_acres is None:
            raise_err(ERR_INVALID_REQUEST, "declared_acres is required for crop-hail units")
        if not (1 <= declared_acres <= 100000):
            raise_err(ERR_INVALID_REQUEST, "declared_acres must be within 1..100000")
        species = None
        declared_head_count = None
        per_head_value_cents = None
    else:
        if species is None:
            raise_err(ERR_INVALID_REQUEST, "species is required for livestock units")
        if declared_head_count is None:
            raise_err(ERR_INVALID_REQUEST, "declared_head_count is required for livestock units")
        if not (1 <= declared_head_count <= 100000):
            raise_err(ERR_INVALID_REQUEST, "declared_head_count must be within 1..100000")
        if per_head_value_cents is None:
            raise_err(ERR_INVALID_REQUEST, "per_head_value_cents is required for livestock units")
        if per_head_value_cents < 1:
            raise_err(ERR_INVALID_REQUEST, "per_head_value_cents must be >= 1")
        county_code = None
        crop_code = None
        declared_acres = None

    unit = db.stamp_new({
        "policy_id": policy["id"],
        "unit_kind": policy["policy_kind"],
        "county_code": county_code,
        "crop_code": crop_code,
        "declared_acres": declared_acres,
        "species": species,
        "declared_head_count": declared_head_count,
        "per_head_value_cents": per_head_value_cents,
        "liability_cents": 0,
        "premium_cents": 0,
        "status": "PENDING_REPORT",
        "_rate_table_id": None,
    }, carrier["current_utc"])

    unit["liability_cents"] = core.compute_unit_liability(unit)
    row, premium = core.rate_unit(unit, carrier["id"], dt(carrier["current_utc"]))
    if row is not None:
        unit["_rate_table_id"] = row["id"]
        unit["premium_cents"] = premium

    db.coverage_units[unit["id"]] = unit
    return success_object(coverage_unit_view(unit), 201)


@bp.route("/carriers/<carrierId>/policies/<policyId>/coverage-units", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_coverage_units(carrierId: str, policyId: str, _user_id: str, _role: str):
    carrier = resolve_carrier(carrierId)
    policy = resolve_policy(carrier["id"], policyId)
    items = core.units_of_policy(policy["id"])
    status = query_arg("status")
    if status is not None:
        items = [u for u in items if u["status"] == status]
    items = sort_created(items)
    limit, offset = parse_pagination()
    page, total = paginate(items, limit, offset)
    return success_list([coverage_unit_view(u) for u in page], limit, offset, total)


@bp.route("/carriers/<carrierId>/policies/<policyId>/coverage-units/<unitId>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_coverage_unit(carrierId: str, policyId: str, unitId: str,
                      _user_id: str, _role: str):
    carrier = resolve_carrier(carrierId)
    policy = resolve_policy(carrier["id"], policyId)
    unit = resolve_unit(policy["id"], unitId)
    return success_object(coverage_unit_view(unit))
