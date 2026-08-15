"""Jurisdiction endpoints."""

from flask import Blueprint, request

import db
from errors import invalid_request, ApiError, ERR_STALE_VERSION
from middleware import authenticate, require_roles
from response import success_object, success_list
from services.common import (
    new_id, get_body, require, optional, get_jurisdiction, paginate, MISSING,
)

bp = Blueprint("jurisdictions", __name__)

_FIELDS = [
    ("name", "str"),
    ("state_code", "str"),
    ("county_name", "str"),
    ("permit_threshold_sqft", "int"),
    ("setback_front_ft", "num"),
    ("setback_side_ft", "num"),
    ("setback_rear_ft", "num"),
    ("max_building_height_ft", "num"),
    ("anchoring_required", "bool"),
    ("permit_base_fee_cents", "int"),
    ("permit_per_sqft_cents", "int"),
    ("tax_rate_bp", "int"),
]


@bp.post("/api/jurisdictions")
def create_jurisdiction():
    authenticate()
    require_roles("PermitCoordinator")
    body = get_body()
    row = {"id": new_id()}
    for name, t in _FIELDS:
        row[name] = require(body, name, t)
    now = db.now_iso()
    row["created_at"] = now
    row["updated_at"] = now
    row["version"] = 1
    db.jurisdictions[row["id"]] = row
    return success_object(row, 201)


@bp.get("/api/jurisdictions/<jid>")
def read_jurisdiction(jid):
    authenticate()
    require_roles("Customer", "SalesRep", "PermitCoordinator", "InstallCrew",
                  "FinanceManager", "OperationsAdmin")
    return success_object(get_jurisdiction(jid))


@bp.put("/api/jurisdictions/<jid>")
def update_jurisdiction(jid):
    authenticate()
    require_roles("PermitCoordinator")
    body = get_body()
    row = get_jurisdiction(jid)
    # OCC guard (§2.7): expected_jurisdiction_version is required on this endpoint
    expected = require(body, "expected_jurisdiction_version", "int")
    if expected != row["version"]:
        raise ApiError(ERR_STALE_VERSION,
                       "expected_jurisdiction_version does not match current version", 412)
    for name, t in _FIELDS:
        v = optional(body, name, t, default=MISSING)
        if v is not MISSING:
            row[name] = v
    row["version"] += 1
    row["updated_at"] = db.now_iso()
    return success_object(row)


@bp.get("/api/jurisdictions/<jid>/permit-applications")
def list_jurisdiction_permit_applications(jid):
    authenticate()
    require_roles("Customer", "SalesRep", "PermitCoordinator", "InstallCrew",
                  "FinanceManager", "OperationsAdmin")
    get_jurisdiction(jid)
    rows = [p for p in db.permit_applications.values() if p["jurisdiction_id"] == jid]
    rows.sort(key=lambda p: p["created_at"])
    limit, offset = paginate(request.args, rows)
    return success_list(rows[offset:offset + limit], limit, offset, len(rows))
