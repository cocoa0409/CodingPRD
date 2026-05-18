"""IncomeDocument routes (PRD §3.2)."""
from __future__ import annotations

from flask import Blueprint, request

from config import (
    ACCOUNT_ACTIVE,
    DOC_TYPES,
    HOLDING_PERIODS,
    ROLE_IRSADJUDICATOR,
    ROLE_TAXPAYER,
)
from db import store
from errors import (
    err_income_doc_invalid,
    err_invalid_input,
    err_qualified_div_exceeds_ordinary,
    err_taxpayer_locked,
)
from middleware import require_auth
from response import empty_success, list_success, success
from services import engine
from utils import iso_now, is_nonempty_str, is_nonneg_int, new_uuid

from routes._helpers import (
    check_version,
    enforce_return_owner,
    get_income_doc_or_404,
    get_json,
    get_return_or_404,
    get_taxpayer_or_404,
    parse_pagination,
    parse_version,
    sort_by_created_at,
)


bp = Blueprint("income_documents", __name__)


_DOC_FIELDS = (
    "wages_cents",
    "federal_withholding_cents",
    "nonemployee_comp_cents",
    "interest_income_cents",
    "ordinary_dividends_cents",
    "qualified_dividends_cents",
    "proceeds_cents",
    "cost_basis_cents",
)


