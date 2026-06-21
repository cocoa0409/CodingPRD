"""Accounts: get, list, courtesy-pay, freeze/unfreeze/close, dormancy/escheat,
stop-expiry, interest posting — PRD §3.4-§3.11."""
from flask import Blueprint, request, g

from db import db, parse_date
from middleware import require_roles
from response import object_response
from models import public, touch
from services.validate import get_body, require_fields
from services.resolve import get_account, require_account_owner
from services import ledger
from services import account_ops
from routes.common import paged_list
import errors
from errors import ApiError

bp = Blueprint("accounts", __name__)


def serialize_account(acct):
    ledger.serialize_account(acct)
    return public(acct)


@bp.route("/accounts/<account_id>", methods=["GET"])
@require_roles("Teller", "ComplianceOfficer", "AccountHolder")
def get_one(account_id):
    a = get_account(account_id)
    return object_response(serialize_account(a))


@bp.route("/accounts", methods=["GET"])
@require_roles("Teller", "ComplianceOfficer")
def list_accounts():
    origin_application_id = request.args.get("origin_application_id")
    apy_tier_code = request.args.get("apy_tier_code")
    status = request.args.get("status")
    rows = list(db.accounts.values())
    if origin_application_id is not None:
        rows = [a for a in rows if a["origin_application_id"] == origin_application_id]
    if apy_tier_code is not None:
        rows = [a for a in rows if a["apy_tier_code"] == apy_tier_code]
    if status is not None:
        rows = [a for a in rows if a["status"] == status]
    return paged_list(rows, serializer=serialize_account)


@bp.route("/accounts/<account_id>/courtesy-pay", methods=["POST"])
@require_roles("AccountHolder")
def courtesy_pay(account_id):
    a = get_account(account_id)
    require_account_owner(a, g.user_id)
    body = get_body()
    require_fields(body, "courtesy_pay_opted_in")
    opted = body["courtesy_pay_opted_in"]
    if not isinstance(opted, bool):
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, "courtesy_pay_opted_in must be a boolean")
    a["courtesy_pay_opted_in"] = opted
    if "courtesy_pay_limit_cents" in body and body["courtesy_pay_limit_cents"] is not None:
        limit = body["courtesy_pay_limit_cents"]
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
            raise ApiError(errors.ERR_INVALID_REQUEST, 422,
                           "courtesy_pay_limit_cents must be a non-negative integer")
        a["courtesy_pay_limit_cents"] = limit
    touch(a)
    return object_response(serialize_account(a))


@bp.route("/accounts/<account_id>/freeze", methods=["POST"])
@require_roles("ComplianceOfficer")
def freeze(account_id):
    a = get_account(account_id)
    if a["status"] != "ACTIVE":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Account is not ACTIVE")
    a["status"] = "FROZEN"
    touch(a)
    return object_response(serialize_account(a))


@bp.route("/accounts/<account_id>/unfreeze", methods=["POST"])
@require_roles("ComplianceOfficer")
def unfreeze(account_id):
    a = get_account(account_id)
    if a["status"] != "FROZEN":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Account is not FROZEN")
    a["status"] = "ACTIVE"
    touch(a)
    return object_response(serialize_account(a))


@bp.route("/accounts/<account_id>/close", methods=["POST"])
@require_roles("AccountHolder")
def close(account_id):
    a = get_account(account_id)
    require_account_owner(a, g.user_id)
    # State gate (priority 5).
    if a["status"] != "ACTIVE":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Account is not ACTIVE")
    # Zero-balance gate (priority 11) precedes pending-items gate (priority 12).
    if ledger.ledger_balance(a["id"]) != 0:
        raise ApiError(errors.ERR_NONZERO_BALANCE, 409, "Account balance is not zero")
    # No PENDING transactions and no STAGED AchLeg referencing this account.
    has_pending = any(
        t["account_id"] == a["id"] and t["status"] == "PENDING"
        for t in db.transactions.values()
    )
    has_staged_leg = _account_has_staged_leg(a["id"])
    if has_pending or has_staged_leg:
        raise ApiError(errors.ERR_PENDING_ITEMS, 409, "Account has pending items")

    a["status"] = "CLOSED"
    touch(a)
    account_ops.expire_active_stops(a["id"])
    # Deactivate JOINT/POD owners; PRIMARY records remain.
    for o in db.account_owners.values():
        if o["account_id"] == a["id"] and o["is_active"] and o["ownership_role"] in ("JOINT", "POD_BENEFICIARY"):
            o["is_active"] = False
            touch(o)
    return object_response(serialize_account(a))


def _account_has_staged_leg(account_id):
    """True if any STAGED AchOrigination has a leg whose role hits this account."""
    for orig in db.ach_originations.values():
        if orig["status"] != "STAGED":
            continue
        if orig["debtor_account_id"] != account_id and orig["creditor_account_id"] != account_id:
            continue
        for leg in db.ach_legs.values():
            if leg["ach_origination_id"] != orig["id"]:
                continue
            if leg["leg_role"] == "DEBIT" and orig["debtor_account_id"] == account_id:
                return True
            if leg["leg_role"] == "CREDIT" and orig["creditor_account_id"] == account_id:
                return True
    return False


@bp.route("/accounts/<account_id>/run-dormancy-scan", methods=["POST"])
@require_roles("ComplianceOfficer")
def run_dormancy_scan(account_id):
    a = get_account(account_id)
    if a["status"] != "ACTIVE":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Account is not ACTIVE")
    if account_ops.inactivity_days(a) < a["dormancy_threshold_days"]:
        raise ApiError(errors.ERR_DORMANCY_NOT_DUE, 409, "Dormancy not yet due")
    a["status"] = "DORMANT"
    touch(a)
    return object_response(serialize_account(a))


@bp.route("/accounts/<account_id>/run-escheat-sweep", methods=["POST"])
@require_roles("ComplianceOfficer")
def run_escheat_sweep(account_id):
    a = get_account(account_id)
    if a["status"] != "DORMANT":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Account is not DORMANT")
    if account_ops.inactivity_days(a) < a["escheat_threshold_days"]:
        raise ApiError(errors.ERR_ESCHEAT_NOT_DUE, 409, "Escheat not yet due")
    account_ops.run_escheat(a)
    return object_response(serialize_account(a))


@bp.route("/accounts/<account_id>/run-stop-expiry", methods=["POST"])
@require_roles("ComplianceOfficer")
def run_stop_expiry(account_id):
    a = get_account(account_id)
    account_ops.run_stop_expiry(a["id"])
    return object_response(serialize_account(a))


@bp.route("/accounts/<account_id>/post-interest", methods=["POST"])
@require_roles("ComplianceOfficer")
def post_interest(account_id):
    a = get_account(account_id)
    body = get_body()
    require_fields(body, "period_start_date", "period_end_date")
    start = body["period_start_date"]
    end = body["period_end_date"]
    # Validate parseable dates.
    try:
        ps = parse_date(start)
        pe = parse_date(end)
    except (ValueError, TypeError):
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, "Invalid period date")
    if ps is None or pe is None:
        raise ApiError(errors.ERR_INVALID_REQUEST, 422, "Invalid period date")
    # Interest-period overlap (priority 15); adjacency allowed.
    if account_ops.interest_periods_overlap(a["id"], start, end):
        raise ApiError(errors.ERR_INTEREST_PERIOD_OVERLAP, 409,
                       "Interest period overlaps an existing posting")
    posting = account_ops.post_interest(a, start, end)
    return object_response(public(posting), status=201)
