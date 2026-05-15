"""Loan routes: origination, listing, separate."""
from __future__ import annotations

from flask import Flask

from ..auth import require_auth
from ..clock import format_iso, now_dt, now_iso_ms
from ..errors import ApiError
from ..pagination import parse_limit_offset, parse_optional_str
from ..services import loans as loan_svc
from ..services.borrowers import recompute_aggregates
from ..store import bump_version, common_fields_create, get_store, now_iso
from ._helpers import (
    created,
    get_borrower_or_404,
    get_json_body,
    list_ok,
    ok,
)


VALID_LOAN_TYPES = {"DIRECT_SUBSIDIZED", "DIRECT_UNSUBSIDIZED", "DIRECT_PLUS"}


def _validate_create(body: dict) -> None:
    if body.get("loan_type") not in VALID_LOAN_TYPES:
        raise ApiError("ERR_INVALID_INPUT", "Invalid loan_type.")
    try:
        op = int(body.get("original_principal_cents"))
    except Exception:
        raise ApiError("ERR_INVALID_INPUT", "original_principal_cents must be int.")
    if op <= 0:
        raise ApiError("ERR_INVALID_INPUT", "original_principal_cents must be positive.")
    try:
        rb = int(body.get("interest_rate_bps"))
    except Exception:
        raise ApiError("ERR_INVALID_INPUT", "interest_rate_bps must be int.")
    if rb <= 0 or rb > 2000:
        raise ApiError("ERR_INVALID_INPUT", "interest_rate_bps must be in (0, 2000].")
    if not body.get("disbursement_date"):
        raise ApiError("ERR_INVALID_INPUT", "disbursement_date is required.")


def _get_loan_in_borrower(borrower_id: str, loan_id: str) -> dict:
    loan = get_store().loans.get(loan_id)
    if not loan or loan.get("borrower_id") != borrower_id:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", f"Loan {loan_id} not found.")
    return loan


def register(app: Flask) -> None:
    @app.route("/borrowers/<borrower_id>/loans", methods=["POST"])
    @require_auth("ServicerAdmin")
    def create_loan(borrower_id):
        b = get_borrower_or_404(borrower_id)
        body = get_json_body(allow_empty=False)
        _validate_create(body)
        loan = {
            **common_fields_create(),
            "borrower_id": borrower_id,
            "loan_type": body["loan_type"],
            "original_principal_cents": int(body["original_principal_cents"]),
            "principal_balance_cents": int(body["original_principal_cents"]),
            "accrued_interest_cents": 0,
            "capitalized_interest_cents": 0,
            "interest_rate_bps": int(body["interest_rate_bps"]),
            "disbursement_date": body["disbursement_date"],
            "status": "IN_SCHOOL",
            "status_entered_at": now_iso(),
            "last_accrual_at": now_iso(),
            "last_payment_due_at": None,
            "days_past_due": 0,
            "qualifying_pslf_payment_count": 0,
        }
        get_store().loans[loan["id"]] = loan
        recompute_aggregates(b)
        return created(loan)

    @app.route("/borrowers/<borrower_id>/loans", methods=["GET"])
    @require_auth("ServicerAdmin", "ServicerCertifier", "ServicerApprover", "CollectionsOfficer", "Borrower")
    def list_loans(borrower_id):
        get_borrower_or_404(borrower_id)
        limit, offset = parse_limit_offset()
        status = parse_optional_str("status")
        loans = [l for l in get_store().loans.values() if l.get("borrower_id") == borrower_id]
        if status:
            loans = [l for l in loans if l["status"] == status]
        loans.sort(key=lambda l: l["created_at"])
        page = {
            "limit": limit,
            "offset": offset,
            "total_count": len(loans),
            "has_more": offset + limit < len(loans),
        }
        return list_ok(loans[offset : offset + limit], page)

    @app.route("/borrowers/<borrower_id>/loans/<loan_id>", methods=["GET"])
    @require_auth("ServicerAdmin", "ServicerCertifier", "ServicerApprover", "CollectionsOfficer", "Borrower")
    def get_loan(borrower_id, loan_id):
        get_borrower_or_404(borrower_id)
        loan = _get_loan_in_borrower(borrower_id, loan_id)
        return ok(loan)

    @app.route("/borrowers/<borrower_id>/loans/<loan_id>/separate", methods=["POST"])
    @require_auth("ServicerAdmin")
    def separate_loan(borrower_id, loan_id):
        b = get_borrower_or_404(borrower_id)
        loan = _get_loan_in_borrower(borrower_id, loan_id)
        body = get_json_body()
        skip = bool(body.get("skip_grace", False))
        if loan["status"] != "IN_SCHOOL":
            raise ApiError("ERR_INVALID_STATE", "Loan must be in IN_SCHOOL to separate.")
        if skip:
            if loan["loan_type"] != "DIRECT_PLUS":
                raise ApiError(
                    "ERR_INVALID_STATE",
                    "skip_grace only allowed for DIRECT_PLUS loans.",
                )
            # Capitalize accrued (should be zero from IN_SCHOOL, but follow spec)
            loan_svc.capitalize_accrued(loan)
            loan_svc.set_status(loan, "REPAYMENT")
            loan_svc.set_due_first_of_month(loan, now_dt())
            loan["last_accrual_at"] = now_iso_ms()
        else:
            loan_svc.set_status(loan, "GRACE")
            loan["last_accrual_at"] = now_iso_ms()
        recompute_aggregates(b)
        return ok(loan)
