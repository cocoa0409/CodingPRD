"""Lender + simulated-clock endpoints (§3.1)."""
from flask import Blueprint

import db
import errors
from middleware import get_user_context, require_role
from response import success
from serializers import public
from services import common, clock

bp = Blueprint("lenders", __name__)


@bp.route("/lenders", methods=["POST"])
def create_lender():
    _, role = get_user_context()
    require_role(role, {"ServicerOps"})
    body = common.get_json_body()
    common.require_fields(body, ["name"])
    if not isinstance(body["name"], str):
        raise errors.err(errors.ERR_INVALID_REQUEST, "name must be a string")
    hud_limit = common.require_positive_int(body, "hud_lending_limit_cents")
    rec = {
        "name": body["name"],
        "hud_lending_limit_cents": hud_limit,
        "clock_utc": "1970-01-01T00:00:00.000Z",
    }
    db.stamp_create(rec)
    db.lenders[rec["id"]] = rec
    return success(public(rec), status=201)


@bp.route("/lenders/<lender_id>", methods=["GET"])
def get_lender(lender_id):
    _, role = get_user_context()
    require_role(role, {"ServicerOps", "ComplianceOfficer", "HudAuditor", "Borrower"})
    rec = db.lenders.get(lender_id)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Lender not found")
    return success(public(rec))


@bp.route("/loans/_clock/set", methods=["POST"])
def set_clock():
    _, role = get_user_context()
    require_role(role, {"System", "ServicerOps"})
    body = common.get_json_body()
    common.require_fields(body, ["lender_id", "to_iso8601"])
    lender = db.lenders.get(body["lender_id"])
    if lender is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Lender not found")
    to_iso = body["to_iso8601"]
    if not isinstance(to_iso, str) or "T" not in to_iso:
        raise errors.err(errors.ERR_INVALID_REQUEST, "to_iso8601 must be an ISO 8601 string")
    lender["clock_utc"] = to_iso
    db.touch(lender)
    clock.run_occupancy_sweep(lender)
    return success(public(lender))
