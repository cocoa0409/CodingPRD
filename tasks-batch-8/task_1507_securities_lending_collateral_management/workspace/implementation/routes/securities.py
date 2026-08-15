"""Security master endpoints."""

from flask import Blueprint, request
import db
import errors
from middleware import get_auth, require_roles, check_list_scope
from response import success_object, success_list
from services import calculations as calc
from services.state_machines import halt_security
from routes.helpers import (
    get_json_body, require_fields, validate_enum, validate_positive_int,
    get_or_404, paginate, serialize_common,
)

bp = Blueprint("securities", __name__)

ALL_ROLES = ["DeskAdmin", "DeskTrader", "BorrowerRep", "OwnerRep", "RiskOfficer", "OpsSettler"]


@bp.route("/api/securities", methods=["POST"])
def create_security():
    user_id, role = get_auth()
    require_roles(role, ["DeskAdmin"])
    body = get_json_body()
    require_fields(body, ["symbol", "asset_class", "price_cents"])
    validate_enum(body["asset_class"], ["EQUITY", "GOV_BOND", "CORP_BOND"], "asset_class")
    validate_positive_int(body["price_cents"], "price_cents")

    # Check unique symbol
    for s in db.securities.values():
        if s["symbol"] == body["symbol"]:
            raise errors.make_error(errors.ERR_VALIDATION, f"Symbol already exists: {body['symbol']}")

    haircut = calc.HAIRCUT_BPS.get(body["asset_class"], 1000)

    sec = {
        "id": db.new_id(),
        "created_at": db.now_iso(),
        "updated_at": db.now_iso(),
        "version": 1,
        "symbol": body["symbol"],
        "asset_class": body["asset_class"],
        "price_cents": body["price_cents"],
        "haircut_bps": haircut,
        "status": "LENDABLE",
    }
    db.securities[sec["id"]] = sec
    return success_object(serialize_common(sec), 201)


@bp.route("/api/securities/<security_id>", methods=["GET"])
def get_security(security_id):
    user_id, role = get_auth()
    require_roles(role, ALL_ROLES)
    sec = get_or_404(db.securities, security_id, "Security")
    return success_object(serialize_common(sec))


@bp.route("/api/securities", methods=["GET"])
def list_securities():
    user_id, role = get_auth()
    require_roles(role, ALL_ROLES)
    filters = {"status": request.args.get("status")}
    items = [s for s in db.securities.values()]
    if filters["status"]:
        items = [s for s in items if s["status"] == filters["status"]]
    page, limit, offset, total = paginate(items, request.args)
    return success_list([serialize_common(s) for s in page], limit, offset, total)


@bp.route("/api/securities/<security_id>/halt", methods=["POST"])
def halt_security_endpoint(security_id):
    user_id, role = get_auth()
    require_roles(role, ["DeskAdmin"])
    sec = get_or_404(db.securities, security_id, "Security")
    if sec["status"] != "LENDABLE":
        raise errors.make_error(errors.ERR_INVALID_STATE, "Security is not LENDABLE")
    halt_security(sec)
    return success_object(serialize_common(sec))


@bp.route("/api/securities/<security_id>/resume", methods=["POST"])
def resume_security(security_id):
    user_id, role = get_auth()
    require_roles(role, ["DeskAdmin"])
    sec = get_or_404(db.securities, security_id, "Security")
    if sec["status"] != "HALTED":
        raise errors.make_error(errors.ERR_INVALID_STATE, "Security is not HALTED")
    sec["status"] = "LENDABLE"
    sec["updated_at"] = db.now_iso()
    sec["version"] += 1
    return success_object(serialize_common(sec))


@bp.route("/api/securities/<security_id>/price", methods=["POST"])
def mark_price(security_id):
    user_id, role = get_auth()
    require_roles(role, ["DeskAdmin"])
    sec = get_or_404(db.securities, security_id, "Security")
    body = get_json_body()
    require_fields(body, ["price_cents"])
    validate_positive_int(body["price_cents"], "price_cents")

    sec["price_cents"] = body["price_cents"]
    sec["updated_at"] = db.now_iso()
    sec["version"] += 1

    # Immediately recompute marked values of ACTIVE pledges on this security
    for p in db.pledges.values():
        if p.get("pledge_security_id") == security_id and p["status"] == "ACTIVE":
            p["marked_value_cents"] = calc.compute_pledge_marked_value(p)
            p["updated_at"] = db.now_iso()
            p["version"] += 1

    # Recompute market_value_cents of open loans in this security
    for loan in db.loans.values():
        if loan["security_id"] == security_id and loan["status"] in ("BOOKED", "RECALLED"):
            calc.recompute_loan_derived(loan)
            calc.evaluate_cure(loan)

    return success_object(serialize_common(sec))
