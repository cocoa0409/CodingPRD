"""Creditor endpoints."""
from flask import Blueprint

from db import db, stamp_create
from errors import ApiError, ERR_NOT_FOUND
from middleware import require_roles
from response import object_response
from serializers import serialize_creditor
from validation import get_body, require_str, require_int, optional_enum, optional_int, invalid

bp = Blueprint("creditors", __name__)

COMMISSION_BASES = {"GROSS_OF_FEES", "NET_OF_FEES"}


@bp.route("/creditors", methods=["POST"])
@require_roles("Creditor")
def create_creditor():
    body = get_body()
    name = require_str(body, "name")
    basis = optional_enum(body, "commission_basis", COMMISSION_BASES, default="GROSS_OF_FEES")
    rate = require_int(body, "commission_rate_bps")
    if rate < 0 or rate > 10000:
        invalid("commission_rate_bps must be between 0 and 10000 inclusive")
    expense = optional_int(body, "expense_recovery_cents", default=0)
    if expense < 0:
        invalid("expense_recovery_cents must be >= 0")
    c = stamp_create({
        "name": name,
        "commission_basis": basis,
        "commission_rate_bps": rate,
        "expense_recovery_cents": expense,
    })
    db.creditors[c["id"]] = c
    return object_response(serialize_creditor(c), status=201)


@bp.route("/creditors/<cid>", methods=["GET"])
@require_roles("Creditor", "Collector", "ComplianceOfficer", "BureauOperator", "System")
def get_creditor(cid):
    c = db.creditors.get(cid)
    if c is None:
        raise ApiError(*ERR_NOT_FOUND, message="Creditor not found")
    return object_response(serialize_creditor(c), status=200)
