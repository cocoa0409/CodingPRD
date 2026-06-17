"""Operator endpoints (PRD §3.1)."""
from flask import Blueprint

import db
import errors
from errors import err
from middleware import authenticate, require_role
from response import success, list_response
from helpers import get_json, require_string, pagination_params, paginate

bp = Blueprint("operators", __name__)


def operator_view(op):
    return {
        "id": op["id"],
        "legal_name": op["legal_name"],
        "contact_email": op["contact_email"],
        "account_status": op["account_status"],
        "jeta_month_cumulative_gallons": op["jeta_month_cumulative_gallons"],
        "open_invoice_balance_cents": op["open_invoice_balance_cents"],
        "created_at": op["created_at"],
        "updated_at": op["updated_at"],
        "version": op["version"],
    }


@bp.route("/operators", methods=["POST"])
def create_operator():
    _, role = authenticate()
    require_role(role, {"BillingClerk", "LineManager"})
    body = get_json()
    legal_name = require_string(body, "legal_name")
    contact_email = require_string(body, "contact_email")
    op = db.common_create()
    op.update({
        "legal_name": legal_name,
        "contact_email": contact_email,
        "account_status": "ACTIVE",
        "jeta_month_cumulative_gallons": 0,
        "open_invoice_balance_cents": 0,
    })
    db.operators[op["id"]] = op
    return success(operator_view(op), 201)


@bp.route("/operators/<id>", methods=["GET"])
def get_operator(id):
    user_id, role = authenticate()
    require_role(role, {"OpsDispatcher", "FuelTech", "BillingClerk", "LineManager", "Operator"})
    op = db.operators.get(id)
    if op is None:
        raise err(errors.ERR_NOT_FOUND, "Operator not found.")
    if role == "Operator" and user_id != op["id"]:
        raise err(errors.ERR_NOT_RESOURCE_OWNER, "Operator may read only its own record.")
    return success(operator_view(op), 200)
