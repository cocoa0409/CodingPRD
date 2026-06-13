"""Account endpoints incl. disconnect-notice & reconnect-request (PRD §3.2, §3.6)."""
from flask import Blueprint, request

from db import db, base_record, touch
from errors import err
from middleware import authenticate, require_roles, require_owner
from response import success
from services import serializers as ser
from services.common import (
    get_json_body,
    paginate,
    parse_pagination,
    require_fields,
    require_str,
)

bp = Blueprint("accounts", __name__)

READ_ROLES = {"BillingOperator", "Customer", "AssistanceCaseworker", "FieldDispatcher"}
LIST_ROLES = {"BillingOperator", "AssistanceCaseworker"}


@bp.route("/accounts", methods=["POST"])
def create_account():
    _, role = authenticate()
    require_roles(role, {"BillingOperator"})
    body = get_json_body()

    # PRD §3.10 precedence: request-body foreign keys (ERR_FK_NOT_FOUND) are
    # checked BEFORE structural validation of the request body (a missing
    # required field -> ERR_INVALID_REQUEST). So resolve the tariff_id FK first,
    # then validate the remaining required fields. (A wholly absent tariff_id
    # offers no FK to resolve, so it falls through to the structural check.)
    if "tariff_id" in body and body["tariff_id"] is not None:
        tariff = db.tariffs.get(body["tariff_id"])
        if tariff is None:
            raise err("ERR_FK_NOT_FOUND", "Referenced tariff does not exist.")

    require_fields(body, ["tariff_id", "holder_name"])
    tariff_id = body["tariff_id"]
    holder_name = require_str(body, "holder_name")

    tariff = db.tariffs.get(tariff_id)
    if tariff is None:
        raise err("ERR_FK_NOT_FOUND", "Referenced tariff does not exist.")
    if tariff["status"] != "ACTIVE":
        raise err("ERR_TARIFF_NOT_ACTIVE", "Account tariff must be ACTIVE.")

    rec = base_record()
    rec.update({
        "tariff_id": tariff_id,
        "holder_name": holder_name,
        "service_status": "ACTIVE",
        "financial_status": "CURRENT",
        "balance_cents": 0,
        "net_metering_credit_balance_cents": 0,
        "oldest_unpaid_bill_due_date": None,
        "budget_plan_id": None,
    })
    db.accounts[rec["id"]] = rec
    return success(ser.account(rec), status=201)


@bp.route("/accounts/<account_id>", methods=["GET"])
def get_account(account_id):
    user_id, role = authenticate()
    require_roles(role, READ_ROLES)
    rec = db.accounts.get(account_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Account not found.")
    require_owner(role, user_id, account_id)
    return success(ser.account(rec), status=200)


@bp.route("/accounts", methods=["GET"])
def list_accounts():
    _, role = authenticate()
    require_roles(role, LIST_ROLES)
    parse_pagination()
    tariff_id = request.args.get("tariff_id")
    service_status = request.args.get("service_status")
    financial_status = request.args.get("financial_status")
    items = list(db.accounts.values())
    if tariff_id is not None:
        items = [a for a in items if a["tariff_id"] == tariff_id]
    if service_status is not None:
        items = [a for a in items if a["service_status"] == service_status]
    if financial_status is not None:
        items = [a for a in items if a["financial_status"] == financial_status]
    page, pagination = paginate(items)
    return success([ser.account(a) for a in page], status=200, pagination=pagination)


def _has_shielding_grant(account_id):
    """A PLEDGED or APPLIED grant shields the account from disconnect (PRD §3.6)."""
    for g in db.assistance_grants.values():
        if g["account_id"] == account_id and g["status"] in ("PLEDGED", "APPLIED"):
            return True
    return False


@bp.route("/accounts/<account_id>/disconnect-notice", methods=["POST"])
def disconnect_notice(account_id):
    _, role = authenticate()
    require_roles(role, {"BillingOperator"})
    account = db.accounts.get(account_id)
    if account is None:
        raise err("ERR_NOT_FOUND", "Account not found.")

    # Gates in PRD priority order (PRD §3.6, §3.10):
    # 1. assistance shield, 2. arrears requirement, 3. service-state.
    if _has_shielding_grant(account_id):
        raise err("ERR_ASSISTANCE_SHIELD", "Account is shielded by assistance.")
    if account["financial_status"] != "IN_ARREARS":
        raise err("ERR_NOT_IN_ARREARS", "Disconnect requires IN_ARREARS standing.")
    if account["service_status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Disconnect notice requires service ACTIVE.")

    account["service_status"] = "DISCONNECT_PENDING"
    touch(account)

    so = base_record()
    so.update({
        "account_id": account_id,
        "order_type": "DISCONNECT",
        "status": "SCHEDULED",
        "reason": "NONPAY",
    })
    db.service_orders[so["id"]] = so
    return success(ser.service_order(so), status=201)


@bp.route("/accounts/<account_id>/reconnect-request", methods=["POST"])
def reconnect_request(account_id):
    _, role = authenticate()
    require_roles(role, {"BillingOperator"})
    account = db.accounts.get(account_id)
    if account is None:
        raise err("ERR_NOT_FOUND", "Account not found.")

    if account["service_status"] != "DISCONNECTED":
        raise err("ERR_INVALID_STATE", "Reconnect requires service DISCONNECTED.")
    if account["financial_status"] == "IN_ARREARS":
        raise err("ERR_ARREARS_NOT_CLEARED", "Arrears must be cleared first.")

    account["service_status"] = "RECONNECT_PENDING"
    touch(account)

    so = base_record()
    so.update({
        "account_id": account_id,
        "order_type": "RECONNECT",
        "status": "SCHEDULED",
        "reason": "RESTORE_AFTER_PAYMENT",
    })
    db.service_orders[so["id"]] = so
    return success(ser.service_order(so), status=201)
