"""ACATTransfer routes: initiate, get, list, validate, reject, cancel."""
from __future__ import annotations

from flask import Blueprint, g, request

import config as cfg
from db import store
from errors import (
    err_account_not_approved,
    err_invalid_state,
    err_kyc_not_verified,
    err_open_orders_block_transfer,
    err_ownership,
    err_transfer_already_pending,
    err_validation,
)
from middleware import require_auth
from response import list_success, success
from routes._helpers import (
    enforce_customer_owns_account,
    get_account_or_404,
    get_json,
    get_transfer_or_404,
    paginate,
    parse_pagination,
    require_int,
    require_str,
    sort_by_created_at,
)
from services.engine import stamp_acat_validated, touch
from services.serializers import acat_transfer_view
from utils import new_uuid


bp = Blueprint("acat_transfers", __name__)


# ── POST /brokerage/acat-transfers ─────────────────────────────────────────

@bp.post("/brokerage/acat-transfers")
@require_auth([cfg.ROLE_CUSTOMER])
def initiate_transfer():
    body = get_json()
    account_id = require_str(body, "account_id")
    a = get_account_or_404(account_id)
    enforce_customer_owns_account(a)

    if a["status"] != cfg.ACCT_STATUS_APPROVED:
        raise err_account_not_approved()
    c = store.customers.get(a["customer_id"])
    if c is None or c["kyc_status"] != cfg.KYC_VERIFIED:
        raise err_kyc_not_verified()

    direction = require_str(body, "direction")
    if direction not in cfg.ACAT_DIRECTIONS:
        raise err_validation("direction must be INBOUND | OUTBOUND")
    cb = require_str(body, "counterparty_brokerage")
    can = require_str(body, "counterparty_account_number")
    rv = require_int(body, "requested_value_cents", minimum=100)

    # OUTBOUND uniqueness: at most one non-terminal outbound per account.
    if direction == cfg.ACAT_OUTBOUND:
        for t in store.acat_transfers.values():
            if (
                t["account_id"] == account_id
                and t["direction"] == cfg.ACAT_OUTBOUND
                and t["status"] in cfg.ACAT_NON_TERMINAL
            ):
                raise err_transfer_already_pending()

    now = store.now()
    tid = new_uuid()
    t = {
        "id": tid,
        "account_id": account_id,
        "direction": direction,
        "counterparty_brokerage": cb,
        "counterparty_account_number": can,
        "requested_value_cents": rv,
        "status": cfg.ACAT_INITIATED,
        "initiated_at": now,
        "expected_completion_at": None,
        "completed_at": None,
        "business_days_elapsed": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    with store.lock:
        store.acat_transfers[tid] = t
    return success(acat_transfer_view(t), 201)


# ── GET /brokerage/acat-transfers/{id} ─────────────────────────────────────

@bp.get("/brokerage/acat-transfers/<tid>")
@require_auth([cfg.ROLE_CUSTOMER, cfg.ROLE_COMPLIANCE, cfg.ROLE_ADMIN])
def get_transfer(tid: str):
    t = get_transfer_or_404(tid)
    if g.role == cfg.ROLE_CUSTOMER:
        a = store.accounts.get(t["account_id"])
        if a is None or a["customer_id"] != g.user_id:
            raise err_ownership()
    return success(acat_transfer_view(t), 200)


# ── GET /brokerage/acat-transfers ──────────────────────────────────────────

@bp.get("/brokerage/acat-transfers")
@require_auth([cfg.ROLE_CUSTOMER, cfg.ROLE_COMPLIANCE, cfg.ROLE_ADMIN])
def list_transfers():
    limit, offset = parse_pagination()
    account_id = request.args.get("account_id")
    direction = request.args.get("direction")
    status_f = request.args.get("status")

    rows = list(store.acat_transfers.values())
    if g.role == cfg.ROLE_CUSTOMER:
        owned = {a["id"] for a in store.accounts.values() if a["customer_id"] == g.user_id}
        rows = [r for r in rows if r["account_id"] in owned]
    if account_id is not None:
        rows = [r for r in rows if r["account_id"] == account_id]
    if direction is not None:
        rows = [r for r in rows if r["direction"] == direction]
    if status_f is not None:
        rows = [r for r in rows if r["status"] == status_f]
    rows = sort_by_created_at(rows)
    total = len(rows)
    page = paginate(rows, limit, offset)
    return list_success([acat_transfer_view(r) for r in page], limit, offset, total)


# ── POST /brokerage/acat-transfers/{id}/validate ───────────────────────────

@bp.post("/brokerage/acat-transfers/<tid>/validate")
@require_auth([cfg.ROLE_COMPLIANCE])
def validate_transfer(tid: str):
    t = get_transfer_or_404(tid)
    a = store.accounts.get(t["account_id"])
    if a is None:
        raise err_invalid_state("orphan transfer")
    if a["status"] != cfg.ACCT_STATUS_APPROVED:
        raise err_account_not_approved()
    c = store.customers.get(a["customer_id"])
    if c is None or c["kyc_status"] != cfg.KYC_VERIFIED:
        raise err_kyc_not_verified()

    if t["status"] != cfg.ACAT_INITIATED:
        raise err_invalid_state("validate requires INITIATED")

    if t["direction"] == cfg.ACAT_OUTBOUND:
        for o in store.orders.values():
            if o["account_id"] == t["account_id"] and o["status"] in cfg.ORDER_OPEN:
                raise err_open_orders_block_transfer()

    now = store.now()
    with store.lock:
        stamp_acat_validated(t, now)
        if t["direction"] == cfg.ACAT_OUTBOUND:
            # Cascade: cancel open orders, posture → TRANSFER_LOCKED.
            for o in list(store.orders.values()):
                if o["account_id"] == t["account_id"] and o["status"] in cfg.ORDER_OPEN:
                    o["status"] = cfg.ORDER_CANCELLED
                    touch(o, now)
            a["trading_posture"] = cfg.POSTURE_TRANSFER_LOCKED
            touch(a, now)
    return success(acat_transfer_view(t), 200)


# ── POST /brokerage/acat-transfers/{id}/reject ─────────────────────────────

@bp.post("/brokerage/acat-transfers/<tid>/reject")
@require_auth([cfg.ROLE_COMPLIANCE])
def reject_transfer(tid: str):
    t = get_transfer_or_404(tid)
    if t["status"] != cfg.ACAT_INITIATED:
        raise err_invalid_state("reject requires INITIATED")
    body = get_json()
    reason = require_str(body, "reason")
    if not reason.strip():
        raise err_validation("reason required")

    now = store.now()
    with store.lock:
        t["status"] = cfg.ACAT_REJECTED
        touch(t, now)
    return success(acat_transfer_view(t), 200)


# ── DELETE /brokerage/acat-transfers/{id} ──────────────────────────────────

@bp.delete("/brokerage/acat-transfers/<tid>")
@require_auth([cfg.ROLE_CUSTOMER])
def cancel_transfer(tid: str):
    t = get_transfer_or_404(tid)
    a = store.accounts.get(t["account_id"])
    if a is None or a["customer_id"] != g.user_id:
        raise err_ownership()
    if t["status"] not in (cfg.ACAT_INITIATED, cfg.ACAT_VALIDATED):
        raise err_invalid_state("cancel requires INITIATED or VALIDATED")

    now = store.now()
    with store.lock:
        previous_status = t["status"]
        t["status"] = cfg.ACAT_CANCELLED
        touch(t, now)
        # If this cancelled a VALIDATED OUTBOUND, lift TRANSFER_LOCKED
        # provided no other non-terminal outbound remains.
        if previous_status == cfg.ACAT_VALIDATED and t["direction"] == cfg.ACAT_OUTBOUND:
            still_locked = False
            for other in store.acat_transfers.values():
                if other["id"] == t["id"]:
                    continue
                if (
                    other["account_id"] == t["account_id"]
                    and other["direction"] == cfg.ACAT_OUTBOUND
                    and other["status"] in cfg.ACAT_NON_TERMINAL
                ):
                    still_locked = True
                    break
            if not still_locked and a["trading_posture"] == cfg.POSTURE_TRANSFER_LOCKED:
                a["trading_posture"] = cfg.POSTURE_OPEN
                touch(a, now)
    return success(acat_transfer_view(t), 200)
