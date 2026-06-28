"""Position / Lot / Disposal endpoints (PRD §3.5, §4)."""
from flask import Blueprint, request

import errors
from db import db
from middleware import get_identity, require_role, require_account_owner
from models import position_dict, lot_dict, disposal_dict, touch
from response import object_response, array_response
from routes.common import (get_json_body, get_position, paginate, page_slice)
from services.account import recompute_account

bp = Blueprint("positions", __name__)


@bp.get("/positions/<position_id>")
def get_position_ep(position_id):
    user_id, role = get_identity()
    require_role(role, {"AccountHolder", "ClearingSystem", "ComplianceOfficer"})
    pos = get_position(position_id)
    require_account_owner(role, user_id, pos["account_id"])
    return object_response(position_dict(pos), 200)


@bp.get("/positions")
def list_positions():
    user_id, role = get_identity()
    require_role(role, {"AccountHolder", "ClearingSystem", "ComplianceOfficer"})

    account_id = request.args.get("account_id")
    security_id = request.args.get("security_id")

    items = list(db.positions.values())
    if role == "AccountHolder":
        items = [p for p in items if p["account_id"] == user_id]
    if account_id is not None:
        items = [p for p in items if p["account_id"] == account_id]
    if security_id is not None:
        items = [p for p in items if p["security_id"] == security_id]

    limit, offset = paginate()
    page, total = page_slice(items, limit, offset)
    return array_response([position_dict(p) for p in page], limit, offset, total)


@bp.patch("/positions/<position_id>/drip")
def set_drip(position_id):
    user_id, role = get_identity()
    require_role(role, {"AccountHolder"})
    pos = get_position(position_id)
    require_account_owner(role, user_id, pos["account_id"])
    body = get_json_body()

    enabled = body.get("drip_enabled")
    if not isinstance(enabled, bool):
        raise errors.err(errors.ERR_INVALID_REQUEST, "drip_enabled must be a boolean")

    pos["drip_enabled"] = enabled
    touch(pos)  # increments Position.version by 1
    return object_response(position_dict(pos), 200)


@bp.get("/positions/<position_id>/lots")
def list_lots(position_id):
    user_id, role = get_identity()
    require_role(role, {"AccountHolder", "ClearingSystem", "ComplianceOfficer"})
    pos = get_position(position_id)
    require_account_owner(role, user_id, pos["account_id"])

    status = request.args.get("status")
    items = [l for l in db.lots.values() if l["position_id"] == position_id]
    if status is not None:
        items = [l for l in items if l["status"] == status]

    limit, offset = paginate()
    page, total = page_slice(items, limit, offset)
    return array_response([lot_dict(l) for l in page], limit, offset, total)


@bp.get("/positions/<position_id>/disposals")
def list_disposals(position_id):
    user_id, role = get_identity()
    require_role(role, {"AccountHolder", "ClearingSystem", "ComplianceOfficer"})
    pos = get_position(position_id)
    require_account_owner(role, user_id, pos["account_id"])

    term = request.args.get("term")
    items = [d for d in db.disposals.values() if d["position_id"] == position_id]
    if term is not None:
        items = [d for d in items if d["term"] == term]

    limit, offset = paginate()
    page, total = page_slice(items, limit, offset)
    return array_response([disposal_dict(d) for d in page], limit, offset, total)
