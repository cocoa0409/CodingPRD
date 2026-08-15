"""Margin call endpoints."""

from flask import Blueprint, request
import db
import errors
from middleware import get_auth, require_roles
from response import success_object, success_list
from services import calculations as calc
from services.state_machines import _touch, default_loan
from routes.helpers import get_or_404, paginate, serialize_common

bp = Blueprint("margin_calls", __name__)

ALL_ROLES = ["DeskAdmin", "DeskTrader", "BorrowerRep", "OwnerRep", "RiskOfficer", "OpsSettler"]


@bp.route("/api/margin-calls/<call_id>", methods=["GET"])
def get_margin_call(call_id):
    user_id, role = get_auth()
    require_roles(role, ALL_ROLES)
    mc = get_or_404(db.margin_calls, call_id, "MarginCall")
    return success_object(serialize_common(mc))


@bp.route("/api/margin-calls", methods=["GET"])
def list_margin_calls():
    user_id, role = get_auth()
    require_roles(role, ALL_ROLES)
    filters = {
        "loan_id": request.args.get("loan_id"),
        "status": request.args.get("status"),
    }
    items = list(db.margin_calls.values())
    if filters["loan_id"]:
        items = [m for m in items if m["loan_id"] == filters["loan_id"]]
    if filters["status"]:
        items = [m for m in items if m["status"] == filters["status"]]
    page, limit, offset, total = paginate(items, request.args)
    return success_list([serialize_common(m) for m in page], limit, offset, total)


@bp.route("/api/margin-calls/<call_id>/declare-default", methods=["POST"])
def declare_default(call_id):
    user_id, role = get_auth()
    require_roles(role, ["RiskOfficer"])
    mc = get_or_404(db.margin_calls, call_id, "MarginCall")
    if mc["status"] != "ESCALATED":
        raise errors.make_error(errors.ERR_INVALID_STATE, "Margin call is not ESCALATED")

    loan = db.loans[mc["loan_id"]]
    if loan["status"] not in ("BOOKED", "RECALLED"):
        raise errors.make_error(errors.ERR_INVALID_STATE, "Loan is not BOOKED or RECALLED")

    mc["status"] = "DEFAULTED"
    _touch(mc)

    default_loan(loan)

    return success_object(serialize_common(mc))
