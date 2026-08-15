"""BeneficialHolder CRUD + position changes + file-schedule."""
from flask import Blueprint, request

from db import db
from errors import (
    ERR_INVALID_REQUEST, ERR_NOT_FOUND, ERR_SCHEDULE_NOT_REQUIRED,
    ERR_FUTURE_EFFECTIVE_DATE, ApiError,
)
from middleware import require_role, get_auth
from response import success_object, success_list
from utils import (
    HOLDER_FIELDS, POSITION_CHANGE_FIELDS, serialize, stamp_created,
    bump_version, parse_pagination, paginate, parse_date, logical_clock_date,
)
from services.calculations import recompute_holder

holders_bp = Blueprint("beneficial_holders", __name__)


def _get_holder_or_404(hid):
    h = db.beneficial_holders.get(hid)
    if not h:
        raise ApiError(ERR_NOT_FOUND, f"BeneficialHolder {hid} not found.", 404)
    return h


@holders_bp.route("/beneficial-holders", methods=["POST"])
def create_holder():
    user_id, role = require_role("ComplianceOfficer")
    body = request.get_json(force=True) or {}

    for f in ["issuer_id", "holder_name"]:
        if f not in body or body[f] is None:
            raise ApiError(ERR_INVALID_REQUEST, f"{f} is required.", 400)

    if body["issuer_id"] not in db.issuers:
        raise ApiError(ERR_INVALID_REQUEST, f"issuer_id {body['issuer_id']} not found.", 400)

    holder = {
        "issuer_id": body["issuer_id"],
        "holder_name": body["holder_name"],
        "holder_cik": body.get("holder_cik"),
        "shares_beneficially_owned": 0,
        "exercisable_derivative_shares": 0,
        "current_pct": 0,
        "fully_diluted_pct": 0,
        "last_reported_pct": None,
        "schedule_type": None,
        "status": "MONITORING",
    }
    stamp_created(holder)
    db.beneficial_holders[holder["id"]] = holder
    return success_object(serialize(holder, HOLDER_FIELDS), 201)


@holders_bp.route("/beneficial-holders", methods=["GET"])
def list_holders():
    get_auth()
    limit, offset = parse_pagination(request.args)
    items = sorted(db.beneficial_holders.values(), key=lambda x: x["created_at"])
    for param in ["issuer_id", "status"]:
        val = request.args.get(param)
        if val:
            items = [h for h in items if str(h.get(param)) == val]
    page, total = paginate(items, limit, offset)
    return success_list([serialize(h, HOLDER_FIELDS) for h in page], limit, offset, total)


@holders_bp.route("/beneficial-holders/<holderId>", methods=["GET"])
def get_holder(holderId):
    get_auth()
    h = _get_holder_or_404(holderId)
    return success_object(serialize(h, HOLDER_FIELDS))


@holders_bp.route("/beneficial-holders/<holderId>/positions", methods=["POST"])
def create_position(holderId):
    user_id, role = require_role("ComplianceOfficer")
    holder = _get_holder_or_404(holderId)
    body = request.get_json(force=True) or {}

    if "shares_delta" not in body or body["shares_delta"] is None:
        raise ApiError(ERR_INVALID_REQUEST, "shares_delta is required.", 400)

    shares_delta = body["shares_delta"]
    if not isinstance(shares_delta, int) or isinstance(shares_delta, bool) or shares_delta == 0:
        raise ApiError(ERR_INVALID_REQUEST, "shares_delta must be a non-zero integer.", 400)

    deriv_delta = body.get("derivative_shares_delta", 0)
    if not isinstance(deriv_delta, int) or isinstance(deriv_delta, bool):
        raise ApiError(ERR_INVALID_REQUEST, "derivative_shares_delta must be an integer.", 400)

    if "effective_date" not in body or body["effective_date"] is None:
        raise ApiError(ERR_INVALID_REQUEST, "effective_date is required.", 400)

    try:
        ed = parse_date(body["effective_date"])
    except (ValueError, TypeError):
        raise ApiError(ERR_INVALID_REQUEST, "effective_date must be YYYY-MM-DD.", 400)

    if ed > logical_clock_date():
        raise ApiError(ERR_FUTURE_EFFECTIVE_DATE, "effective_date is later than logical clock date.", 422)

    pc = {
        "holder_id": holderId,
        "shares_delta": shares_delta,
        "derivative_shares_delta": deriv_delta,
        "effective_date": body["effective_date"],
        "note": body.get("note"),
    }
    # PositionChange has no updated_at / version
    from utils import new_id, now_stamp
    pc["id"] = new_id()
    pc["created_at"] = now_stamp()
    db.position_changes[pc["id"]] = pc

    recompute_holder(holderId)
    return success_object(serialize(pc, POSITION_CHANGE_FIELDS), 201)


@holders_bp.route("/position-changes", methods=["GET"])
def list_position_changes():
    get_auth()
    limit, offset = parse_pagination(request.args)
    items = sorted(db.position_changes.values(), key=lambda x: x["created_at"])
    holder_id = request.args.get("holder_id")
    if holder_id:
        items = [pc for pc in items if pc["holder_id"] == holder_id]
    page, total = paginate(items, limit, offset)
    return success_list([serialize(pc, POSITION_CHANGE_FIELDS) for pc in page], limit, offset, total)


@holders_bp.route("/position-changes/<positionChangeId>", methods=["GET"])
def get_position_change(positionChangeId):
    get_auth()
    pc = db.position_changes.get(positionChangeId)
    if not pc:
        raise ApiError(ERR_NOT_FOUND, f"PositionChange {positionChangeId} not found.", 404)
    return success_object(serialize(pc, POSITION_CHANGE_FIELDS))


@holders_bp.route("/beneficial-holders/<holderId>/file-schedule", methods=["POST"])
def file_schedule(holderId):
    user_id, role = require_role("ComplianceOfficer")
    holder = _get_holder_or_404(holderId)
    body = request.get_json(force=True) or {}

    schedule_type = body.get("schedule_type")
    if schedule_type not in ("SCHEDULE_13D", "SCHEDULE_13G"):
        raise ApiError(ERR_INVALID_REQUEST, "schedule_type must be SCHEDULE_13D or SCHEDULE_13G.", 400)

    if holder["status"] not in ("FILING_REQUIRED", "AMENDMENT_REQUIRED"):
        raise ApiError(ERR_SCHEDULE_NOT_REQUIRED, "file-schedule requires FILING_REQUIRED or AMENDMENT_REQUIRED.", 409)

    holder["status"] = "FILED"
    holder["last_reported_pct"] = holder["current_pct"]
    holder["schedule_type"] = schedule_type
    bump_version(holder)
    return success_object(serialize(holder, HOLDER_FIELDS))
