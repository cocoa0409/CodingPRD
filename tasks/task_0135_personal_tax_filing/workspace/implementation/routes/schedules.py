"""Schedule routes (PRD §3.3)."""
from __future__ import annotations

from flask import Blueprint

from config import (
    ACCOUNT_ACTIVE,
    ROLE_IRSADJUDICATOR,
    ROLE_TAXPAYER,
    SCHEDULE_TYPES,
)
from db import store
from errors import (
    err_duplicate_schedule,
    err_invalid_input,
    err_invalid_state,
    err_salt_cap_exceeded,
    err_taxpayer_locked,
)
from middleware import require_auth
from response import list_success, success
from services import engine
from utils import is_nonneg_int, new_uuid

from routes._helpers import (
    check_version,
    enforce_return_owner,
    get_json,
    get_return_or_404,
    get_schedule_or_404,
    get_taxpayer_or_404,
    parse_pagination,
    parse_version,
    sort_by_created_at,
)


bp = Blueprint("schedules", __name__)

_INPUT_FIELDS = (
    "itemized_medical_cents",
    "itemized_salt_cents",
    "itemized_mortgage_interest_cents",
    "itemized_charity_cents",
    "schedule_c_gross_receipts_cents",
    "schedule_c_expenses_cents",
    "schedule_e_rental_income_cents",
    "schedule_e_rental_expenses_cents",
)


def _serialize_schedule(s: dict) -> dict:
    return {
        "id": s["id"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
        "tax_return_id": s["tax_return_id"],
        "schedule_type": s["schedule_type"],
        "itemized_medical_cents": s["itemized_medical_cents"],
        "itemized_salt_cents": s["itemized_salt_cents"],
        "itemized_mortgage_interest_cents": s["itemized_mortgage_interest_cents"],
        "itemized_charity_cents": s["itemized_charity_cents"],
        "schedule_b_interest_cents": s["schedule_b_interest_cents"],
        "schedule_b_dividends_cents": s["schedule_b_dividends_cents"],
        "schedule_c_gross_receipts_cents": s["schedule_c_gross_receipts_cents"],
        "schedule_c_expenses_cents": s["schedule_c_expenses_cents"],
        "schedule_c_net_profit_cents": s["schedule_c_net_profit_cents"],
        "schedule_d_short_term_gain_cents": s["schedule_d_short_term_gain_cents"],
        "schedule_d_long_term_gain_cents": s["schedule_d_long_term_gain_cents"],
        "schedule_e_rental_income_cents": s["schedule_e_rental_income_cents"],
        "schedule_e_rental_expenses_cents": s["schedule_e_rental_expenses_cents"],
        "total_itemized_deduction_cents": s["total_itemized_deduction_cents"],
    }


def _new_schedule(tax_return_id: str, schedule_type: str) -> dict:
    return {
        "id": new_uuid(),
        "tax_return_id": tax_return_id,
        "schedule_type": schedule_type,
        "itemized_medical_cents": 0,
        "itemized_salt_cents": 0,
        "itemized_mortgage_interest_cents": 0,
        "itemized_charity_cents": 0,
        "schedule_b_interest_cents": 0,
        "schedule_b_dividends_cents": 0,
        "schedule_c_gross_receipts_cents": 0,
        "schedule_c_expenses_cents": 0,
        "schedule_c_net_profit_cents": 0,
        "schedule_d_short_term_gain_cents": 0,
        "schedule_d_long_term_gain_cents": 0,
        "schedule_e_rental_income_cents": 0,
        "schedule_e_rental_expenses_cents": 0,
        "total_itemized_deduction_cents": 0,
    }


# ── POST /tax-returns/{id}/schedules ────────────────────────────────────


@bp.post("/tax-returns/<return_id>/schedules")
@require_auth([ROLE_TAXPAYER])
def create_schedule(return_id):
    body = get_json()
    with store.lock:
        r = get_return_or_404(return_id)
        enforce_return_owner(r)
        tp = get_taxpayer_or_404(r["taxpayer_id"])
        if tp["account_status"] != ACCOUNT_ACTIVE:
            raise err_taxpayer_locked()
        if r["status"] not in ("DRAFT", "READY_TO_FILE"):
            raise err_invalid_state("Cannot attach schedules outside DRAFT or READY_TO_FILE")

        schedule_type = body.get("schedule_type")
        if schedule_type not in SCHEDULE_TYPES:
            raise err_invalid_input("schedule_type must be one of A, B, C, D, E")

        s = _new_schedule(return_id, schedule_type)
        for f in _INPUT_FIELDS:
            if f in body and body[f] is not None:
                if not is_nonneg_int(body[f]):
                    raise err_invalid_input(f"{f} must be a non-negative integer")
                s[f] = body[f]

        # Priority 12: SALT cap on input.
        if schedule_type == "A" and s["itemized_salt_cents"] > 1_000_000:
            raise err_salt_cap_exceeded()

        # Priority 16: duplicate schedule type per return.
        for existing in store.schedules.values():
            if existing["tax_return_id"] == return_id and existing["schedule_type"] == schedule_type:
                raise err_duplicate_schedule()

        engine.stamp_create(s)
        store.schedules[s["id"]] = s
        engine.cascade_child_mutation(r)

    return success(_serialize_schedule(s), 201)


# ── PATCH /schedules/{id} ───────────────────────────────────────────────


@bp.patch("/schedules/<schedule_id>")
@require_auth([ROLE_TAXPAYER])
def patch_schedule(schedule_id):
    body = get_json()
    with store.lock:
        s = get_schedule_or_404(schedule_id)
        r = get_return_or_404(s["tax_return_id"])
        enforce_return_owner(r)
        tp = get_taxpayer_or_404(r["taxpayer_id"])
        if tp["account_status"] != ACCOUNT_ACTIVE:
            raise err_taxpayer_locked()
        if r["status"] not in ("DRAFT", "READY_TO_FILE"):
            raise err_invalid_state("Cannot edit schedules outside DRAFT or READY_TO_FILE")

        expected = parse_version(body)

        # Build working copy.
        working = dict(s)
        for f in _INPUT_FIELDS:
            if f in body and body[f] is not None:
                if not is_nonneg_int(body[f]):
                    raise err_invalid_input(f"{f} must be a non-negative integer")
                working[f] = body[f]

        # SALT cap check on Schedule A.
        if s["schedule_type"] == "A" and working["itemized_salt_cents"] > 1_000_000:
            raise err_salt_cap_exceeded()

        check_version(s, expected)

        for f in _INPUT_FIELDS:
            if f in body and body[f] is not None:
                s[f] = body[f]
        engine.stamp_update(s)
        engine.cascade_child_mutation(r)

    return success(_serialize_schedule(s), 200)


# ── GET /tax-returns/{id}/schedules ─────────────────────────────────────


@bp.get("/tax-returns/<return_id>/schedules")
@require_auth([ROLE_TAXPAYER, ROLE_IRSADJUDICATOR])
def list_schedules(return_id):
    r = get_return_or_404(return_id)
    enforce_return_owner(r)
    limit, offset = parse_pagination()
    rows = [s for s in store.schedules.values() if s["tax_return_id"] == return_id]
    rows = sort_by_created_at(rows)
    total = len(rows)
    page = rows[offset : offset + limit]
    return list_success([_serialize_schedule(s) for s in page], limit, offset, total, 200)
