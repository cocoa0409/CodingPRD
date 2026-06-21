"""MissedPickupCredit endpoints (PRD §3.7)."""
from flask import request, Blueprint

from db import db, touch
from errors import err
from middleware import authenticate, require_owner, require_roles
from response import success
from services import billing
from services import serializers as ser
from services.common import paginate, parse_pagination

bp = Blueprint("credits", __name__)


@bp.route("/missed-pickup-credits/<credit_id>", methods=["GET"])
def get_credit(credit_id):
    user_id, role = authenticate()
    require_roles(role, {"Billing", "ResidentAccount"})
    rec = db.credits.get(credit_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Missed-pickup credit not found.")
    require_owner(role, user_id, rec["account_id"])
    return success(ser.missed_pickup_credit(rec), status=200)


@bp.route("/missed-pickup-credits", methods=["GET"])
def list_credits():
    user_id, role = authenticate()
    require_roles(role, {"Billing", "ResidentAccount"})
    parse_pagination()
    items = list(db.credits.values())
    if role == "ResidentAccount":
        items = [c for c in items if c["account_id"] == user_id]
    account_id = request.args.get("account_id")
    status = request.args.get("status")
    source_pickup_id = request.args.get("source_pickup_id")
    source_special_pickup_id = request.args.get("source_special_pickup_id")
    applied_invoice_id = request.args.get("applied_invoice_id")
    if account_id is not None:
        items = [c for c in items if c["account_id"] == account_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    if source_pickup_id is not None:
        items = [c for c in items if c["source_pickup_id"] == source_pickup_id]
    if source_special_pickup_id is not None:
        items = [c for c in items if c["source_special_pickup_id"] == source_special_pickup_id]
    if applied_invoice_id is not None:
        items = [c for c in items if c["applied_invoice_id"] == applied_invoice_id]
    page, pagination = paginate(items)
    return success([ser.missed_pickup_credit(c) for c in page], status=200, pagination=pagination)


@bp.route("/missed-pickup-credits/<credit_id>/void", methods=["POST"])
def void_credit(credit_id):
    _, role = authenticate()
    require_roles(role, {"Billing"})
    rec = db.credits.get(credit_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Missed-pickup credit not found.")
    if rec["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Only a PENDING credit can be voided.")
    rec["status"] = "VOID"
    touch(rec)
    billing.recompute_account_balance(rec["account_id"])
    return success(ser.missed_pickup_credit(rec), status=200)
