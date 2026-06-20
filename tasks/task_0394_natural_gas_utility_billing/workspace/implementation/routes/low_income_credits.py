"""Low-income credit endpoints (PRD §3.8)."""

from flask import Blueprint

from db import store
from errors import ERR_INVALID_STATE, ERR_NOT_ELIGIBLE, err
from middleware import authenticate, require_role, require_account_ownership
from response import success
from services.common import (
    get_body,
    require_fields,
    require_int,
    attach_common_fields,
    bump,
    paginate,
)
from services.serialize import view_low_income_credit
from services import lookup, calc

bp = Blueprint("low_income_credits", __name__)


@bp.route("/accounts/<account_id>/low-income-credits", methods=["POST"])
def submit_credit(account_id):
    principal = authenticate()
    require_role(principal, {"CustomerService", "Account"})
    with store.lock:
        account = lookup.get_account(account_id)
        require_account_ownership(principal, account_id)
        body = get_body()
        require_fields(body, ["household_size", "annual_income_cents"])
        household_size = require_int(body, "household_size", minimum=1)
        annual_income_cents = require_int(body, "annual_income_cents", minimum=0)

        tier = calc.compute_low_income_tier(household_size, annual_income_cents)
        rec = {
            "account_id": account_id,
            "household_size": household_size,
            "annual_income_cents": annual_income_cents,
            "tier": tier,
            "status": "SUBMITTED",
        }
        attach_common_fields(rec)
        store.low_income_credits[rec["id"]] = rec
        return success(view_low_income_credit(rec), 201)


@bp.route("/accounts/<account_id>/low-income-credits", methods=["GET"])
def list_credits(account_id):
    principal = authenticate()
    require_role(principal, {"BillingAdmin", "CustomerService", "Account"})
    account = lookup.get_account(account_id)
    require_account_ownership(principal, account_id)
    records = [c for c in store.low_income_credits.values() if c["account_id"] == account_id]
    page, list_meta = paginate(records)
    return success([view_low_income_credit(c) for c in page], 200, list_meta=list_meta)


@bp.route("/accounts/<account_id>/low-income-credits/<credit_id>/approve", methods=["POST"])
def approve_credit(account_id, credit_id):
    principal = authenticate()
    require_role(principal, {"CustomerService"})
    with store.lock:
        account = lookup.get_account(account_id)
        credit = lookup.get_credit_under_account(account_id, credit_id)
        if credit["status"] != "SUBMITTED":
            raise err(ERR_INVALID_STATE, "Credit is not SUBMITTED")
        if credit["tier"] == "NONE":
            raise err(ERR_NOT_ELIGIBLE, "Computed tier is NONE")
        credit["status"] = "APPROVED"
        bump(credit)
        account["low_income_status"] = "ENROLLED"
        account["low_income_tier"] = credit["tier"]
        return success(view_low_income_credit(credit), 200)


@bp.route("/accounts/<account_id>/low-income-credits/<credit_id>/deny", methods=["POST"])
def deny_credit(account_id, credit_id):
    principal = authenticate()
    require_role(principal, {"CustomerService"})
    with store.lock:
        account = lookup.get_account(account_id)
        credit = lookup.get_credit_under_account(account_id, credit_id)
        if credit["status"] != "SUBMITTED":
            raise err(ERR_INVALID_STATE, "Credit is not SUBMITTED")
        credit["status"] = "DENIED"
        bump(credit)
        return success(view_low_income_credit(credit), 200)


@bp.route("/accounts/<account_id>/low-income-credits/<credit_id>/expire", methods=["POST"])
def expire_credit(account_id, credit_id):
    principal = authenticate()
    require_role(principal, {"BillingAdmin"})
    with store.lock:
        account = lookup.get_account(account_id)
        credit = lookup.get_credit_under_account(account_id, credit_id)
        if credit["status"] != "APPROVED":
            raise err(ERR_INVALID_STATE, "Credit is not APPROVED")
        credit["status"] = "EXPIRED"
        bump(credit)
        # If no other APPROVED credit remains, reset account low-income fields.
        other_approved = any(
            c["account_id"] == account_id and c["status"] == "APPROVED"
            for c in store.low_income_credits.values()
        )
        if not other_approved:
            account["low_income_status"] = "NONE"
            account["low_income_tier"] = "NONE"
        return success(view_low_income_credit(credit), 200)
