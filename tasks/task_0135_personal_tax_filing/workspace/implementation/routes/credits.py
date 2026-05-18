"""TaxCredit routes (PRD §3.4)."""
from __future__ import annotations

from flask import Blueprint

from config import (
    ACCOUNT_ACTIVE,
    CREDIT_TYPES,
    ELIG_PENDING,
    ROLE_IRSADJUDICATOR,
    ROLE_TAXPAYER,
)
from db import store
from errors import (
    err_credit_ineligible,
    err_duplicate_credit,
    err_invalid_input,
    err_invalid_state,
    err_taxpayer_locked,
)
from middleware import require_auth
from response import empty_success, list_success, success
from services import engine
from utils import is_nonneg_int, new_uuid

from routes._helpers import (
    enforce_return_owner,
    get_credit_or_404,
    get_json,
    get_return_or_404,
    get_taxpayer_or_404,
    parse_pagination,
    sort_by_created_at,
)


bp = Blueprint("credits", __name__)


def _serialize_credit(c: dict) -> dict:
    return {
        "id": c["id"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
        "tax_return_id": c["tax_return_id"],
        "credit_type": c["credit_type"],
        "requested_amount_cents": c["requested_amount_cents"],
        "eligibility_status": c["eligibility_status"],
        "approved_amount_cents": c["approved_amount_cents"],
        "refundable_portion_cents": c["refundable_portion_cents"],
        "aotc_student_count": c["aotc_student_count"],
        "aotc_qualified_expenses_cents": c["aotc_qualified_expenses_cents"],
        "ineligibility_reason": c["ineligibility_reason"],
    }


# ── POST /tax-returns/{id}/credits ──────────────────────────────────────


@bp.post("/tax-returns/<return_id>/credits")
@require_auth([ROLE_TAXPAYER])
def claim_credit(return_id):
    body = get_json()
    with store.lock:
        r = get_return_or_404(return_id)
        enforce_return_owner(r)
        tp = get_taxpayer_or_404(r["taxpayer_id"])
        if tp["account_status"] != ACCOUNT_ACTIVE:
            raise err_taxpayer_locked()
        if r["status"] not in ("DRAFT", "READY_TO_FILE"):
            raise err_invalid_state("Cannot claim credits outside DRAFT or READY_TO_FILE")

        credit_type = body.get("credit_type")
        if credit_type not in CREDIT_TYPES:
            raise err_invalid_input("credit_type must be one of EITC, CTC, AOTC")

        requested = body.get("requested_amount_cents")
        if not is_nonneg_int(requested):
            raise err_invalid_input("requested_amount_cents must be a non-negative integer")

        aotc_students = body.get("aotc_student_count", 0) or 0
        aotc_expenses = body.get("aotc_qualified_expenses_cents", 0) or 0
        if not is_nonneg_int(aotc_students):
            raise err_invalid_input("aotc_student_count must be a non-negative integer")
        if not is_nonneg_int(aotc_expenses):
            raise err_invalid_input("aotc_qualified_expenses_cents must be a non-negative integer")

        # Priority 14: structural eligibility.
        # AOTC requires student count >= 1 and qualified expenses > 0.
        if credit_type == "AOTC":
            if aotc_students < 1 or aotc_expenses <= 0:
                raise err_credit_ineligible(
                    "AOTC requires aotc_student_count >= 1 and aotc_qualified_expenses_cents > 0"
                )
        # MARRIED_SEPARATE filing_status: EITC and AOTC ineligible.
        if r["filing_status"] == "MARRIED_SEPARATE" and credit_type in ("EITC", "AOTC"):
            raise err_credit_ineligible(
                "EITC and AOTC unavailable for MARRIED_SEPARATE filing status"
            )

        # Priority 15: duplicate credit type on same return.
        for existing in store.tax_credits.values():
            if (
                existing["tax_return_id"] == return_id
                and existing["credit_type"] == credit_type
            ):
                raise err_duplicate_credit()

        c = {
            "id": new_uuid(),
            "tax_return_id": return_id,
            "credit_type": credit_type,
            "requested_amount_cents": requested,
            "eligibility_status": ELIG_PENDING,
            "approved_amount_cents": 0,
            "refundable_portion_cents": 0,
            "aotc_student_count": aotc_students,
            "aotc_qualified_expenses_cents": aotc_expenses,
            "ineligibility_reason": None,
        }
        engine.stamp_create(c)
        store.tax_credits[c["id"]] = c
        engine.cascade_child_mutation(r)

    return success(_serialize_credit(c), 201)


# ── GET /tax-returns/{id}/credits ───────────────────────────────────────


@bp.get("/tax-returns/<return_id>/credits")
@require_auth([ROLE_TAXPAYER, ROLE_IRSADJUDICATOR])
def list_credits(return_id):
    r = get_return_or_404(return_id)
    enforce_return_owner(r)
    limit, offset = parse_pagination()
    rows = [c for c in store.tax_credits.values() if c["tax_return_id"] == return_id]
    rows = sort_by_created_at(rows)
    total = len(rows)
    page = rows[offset : offset + limit]
    return list_success([_serialize_credit(c) for c in page], limit, offset, total, 200)


# ── DELETE /credits/{id} ────────────────────────────────────────────────


@bp.delete("/credits/<credit_id>")
@require_auth([ROLE_TAXPAYER])
def delete_credit(credit_id):
    with store.lock:
        c = get_credit_or_404(credit_id)
        r = get_return_or_404(c["tax_return_id"])
        enforce_return_owner(r)
        tp = get_taxpayer_or_404(r["taxpayer_id"])
        if tp["account_status"] != ACCOUNT_ACTIVE:
            raise err_taxpayer_locked()
        if r["status"] not in ("DRAFT", "READY_TO_FILE"):
            raise err_invalid_state("Cannot delete credits outside DRAFT or READY_TO_FILE")

        del store.tax_credits[credit_id]
        engine.cascade_child_mutation(r)

    return empty_success(204)
