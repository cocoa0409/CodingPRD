"""Account routes: create, get, list, close, pdt/reset."""
from __future__ import annotations

from flask import Blueprint, request

import config as cfg
from db import store
from errors import (
    err_account_has_dependencies,
    err_account_not_approved,
    err_invalid_state,
    err_kyc_not_verified,
    err_validation,
)
from middleware import require_auth
from response import list_success, success
from routes._helpers import (
    enforce_customer_owns_account,
    enforce_customer_owns_customer,
    get_account_or_404,
    get_customer_or_404,
    get_json,
    paginate,
    parse_pagination,
    require_int,
    require_str,
    sort_by_created_at,
)
from services.engine import recompute_equity, touch
from services.serializers import account_view


bp = Blueprint("accounts", __name__)


# ── POST /brokerage/accounts ───────────────────────────────────────────────

@bp.post("/brokerage/accounts")
@require_auth([cfg.ROLE_CUSTOMER])
def create_account():
    body = get_json()
    customer_id = require_str(body, "customer_id")
    c = get_customer_or_404(customer_id)
    enforce_customer_owns_customer(c)

    account_type = require_str(body, "account_type")
    if account_type not in cfg.ACCOUNT_TYPES:
        raise err_validation("account_type must be CASH | MARGIN_REG_T | MARGIN_PMA")

    now = store.now()
    from utils import new_uuid

    aid = new_uuid()
    account = {
        "id": aid,
        "customer_id": customer_id,
        "account_type": account_type,
        "status": cfg.ACCT_STATUS_PENDING_KYC,
        "trading_posture": cfg.POSTURE_RESTRICTED,
        "options_level": 0,
        "cash_balance_cents": 0,
        "equity_value_cents": 0,
        "pdt_flag": False,
        "pdt_flagged_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    with store.lock:
        store.accounts[aid] = account
    return success(account_view(account), 201)


# ── GET /brokerage/accounts/{id} ───────────────────────────────────────────

@bp.get("/brokerage/accounts/<account_id>")
@require_auth([cfg.ROLE_CUSTOMER, cfg.ROLE_COMPLIANCE, cfg.ROLE_ADMIN])
def get_account(account_id: str):
    a = get_account_or_404(account_id)
    enforce_customer_owns_account(a)
    return success(account_view(a), 200)


# ── GET /brokerage/accounts ────────────────────────────────────────────────

@bp.get("/brokerage/accounts")
@require_auth([cfg.ROLE_CUSTOMER, cfg.ROLE_COMPLIANCE, cfg.ROLE_ADMIN])
def list_accounts():
    from flask import g

    limit, offset = parse_pagination()
    customer_filter = request.args.get("customer_id")
    status_filter = request.args.get("status")

    rows = list(store.accounts.values())
    if g.role == cfg.ROLE_CUSTOMER:
        # Customers only see their own accounts.
        rows = [r for r in rows if r["customer_id"] == g.user_id]
    if customer_filter is not None:
        rows = [r for r in rows if r["customer_id"] == customer_filter]
    if status_filter is not None:
        rows = [r for r in rows if r["status"] == status_filter]

    rows = sort_by_created_at(rows)
    total = len(rows)
    page = paginate(rows, limit, offset)
    return list_success([account_view(r) for r in page], limit, offset, total)


# ── POST /brokerage/accounts/{id}/close ────────────────────────────────────

@bp.post("/brokerage/accounts/<account_id>/close")
@require_auth([cfg.ROLE_CUSTOMER])
def close_account(account_id: str):
    a = get_account_or_404(account_id)
    enforce_customer_owns_account(a)

    # Posture gates: status==APPROVED first, then kyc_status==VERIFIED.
    if a["status"] != cfg.ACCT_STATUS_APPROVED:
        raise err_account_not_approved()
    c = store.customers.get(a["customer_id"])
    if c is None or c["kyc_status"] != cfg.KYC_VERIFIED:
        raise err_kyc_not_verified()

    # Dependencies must be settled.
    for o in store.orders.values():
        if o["account_id"] == account_id and o["status"] in cfg.ORDER_OPEN:
            raise err_account_has_dependencies("open Orders block close")
    for t in store.acat_transfers.values():
        if t["account_id"] == account_id and t["status"] in cfg.ACAT_NON_TERMINAL:
            raise err_account_has_dependencies("non-terminal ACATTransfers block close")
    if a["cash_balance_cents"] != 0 or a["equity_value_cents"] != 0:
        raise err_account_has_dependencies("non-zero balances block close")

    now = store.now()
    with store.lock:
        a["status"] = cfg.ACCT_STATUS_CLOSED
        a["trading_posture"] = cfg.POSTURE_RESTRICTED
        touch(a, now)
    return success(account_view(a), 200)


# ── POST /brokerage/accounts/{id}/pdt/reset ────────────────────────────────

@bp.post("/brokerage/accounts/<account_id>/pdt/reset")
@require_auth([cfg.ROLE_CUSTOMER])
def pdt_reset(account_id: str):
    a = get_account_or_404(account_id)
    enforce_customer_owns_account(a)

    # Posture gates apply (account approved, KYC verified).
    if a["status"] != cfg.ACCT_STATUS_APPROVED:
        raise err_account_not_approved()
    c = store.customers.get(a["customer_id"])
    if c is None or c["kyc_status"] != cfg.KYC_VERIFIED:
        raise err_kyc_not_verified()

    body = get_json()
    top_up = require_int(body, "equity_top_up_cents", minimum=0)

    now = store.now()
    with store.lock:
        a["cash_balance_cents"] += top_up
        recompute_equity(a)
        if a["trading_posture"] == cfg.POSTURE_PDT_FROZEN and a["equity_value_cents"] >= cfg.PDT_EQUITY_FLOOR_CENTS:
            a["trading_posture"] = cfg.POSTURE_OPEN
            a["pdt_flag"] = False
        touch(a, now)
    return success(account_view(a), 200)
