"""Account routes: registration, two-dimensional lifecycle (KYC + billing),
sweep, close, reads, and cash-transaction listing (PRD §3.2, §3.3, §3.5, §3.12).
"""

from flask import Blueprint, request

from db import store
from errors import err
from middleware import get_json, require_auth, require_owner
from models import (
    create_cash_transaction,
    new_entity,
    recompute_pending_roundup,
    serialize,
    touch,
)
from response import success
from routes.helpers import (
    fetch_or_404,
    list_response,
    require_int,
    require_str,
)
from services.calc import subscription_fee
from services.settlement import run_sweep

bp = Blueprint("accounts", __name__)


# ---------------------------------------------------------------------------
# Registration (PRD §3.2)
# ---------------------------------------------------------------------------
@bp.route("/accounts/register", methods=["POST"])
def register():
    require_auth({"Anonymous"})
    body = get_json()
    email = require_str(body, "email")
    full_name = require_str(body, "full_name")
    plan_id = require_str(body, "plan_id")
    model_portfolio_id = require_str(body, "model_portfolio_id")
    sweep_threshold = require_int(body, "sweep_threshold_cents", minimum=100, required=False)
    if sweep_threshold is None:
        sweep_threshold = 500

    # Existence of referenced ids (priority 4).
    fetch_or_404(store.subscription_plans, plan_id)
    fetch_or_404(store.model_portfolios, model_portfolio_id)

    # Email unique across accounts (PRD §3.2).
    for a in store.accounts.values():
        if a["email"] == email:
            raise err("ERR_INVALID_REQUEST", "Email already registered.")

    account = new_entity(
        {
            "email": email,
            "full_name": full_name,
            "plan_id": plan_id,
            "model_portfolio_id": model_portfolio_id,
            "kyc_status": "PENDING_KYC",
            "billing_status": "TRIAL",
            "cash_balance_cents": 0,
            "pending_roundup_cents": 0,
            "lifetime_invested_cents": 0,
            "referral_credits_cents": 0,
            "months_billed": 0,
            "sweep_threshold_cents": sweep_threshold,
        }
    )
    store.accounts[account["id"]] = account
    return success(serialize(account), status=201)


@bp.route("/accounts/<entity_id>", methods=["GET"])
def get_account(entity_id):
    role, user_id = require_auth({"PlatformAdmin", "Investor", "CustodialGuardian"})
    account = fetch_or_404(store.accounts, entity_id)
    require_owner(role, user_id, account["id"])
    return success(serialize(account))


@bp.route("/accounts", methods=["GET"])
def list_accounts():
    require_auth({"PlatformAdmin"})
    items = list(store.accounts.values())
    plan_id = request.args.get("plan_id")
    model_portfolio_id = request.args.get("model_portfolio_id")
    kyc_status = request.args.get("kyc_status")
    billing_status = request.args.get("billing_status")
    if plan_id is not None:
        items = [a for a in items if a["plan_id"] == plan_id]
    if model_portfolio_id is not None:
        items = [a for a in items if a["model_portfolio_id"] == model_portfolio_id]
    if kyc_status is not None:
        items = [a for a in items if a["kyc_status"] == kyc_status]
    if billing_status is not None:
        items = [a for a in items if a["billing_status"] == billing_status]
    data, pagination = list_response(items)
    return success(data, pagination=pagination)


# ---------------------------------------------------------------------------
# KYC dimension (PRD §3.2)
# ---------------------------------------------------------------------------
@bp.route("/accounts/<entity_id>/verify-kyc", methods=["POST"])
def verify_kyc(entity_id):
    require_auth({"PlatformAdmin"})
    account = fetch_or_404(store.accounts, entity_id)
    if account["kyc_status"] != "PENDING_KYC":
        raise err("ERR_INVALID_STATE", "Account is not PENDING_KYC.")
    account["kyc_status"] = "VERIFIED"
    touch(account)
    return success(serialize(account))


@bp.route("/accounts/<entity_id>/restrict", methods=["POST"])
def restrict(entity_id):
    require_auth({"PlatformAdmin"})
    account = fetch_or_404(store.accounts, entity_id)
    if account["kyc_status"] not in ("PENDING_KYC", "VERIFIED"):
        raise err("ERR_INVALID_STATE", "Account cannot be restricted from its current state.")
    account["kyc_status"] = "RESTRICTED"
    # Cascade: freeze every OPEN bucket of the account (PRD §3.2).
    for b in store.buckets.values():
        if b["account_id"] == account["id"] and b["status"] == "OPEN":
            b["status"] = "FROZEN"
            touch(b)
    touch(account)
    return success(serialize(account))


