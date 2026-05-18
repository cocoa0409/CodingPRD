"""EstimatedTaxPayment routes (PRD §3.10)."""
from __future__ import annotations

from flask import Blueprint, g, request

from config import (
    ACCOUNT_ACTIVE,
    PAYMENT_CANCELLED,
    PAYMENT_SCHEDULED,
    QUARTERS,
    ROLE_IRSADJUDICATOR,
    ROLE_TAXPAYER,
    TAX_YEAR_MAX,
    TAX_YEAR_MIN,
)
from db import store
from errors import (
    err_invalid_input,
    err_payment_cannot_cancel,
    err_payment_date_past,
    err_taxpayer_locked,
)
from middleware import require_auth
from response import list_success, success
from services import engine
from utils import iso_now, new_uuid, parse_date_to_midnight_utc

from routes._helpers import (
    enforce_taxpayer_self,
    get_json,
    get_payment_or_404,
    get_taxpayer_or_404,
    parse_pagination,
    sort_by_created_at,
)


bp = Blueprint("estimated_payments", __name__)


def _serialize_payment(p: dict) -> dict:
    return {
        "id": p["id"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
        "taxpayer_id": p["taxpayer_id"],
        "tax_year": p["tax_year"],
        "quarter": p["quarter"],
        "amount_cents": p["amount_cents"],
        "scheduled_pay_date": p["scheduled_pay_date"],
        "status": p["status"],
        "confirmed_at": p.get("confirmed_at"),
        "cancelled_at": p.get("cancelled_at"),
    }


# ── POST /estimated-payments ────────────────────────────────────────────


@bp.post("/estimated-payments")
@require_auth([ROLE_TAXPAYER])
def schedule_payment():
    body = get_json()
    with store.lock:
        taxpayer_id = body.get("taxpayer_id")
        if not isinstance(taxpayer_id, str) or not taxpayer_id.strip():
            raise err_invalid_input("taxpayer_id is required")
        tp = get_taxpayer_or_404(taxpayer_id)
        enforce_taxpayer_self(tp)
        if tp["account_status"] != ACCOUNT_ACTIVE:
            raise err_taxpayer_locked()

        tax_year = body.get("tax_year")
        quarter = body.get("quarter")
        amount = body.get("amount_cents")
        pay_date_raw = body.get("scheduled_pay_date")

        if isinstance(tax_year, bool) or not isinstance(tax_year, int):
            raise err_invalid_input("tax_year must be an integer")
        if tax_year < TAX_YEAR_MIN or tax_year > TAX_YEAR_MAX:
            raise err_invalid_input("tax_year must be in 2020..2025")
        if quarter not in QUARTERS:
            raise err_invalid_input("quarter must be one of Q1, Q2, Q3, Q4")
        if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
            raise err_invalid_input("amount_cents must be a positive integer")
        if not isinstance(pay_date_raw, str):
            raise err_invalid_input("scheduled_pay_date must be a YYYY-MM-DD string")
        try:
            pay_date_dt = parse_date_to_midnight_utc(pay_date_raw)
        except Exception:
            raise err_invalid_input("scheduled_pay_date must be a valid YYYY-MM-DD date")

        # Priority 17: strictly after clock.now.
        if pay_date_dt <= store.clock_now():
            raise err_payment_date_past()

        p = {
            "id": new_uuid(),
            "taxpayer_id": taxpayer_id,
            "tax_year": tax_year,
            "quarter": quarter,
            "amount_cents": amount,
            "scheduled_pay_date": pay_date_raw,
            "status": PAYMENT_SCHEDULED,
            "confirmed_at": None,
            "cancelled_at": None,
        }
        engine.stamp_create(p)
        store.estimated_payments[p["id"]] = p

    return success(_serialize_payment(p), 201)


# ── GET /estimated-payments ─────────────────────────────────────────────


@bp.get("/estimated-payments")
@require_auth([ROLE_TAXPAYER, ROLE_IRSADJUDICATOR])
def list_payments():
    limit, offset = parse_pagination()
    f_tp = request.args.get("taxpayer_id")
    f_year = request.args.get("tax_year")
    f_q = request.args.get("quarter")
    f_status = request.args.get("status")

    if f_year is not None:
        try:
            f_year_int = int(f_year)
        except (TypeError, ValueError):
            raise err_invalid_input("tax_year filter must be integer")
    else:
        f_year_int = None

    rows = list(store.estimated_payments.values())
    if g.role == ROLE_TAXPAYER:
        rows = [p for p in rows if p["taxpayer_id"] == g.user_id]
    if f_tp is not None:
        rows = [p for p in rows if p["taxpayer_id"] == f_tp]
    if f_year_int is not None:
        rows = [p for p in rows if p["tax_year"] == f_year_int]
    if f_q is not None:
        rows = [p for p in rows if p["quarter"] == f_q]
    if f_status is not None:
        rows = [p for p in rows if p["status"] == f_status]
    rows = sort_by_created_at(rows)
    total = len(rows)
    page = rows[offset : offset + limit]
    return list_success([_serialize_payment(p) for p in page], limit, offset, total, 200)


# ── POST /estimated-payments/{id}/cancel ────────────────────────────────


@bp.post("/estimated-payments/<payment_id>/cancel")
@require_auth([ROLE_TAXPAYER])
def cancel_payment(payment_id):
    with store.lock:
        p = get_payment_or_404(payment_id)
        tp = get_taxpayer_or_404(p["taxpayer_id"])
        enforce_taxpayer_self(tp)
        if tp["account_status"] != ACCOUNT_ACTIVE:
            raise err_taxpayer_locked()
        if p["status"] != PAYMENT_SCHEDULED:
            raise err_payment_cannot_cancel("Only SCHEDULED payments can be cancelled")
        pay_dt = parse_date_to_midnight_utc(p["scheduled_pay_date"])
        if store.clock_now() >= pay_dt:
            raise err_payment_cannot_cancel()

        p["status"] = PAYMENT_CANCELLED
        p["cancelled_at"] = iso_now(store.clock_now())
        engine.stamp_update(p)

    return success(_serialize_payment(p), 200)
