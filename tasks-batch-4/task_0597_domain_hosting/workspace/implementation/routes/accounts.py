"""Accounts, store credit and the suspension posture (PRD 3.1)."""

from flask import Blueprint

import config
import db
import middleware as mw
import response
import validation as v
from services import cascades, money
from services.serializers import account_out, ledger_out

bp = Blueprint("accounts", __name__)


@bp.post("/accounts")
@mw.roles_required("Anonymous")
def create_account():
    data = v.body()
    email = v.req_str(data, "email")
    company_name = v.req_str(data, "company_name")
    auto_renew_default = v.opt_bool(data, "auto_renew_default", True)

    for existing in db.accounts.values():
        if existing["email"] == email:
            raise v.bad("An account with this email already exists.")

    account = db.base_record()
    account.update(
        {
            "email": email,
            "company_name": company_name,
            "status": "ACTIVE",
            "payment_method_token": None,
            "auto_renew_default": auto_renew_default,
            "credit_balance_cents": 0,
            "net_cash_cents": 0,
            "risk_score": 0,
        }
    )
    db.accounts[account["id"]] = account
    return response.created(account_out(account))


@bp.get("/accounts/<account_id>")
@mw.roles_required(
    "Registrant", "SupportAgent", "BillingAdmin", "AbuseAnalyst", "PlatformAdmin"
)
def read_account(account_id):
    account = v.get_account(account_id)
    mw.require_owner(account["id"])
    return response.ok(account_out(account))


@bp.post("/accounts/<account_id>/payment-method")
@mw.roles_required("Registrant", "BillingAdmin")
def attach_payment_method(account_id):
    data = v.body()
    card_token = v.req_str(data, "card_token")
    account = v.get_account(account_id)
    mw.require_owner(account["id"])
    mw.gate_account_suspended()

    account["payment_method_token"] = card_token
    db.touch(account)
    return response.ok(account_out(account))


@bp.post("/accounts/<account_id>/credits")
@mw.roles_required("BillingAdmin")
def grant_credit(account_id):
    data = v.body()
    amount_cents = v.req_int(data, "amount_cents", minimum=0)
    reason = v.req_str(data, "reason")
    account = v.get_account(account_id)

    entry = money.write_ledger(
        account, "CREDIT_GRANT", amount_cents, "ADJUSTMENT", None, reason
    )
    return response.created(ledger_out(entry))


@bp.get("/accounts/<account_id>/ledger-entries")
@mw.roles_required("Registrant", "BillingAdmin", "PlatformAdmin")
def list_ledger_entries(account_id):
    limit, offset = v.pagination()
    entry_type = v.query_enum("entry_type", config.LEDGER_ENTRY_TYPES)
    account = v.get_account(account_id)
    mw.require_owner(account["id"])

    rows = db.ordered(
        db.ledger_entries,
        lambda e: e["account_id"] == account["id"]
        and (entry_type is None or e["entry_type"] == entry_type),
    )
    page, total = v.paginate(rows, limit, offset, ledger_out)
    return response.listing(page, limit, offset, total)


@bp.post("/accounts/<account_id>/reinstate")
@mw.roles_required("SupportAgent")
def reinstate_account(account_id):
    data = v.body()
    v.req_str(data, "reason")
    account = v.get_account(account_id)

    if account["status"] == "SUSPENDED":
        cascades.reinstate_account(account)
    return response.ok(account_out(account))