# ---------------------------------------------------------------------------
# Billing dimension (PRD §3.2, §3.3)
# ---------------------------------------------------------------------------
@bp.route("/accounts/<entity_id>/billing/charge-subscription", methods=["POST"])
def charge_subscription(entity_id):
    require_auth({"PlatformAdmin"})
    account = fetch_or_404(store.accounts, entity_id)
    plan = store.subscription_plans[account["plan_id"]]

    billing = account["billing_status"]
    if billing in ("TRIAL", "ACTIVE"):
        pass  # TRIAL->ACTIVE or ACTIVE->ACTIVE
    elif billing == "PAST_DUE":
        # PAST_DUE -> ACTIVE only when cash covers the full monthly fee (PRD §3.2).
        if account["cash_balance_cents"] < plan["monthly_fee_cents"]:
            raise err("ERR_INVALID_STATE", "Cash insufficient to bring PAST_DUE account current.")
    else:
        raise err("ERR_INVALID_STATE", "Cannot charge subscription from current billing state.")

    # Compute fee (reads months_billed before increment) (PRD §3.3).
    fee = subscription_fee(plan["monthly_fee_cents"], account["months_billed"])

    create_cash_transaction(account["id"], "SUBSCRIPTION_FEE", -fee, "CONFIRMED")

    # Debit cash, floored at zero with shortfall recorded (PRD §3.3, §2.6).
    if fee <= account["cash_balance_cents"]:
        account["cash_balance_cents"] = account["cash_balance_cents"] - fee
    else:
        account["cash_balance_cents"] = 0

    account["months_billed"] = account["months_billed"] + 1
    account["billing_status"] = "ACTIVE"
    touch(account)
    return success(serialize(account))


@bp.route("/accounts/<entity_id>/billing/mark-past-due", methods=["POST"])
def mark_past_due(entity_id):
    require_auth({"PlatformAdmin"})
    account = fetch_or_404(store.accounts, entity_id)
    plan = store.subscription_plans[account["plan_id"]]
    if account["billing_status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Only an ACTIVE account can be marked past due.")
    if not (account["cash_balance_cents"] < plan["monthly_fee_cents"]):
        raise err("ERR_INVALID_STATE", "Account cash is not below the monthly fee.")
    account["billing_status"] = "PAST_DUE"
    touch(account)
    return success(serialize(account))


# ---------------------------------------------------------------------------
# Sweep (PRD §3.5) — OCC on account version.
# ---------------------------------------------------------------------------
@bp.route("/accounts/<entity_id>/sweep", methods=["POST"])
def sweep(entity_id):
    role, user_id = require_auth({"PlatformAdmin", "Investor"})
    account = fetch_or_404(store.accounts, entity_id)
    require_owner(role, user_id, account["id"])

    body = get_json()

    # Structural validity (priority 5, PRD §2.9): expected_account_version present.
    if "expected_account_version" not in body or body["expected_account_version"] is None:
        raise err("ERR_INVALID_REQUEST", "expected_account_version is required.")
    expected = body["expected_account_version"]

    # KYC gate (priority 9, PRD §3.5) — VERIFIED required; sits before OCC (21).
    if account["kyc_status"] != "VERIFIED":
        raise err("ERR_KYC_NOT_VERIFIED", "Account must be VERIFIED to sweep.")

    # OCC stale-version guard (priority 21, PRD §2.8).
    if expected != account["version"]:
        raise err("ERR_STALE_VERSION", "Account version is stale.")

    run_sweep(account)
    recompute_pending_roundup(account)
    touch(account)
    return success(serialize(account))


# ---------------------------------------------------------------------------
# Close (PRD §3.2)
# ---------------------------------------------------------------------------
@bp.route("/accounts/<entity_id>/close", methods=["POST"])
def close_account(entity_id):
    role, user_id = require_auth({"Investor"})
    account = fetch_or_404(store.accounts, entity_id)
    require_owner(role, user_id, account["id"])

    if account["billing_status"] not in ("TRIAL", "ACTIVE", "PAST_DUE"):
        raise err("ERR_INVALID_STATE", "Account cannot be closed from its current billing state.")

    # Every bucket must be CLOSED (PRD §3.2).
    for b in store.buckets.values():
        if b["account_id"] == account["id"] and b["status"] != "CLOSED":
            raise err("ERR_ACCOUNT_HAS_OPEN_BUCKETS", "All buckets must be CLOSED to close the account.")

    account["billing_status"] = "CLOSED"
    # Cascade: cancel ACTIVE recurring contributions (PRD §3.2).
    for rc in store.recurring_contributions.values():
        if rc["account_id"] == account["id"] and rc["status"] == "ACTIVE":
            rc["status"] = "CANCELLED"
            touch(rc)
    touch(account)
    return success(serialize(account))


# ---------------------------------------------------------------------------
# Cash transactions list (PRD §3.12)
# ---------------------------------------------------------------------------
@bp.route("/accounts/<entity_id>/cash-transactions", methods=["GET"])
def list_cash_transactions(entity_id):
    role, user_id = require_auth({"PlatformAdmin", "Investor", "CustodialGuardian"})
    account = fetch_or_404(store.accounts, entity_id)
    require_owner(role, user_id, account["id"])

    items = [t for t in store.cash_transactions.values() if t["account_id"] == account["id"]]
    tx_type = request.args.get("tx_type")
    status = request.args.get("status")
    if tx_type is not None:
        items = [t for t in items if t["tx_type"] == tx_type]
    if status is not None:
        items = [t for t in items if t["status"] == status]
    data, pagination = list_response(items)
    return success(data, pagination=pagination)
