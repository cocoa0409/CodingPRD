"""ContractorAccount endpoints (PRD section 3.2)."""
from flask import Blueprint, request

from db import db
from helpers import (
    get_account, check_account_owner, paginate,
)
from middleware import require_auth, require_role
from response import success
import serialize
import validate

bp = Blueprint("contractor_accounts", __name__)


@bp.post("/contractor-accounts")
def create_account():
    _, role = require_auth()
    require_role(role, ["YardAdmin"])
    body = validate.get_json_body()
    validate.require_fields(body, ["business_name", "credit_limit_cents"])
    business_name = validate.require_string(body, "business_name")
    credit_limit_cents = validate.require_non_negative_int(body, "credit_limit_cents")

    rec = db.insert_with_common(db.contractor_accounts, {
        "business_name": business_name,
        "credit_limit_cents": credit_limit_cents,
        "status": "ACTIVE",
    })
    return success(serialize.contractor_account(rec), status=201)


@bp.get("/contractor-accounts")
def list_accounts():
    _, role = require_auth()
    require_role(role, ["YardAdmin", "BillingClerk", "Dispatcher"])
    limit, offset = validate.get_pagination()
    status = request.args.get("status")
    records = list(db.contractor_accounts.values())
    if status is not None:
        records = [r for r in records if r["status"] == status]
    return paginate(records, serialize.contractor_account, limit, offset)


@bp.get("/contractor-accounts/<account_id>")
def get_account_ep(account_id):
    user_id, role = require_auth()
    require_role(role, ["YardAdmin", "BillingClerk", "Dispatcher", "Contractor"])
    rec = get_account(account_id)
    check_account_owner(rec, role, user_id)
    return success(serialize.contractor_account(rec), status=200)


@bp.post("/contractor-accounts/<account_id>/suspend")
def suspend_account(account_id):
    _, role = require_auth()
    require_role(role, ["YardAdmin", "BillingClerk"])
    rec = get_account(account_id)
    rec["status"] = "SUSPENDED"
    db.touch(rec)
    return success(serialize.contractor_account(rec), status=200)


@bp.post("/contractor-accounts/<account_id>/reinstate")
def reinstate_account(account_id):
    _, role = require_auth()
    require_role(role, ["YardAdmin", "BillingClerk"])
    rec = get_account(account_id)
    rec["status"] = "ACTIVE"
    db.touch(rec)
    return success(serialize.contractor_account(rec), status=200)


@bp.get("/contractor-accounts/<account_id>/orders")
def list_account_orders(account_id):
    user_id, role = require_auth()
    require_role(role, ["YardAdmin", "BillingClerk", "Dispatcher", "Contractor"])
    rec = get_account(account_id)
    check_account_owner(rec, role, user_id)
    limit, offset = validate.get_pagination()
    records = [o for o in db.rental_orders.values() if o["account_id"] == account_id]
    return paginate(records, serialize.rental_order, limit, offset)


@bp.get("/contractor-accounts/<account_id>/invoices")
def list_account_invoices(account_id):
    user_id, role = require_auth()
    require_role(role, ["YardAdmin", "BillingClerk", "Contractor"])
    rec = get_account(account_id)
    check_account_owner(rec, role, user_id)
    limit, offset = validate.get_pagination()
    status = request.args.get("status")
    records = [i for i in db.invoices.values() if i["account_id"] == account_id]
    if status is not None:
        records = [i for i in records if i["status"] == status]
    return paginate(records, serialize.invoice, limit, offset)