def _serialize_doc(d: dict) -> dict:
    return {
        "id": d["id"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
        "tax_return_id": d["tax_return_id"],
        "doc_type": d["doc_type"],
        "payer_ein": d["payer_ein"],
        "payer_name": d["payer_name"],
        "wages_cents": d["wages_cents"],
        "federal_withholding_cents": d["federal_withholding_cents"],
        "nonemployee_comp_cents": d["nonemployee_comp_cents"],
        "interest_income_cents": d["interest_income_cents"],
        "ordinary_dividends_cents": d["ordinary_dividends_cents"],
        "qualified_dividends_cents": d["qualified_dividends_cents"],
        "proceeds_cents": d["proceeds_cents"],
        "cost_basis_cents": d["cost_basis_cents"],
        "holding_period": d["holding_period"],
        "imported_at": d["imported_at"],
    }


def _validate_amount_fields(d: dict):
    for f in _DOC_FIELDS:
        if not is_nonneg_int(d.get(f, 0)):
            raise err_invalid_input(f"{f} must be a non-negative integer")


def _validate_doc_semantics(doc_type: str, d: dict):
    """Apply validation priorities 10 (DIV) and 11 (1099-B)."""
    # Priority 10: DIV qualified <= ordinary.
    if doc_type == "1099_DIV":
        qual = d.get("qualified_dividends_cents", 0) or 0
        ord_d = d.get("ordinary_dividends_cents", 0) or 0
        if qual > ord_d:
            raise err_qualified_div_exceeds_ordinary()
    # Priority 11: 1099_B holding_period required, cost basis sanity.
    if doc_type == "1099_B":
        hp = d.get("holding_period", "NONE")
        if hp not in ("SHORT_TERM", "LONG_TERM"):
            raise err_income_doc_invalid("1099-B requires holding_period in {SHORT_TERM, LONG_TERM}")
        proceeds = d.get("proceeds_cents", 0) or 0
        cost = d.get("cost_basis_cents", 0) or 0
        if cost > proceeds + 100_000_000:
            raise err_income_doc_invalid("1099-B cost_basis_cents exceeds proceeds_cents + sanity ceiling")


# ── POST /tax-returns/{id}/income-documents ─────────────────────────────


@bp.post("/tax-returns/<return_id>/income-documents")
@require_auth([ROLE_TAXPAYER])
def import_doc(return_id):
    body = get_json()
    with store.lock:
        r = get_return_or_404(return_id)
        enforce_return_owner(r)
        tp = get_taxpayer_or_404(r["taxpayer_id"])
        if tp["account_status"] != ACCOUNT_ACTIVE:
            raise err_taxpayer_locked()

        # NOTE: importing onto any return state mutates children; if the
        # return is in a terminal/in-flight state (FILED/ACCEPTED/etc.)
        # the cascade-child rule (§2.7) implies child mutation reverts
        # only READY_TO_FILE → DRAFT. Mutations on non-DRAFT/non-READY
        # returns make no semantic sense; reject as ERR_INVALID_STATE.
        if r["status"] not in ("DRAFT", "READY_TO_FILE"):
            from errors import err_invalid_state
            raise err_invalid_state("Cannot import documents on a return that is not DRAFT or READY_TO_FILE")

        doc_type = body.get("doc_type")
        if doc_type not in DOC_TYPES:
            raise err_invalid_input("doc_type must be one of W2, 1099_NEC, 1099_INT, 1099_DIV, 1099_B")
        payer_ein = body.get("payer_ein")
        payer_name = body.get("payer_name")
        if not is_nonempty_str(payer_ein):
            raise err_invalid_input("payer_ein is required")
        if not is_nonempty_str(payer_name):
            raise err_invalid_input("payer_name is required")

        d = {
            "id": new_uuid(),
            "tax_return_id": return_id,
            "doc_type": doc_type,
            "payer_ein": payer_ein,
            "payer_name": payer_name,
            "wages_cents": body.get("wages_cents", 0) or 0,
            "federal_withholding_cents": body.get("federal_withholding_cents", 0) or 0,
            "nonemployee_comp_cents": body.get("nonemployee_comp_cents", 0) or 0,
            "interest_income_cents": body.get("interest_income_cents", 0) or 0,
            "ordinary_dividends_cents": body.get("ordinary_dividends_cents", 0) or 0,
            "qualified_dividends_cents": body.get("qualified_dividends_cents", 0) or 0,
            "proceeds_cents": body.get("proceeds_cents", 0) or 0,
            "cost_basis_cents": body.get("cost_basis_cents", 0) or 0,
            "holding_period": body.get("holding_period", "NONE"),
        }
        if d["holding_period"] not in HOLDING_PERIODS:
            raise err_invalid_input("holding_period must be NONE, SHORT_TERM, or LONG_TERM")
        _validate_amount_fields(d)
        _validate_doc_semantics(doc_type, d)

        d["imported_at"] = iso_now(store.clock_now())
        engine.stamp_create(d)
        store.income_documents[d["id"]] = d

        # Cascade: READY_TO_FILE → DRAFT (also bumps parent version).
        engine.cascade_child_mutation(r)

    return success(_serialize_doc(d), 201)


# ── GET /tax-returns/{id}/income-documents ──────────────────────────────


@bp.get("/tax-returns/<return_id>/income-documents")
@require_auth([ROLE_TAXPAYER, ROLE_IRSADJUDICATOR])
def list_docs(return_id):
    r = get_return_or_404(return_id)
    enforce_return_owner(r)
    limit, offset = parse_pagination()
    f_doc_type = request.args.get("doc_type")
    rows = [d for d in store.income_documents.values() if d["tax_return_id"] == return_id]
    if f_doc_type is not None:
        rows = [d for d in rows if d["doc_type"] == f_doc_type]
    rows = sort_by_created_at(rows)
    total = len(rows)
    page = rows[offset : offset + limit]
    return list_success([_serialize_doc(d) for d in page], limit, offset, total, 200)


# ── PATCH /income-documents/{id} ────────────────────────────────────────


@bp.patch("/income-documents/<doc_id>")
@require_auth([ROLE_TAXPAYER])
def patch_doc(doc_id):
    body = get_json()
    with store.lock:
        d = get_income_doc_or_404(doc_id)
        r = get_return_or_404(d["tax_return_id"])
        enforce_return_owner(r)
        tp = get_taxpayer_or_404(r["taxpayer_id"])
        if tp["account_status"] != ACCOUNT_ACTIVE:
            raise err_taxpayer_locked()
        if r["status"] not in ("DRAFT", "READY_TO_FILE"):
            from errors import err_invalid_state
            raise err_invalid_state("Cannot edit documents on a return that is not DRAFT or READY_TO_FILE")

        expected = parse_version(body)

        # Apply updates onto a working copy then validate.
        working = dict(d)
        for f in _DOC_FIELDS:
            if f in body and body[f] is not None:
                working[f] = body[f]
        if "holding_period" in body and body["holding_period"] is not None:
            if body["holding_period"] not in HOLDING_PERIODS:
                raise err_invalid_input("holding_period must be NONE, SHORT_TERM, or LONG_TERM")
            working["holding_period"] = body["holding_period"]

        _validate_amount_fields(working)
        _validate_doc_semantics(working["doc_type"], working)

        check_version(d, expected)

        for f in _DOC_FIELDS:
            if f in body and body[f] is not None:
                d[f] = body[f]
        if "holding_period" in body and body["holding_period"] is not None:
            d["holding_period"] = body["holding_period"]
        engine.stamp_update(d)
        engine.cascade_child_mutation(r)

    return success(_serialize_doc(d), 200)


# ── DELETE /income-documents/{id} ───────────────────────────────────────


@bp.delete("/income-documents/<doc_id>")
@require_auth([ROLE_TAXPAYER])
def delete_doc(doc_id):
    with store.lock:
        d = get_income_doc_or_404(doc_id)
        r = get_return_or_404(d["tax_return_id"])
        enforce_return_owner(r)
        tp = get_taxpayer_or_404(r["taxpayer_id"])
        if tp["account_status"] != ACCOUNT_ACTIVE:
            raise err_taxpayer_locked()
        if r["status"] not in ("DRAFT", "READY_TO_FILE"):
            from errors import err_invalid_state
            raise err_invalid_state("Cannot delete documents on a return that is not DRAFT or READY_TO_FILE")

        del store.income_documents[doc_id]
        engine.cascade_child_mutation(r)

    return empty_success(204)
