"""Permit endpoints (PRD 3.5)."""
from flask import Blueprint

import db
from errors import invalid_state, validation
from middleware import auth, require_roles
from response import success
from services import cascades
from services.core import (
    PERMIT_TYPES,
    arg,
    as_dt,
    as_enum,
    as_str,
    base_record,
    body,
    get_child,
    get_market,
    list_response,
    required,
    serialize,
    touch,
)

bp = Blueprint("permits", __name__)

MO = ("MarketOperator",)
GET_ONE = ("MarketOperator", "VendorRole", "UtilityCrew")
GET_LIST = ("MarketOperator", "UtilityCrew")


def _temp_structure_cascade(permit):
    if permit["permit_type"] != "TEMP_STRUCTURE":
        return
    assignment = db.STORES["assignments"].get(permit["assignment_id"])
    if assignment is not None and assignment["status"] in ("PENDING_PAYMENT", "ACTIVE"):
        cascades.forfeit_assignment(assignment, strike=False, recompute=False)


@bp.post("/markets/<marketId>/permits")
def create_permit(marketId):
    user = auth()
    require_roles(user, MO)
    get_market(marketId)
    data = body()
    assignment_id = as_str(required(data, "assignment_id"), "assignment_id")
    get_child("assignments", assignment_id, marketId)
    permit_type = as_enum(required(data, "permit_type"), "permit_type", PERMIT_TYPES)
    issued_by = as_str(required(data, "issued_by"), "issued_by")
    issued_at = as_dt(required(data, "issued_at"), "issued_at")
    expires_at = as_dt(required(data, "expires_at"), "expires_at")
    if not expires_at > issued_at:
        raise validation("expires_at must be strictly after issued_at")
    rec = base_record()
    rec.update(
        {
            "market_id": marketId,
            "assignment_id": assignment_id,
            "permit_type": permit_type,
            "issued_by": issued_by,
            "issued_at": issued_at,
            "expires_at": expires_at,
            "status": "ACTIVE",
        }
    )
    db.STORES["permits"][rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.get("/markets/<marketId>/permits/<permitId>")
def get_permit(marketId, permitId):
    user = auth()
    require_roles(user, GET_ONE)
    get_market(marketId)
    return success(serialize(get_child("permits", permitId, marketId)))


@bp.get("/markets/<marketId>/permits")
def list_permits(marketId):
    user = auth()
    require_roles(user, GET_LIST)
    get_market(marketId)
    status = arg("status")
    permit_type = arg("permit_type")
    assignment_id = arg("assignment_id")
    records = []
    for p in db.STORES["permits"].values():
        if p["market_id"] != marketId:
            continue
        if status is not None and p["status"] != status:
            continue
        if permit_type is not None and p["permit_type"] != permit_type:
            continue
        if assignment_id is not None and p["assignment_id"] != assignment_id:
            continue
        records.append(p)
    return list_response(records)


@bp.post("/markets/<marketId>/permits/<permitId>/revoke")
def revoke_permit(marketId, permitId):
    user = auth()
    require_roles(user, MO)
    get_market(marketId)
    permit = get_child("permits", permitId, marketId)
    if permit["status"] != "ACTIVE":
        raise invalid_state("only an ACTIVE permit can be revoked")
    permit["status"] = "REVOKED"
    touch(permit)
    _temp_structure_cascade(permit)
    return success(serialize(permit))
