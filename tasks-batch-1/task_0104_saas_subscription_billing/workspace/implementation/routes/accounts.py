"""Account routes: register, get, close (PRD §3.2, §3.9)."""
from flask import Blueprint

import errors
import serializers as S
import validate as V
from db import db, stamp_new, touch
from middleware import authenticate, require_role, require_account_owner_match
from response import success

bp = Blueprint("accounts", __name__)


@bp.route("/accounts", methods=["POST"])
def create_account():
    role, _ = authenticate()
    require_role(role, {"Anonymous"})
    body = V.get_body()

    email = V.require_str(body, "email")
    company_name = V.require_str(body, "company_name")
    region_code = V.require_str(body, "region_code")
    payment_method_ok = V.optional_bool(body, "payment_method_ok", default=True)

    # Uniqueness (priority 6) before business-referential jurisdiction (priority 8).
    for a in db.accounts.values():
        if a["email"] == email:
            raise errors.duplicate(f"Account email {email} already exists")

    # Resolve jurisdiction from region_code (priority 8 -> ERR_JURISDICTION_NOT_FOUND).
    jurisdiction = None
    for j in db.tax_jurisdictions.values():
        if j["region_code"] == region_code:
            jurisdiction = j
            break
    if jurisdiction is None:
        raise errors.jurisdiction_not_found(
            f"No tax jurisdiction matches region_code {region_code}")

    account = {
        "email": email,
        "company_name": company_name,
        "region_code": region_code,
        "tax_jurisdiction_id": jurisdiction["id"],
        "payment_method_ok": payment_method_ok,
        "mrr_cents": 0,
        "status": "ACTIVE",
    }
    stamp_new(account)
    db.accounts[account["id"]] = account
    return success(S.ser_account(account), status=201)


@bp.route("/accounts/<id>", methods=["GET"])
def get_account(id):
    role, user_id = authenticate()
    require_role(role, {"BillingAdmin", "AccountOwner"})
    account = db.accounts.get(id)
    if account is None:
        raise errors.not_found("Account not found")
    require_account_owner_match(role, user_id, id)
    return success(S.ser_account(account))


@bp.route("/accounts/<id>/close", methods=["POST"])
def close_account(id):
    role, user_id = authenticate()
    require_role(role, {"AccountOwner"})
    account = db.accounts.get(id)
    if account is None:
        raise errors.not_found("Account not found")
    require_account_owner_match(role, user_id, id)

    if account["status"] != "ACTIVE":
        raise errors.invalid_state("Account is not ACTIVE")

    # Blocked while live commitments remain (PRD §3.9).
    for sub in db.subscriptions.values():
        if sub["account_id"] == id and sub["lifecycle_status"] in ("TRIALING", "ACTIVE"):
            raise errors.ApiError(errors.ERR_ACCOUNT_HAS_ACTIVE_SUBS, 409,
                                  "Account has a TRIALING or ACTIVE subscription")
    for inv in db.invoices.values():
        if inv["account_id"] == id and inv["status"] in ("OPEN", "PAST_DUE"):
            raise errors.ApiError(errors.ERR_ACCOUNT_HAS_OPEN_INVOICES, 409,
                                  "Account has an OPEN or PAST_DUE invoice")

    account["status"] = "CLOSED"
    account["mrr_cents"] = 0
    touch(account)
    return success(S.ser_account(account))
