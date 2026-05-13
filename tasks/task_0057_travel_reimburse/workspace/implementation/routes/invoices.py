"""Invoice endpoints (upload, OCR, tax verification, fetch)."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal

from flask import Blueprint, g, request

from db import STORE
from errors import (
    APIError, ERR_FORBIDDEN, ERR_INVALID_STATE, ERR_NOT_FOUND, ERR_VALIDATION,
    ERR_INVOICE_DUPLICATE, ERR_IDEMPOTENT_REPLAY,
)
from middleware import require_auth
from response import success
from serializers import invoice as ser_invoice
from services.audit import emit_external_sync
from services.validate import (
    require_body, get_str, get_enum, get_money, get_datetime,
)
from utils import CLOCK, new_uuid, format_ts


bp = Blueprint("invoices", __name__)


CATEGORIES = {"LODGING", "PER_DIEM", "TRANSPORTATION", "OTHER"}


def _load_invoice_or_404(inv_id):
    row = STORE.invoices.get(inv_id)
    if not row:
        raise APIError(ERR_NOT_FOUND, f"Invoice {inv_id} not found", 404)
    return row


def _duplicate_exists(invoice_code, invoice_number, exclude_id=None,
                     statuses=None) -> bool:
    """Return True if an Invoice with the same (invoice_code, invoice_number) exists
    in any of the given ocr_statuses (defaults to anything not REJECTED)."""
    for r in STORE.invoices.values():
        if exclude_id is not None and r["id"] == exclude_id:
            continue
        if r["invoice_code"] != invoice_code or r["invoice_number"] != invoice_number:
            continue
        if statuses is None:
            if r["ocr_status"] != "REJECTED":
                return True
        else:
            if r["ocr_status"] in statuses:
                return True
    return False


def bump_inv(row: dict) -> None:
    row["updated_at"] = CLOCK.now_iso()
    row["version"] = row.get("version", 0) + 1


@bp.route("/invoices", methods=["POST"])
@require_auth(["Applicant"])
def upload_invoice():
    body = require_body(request.get_json(silent=True))
    applicant_id = get_str(body, "applicant_id")
    invoice_number = get_str(body, "invoice_number")
    invoice_code = get_str(body, "invoice_code")
    category = get_enum(body, "category", CATEGORIES)
    amount = get_money(body, "amount", required=False, non_negative=True, default=None)
    invoice_date = None
    if body.get("invoice_date") is not None:
        invoice_date = get_datetime(body, "invoice_date", required=False)

    # Body FK: applicant_id must exist
    if applicant_id not in STORE.employees:
        raise APIError("ERR_REFERENCE_INVALID", "applicant_id not found", 422)
    # Ownership
    if applicant_id != g.user_id:
        raise APIError(ERR_FORBIDDEN,
                        "Applicant can only upload their own invoices", 403)

    # Duplicate check at upload time (per PRD §3.6)
    if _duplicate_exists(invoice_code, invoice_number):
        raise APIError(ERR_INVOICE_DUPLICATE,
                        "Invoice (invoice_code, invoice_number) already exists", 409)

    now = CLOCK.now_iso()
    iid = new_uuid()
    row = {
        "id": iid,
        "applicant_id": applicant_id,
        "invoice_number": invoice_number,
        "invoice_code": invoice_code,
        "amount": amount,
        "invoice_date": format_ts(invoice_date) if invoice_date else None,
        "category": category,
        "ocr_status": "PENDING_OCR",
        "matched_segment_id": None,
        "rejection_reason": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    STORE.invoices[iid] = row
    return success(ser_invoice(row), status=201)


@bp.route("/invoices/<inv_id>", methods=["GET"])
@require_auth(["Applicant", "Finance", "Admin"])
def get_invoice(inv_id):
    inv = _load_invoice_or_404(inv_id)
    return success(ser_invoice(inv))


def _body_fingerprint() -> str:
    raw = request.get_data() or b""
    return hashlib.sha256(raw).hexdigest()


@bp.route("/invoices/<inv_id>/ocr", methods=["POST"])
@require_auth(["Applicant"])
def ocr_invoice(inv_id):
    inv = _load_invoice_or_404(inv_id)
    # Ownership
    if inv["applicant_id"] != g.user_id:
        raise APIError(ERR_FORBIDDEN, "Applicant is not the owner", 403)

    idempotency_key = request.headers.get("Idempotency-Key", "").strip()
    body_fp = _body_fingerprint()
    if idempotency_key:
        cache_for_inv = STORE.idempotency_cache.setdefault(inv["id"], {})
        prior = cache_for_inv.get(idempotency_key)
        if prior is not None:
            prior_fp, prior_payload, prior_status = prior
            if prior_fp != body_fp:
                raise APIError(ERR_IDEMPOTENT_REPLAY,
                                "Idempotency-Key replayed with different payload", 409)
            # Return prior response verbatim
            from flask import jsonify
            resp = jsonify(prior_payload)
            resp.status_code = prior_status
            return resp

    # State must be PENDING_OCR
    if inv["ocr_status"] != "PENDING_OCR":
        raise APIError(ERR_INVALID_STATE,
                        "Invoice is not in PENDING_OCR", 409)

    # OCR: simulate population of missing fields
    if inv.get("amount") is None:
        inv["amount"] = Decimal("0.00")
    if inv.get("invoice_date") is None:
        inv["invoice_date"] = CLOCK.now_iso()
    # category already set on upload
    inv["ocr_status"] = "OCR_RECOGNIZED"
    bump_inv(inv)

    # Build response and cache under idempotency key
    from response import success as _success
    resp = _success(ser_invoice(inv))
    if idempotency_key:
        payload = resp.get_json()
        STORE.idempotency_cache.setdefault(inv["id"], {})[idempotency_key] = (
            body_fp, payload, resp.status_code,
        )
    return resp


@bp.route("/invoices/<inv_id>/verify-tax", methods=["POST"])
@require_auth(["Applicant", "Finance"])
def verify_tax(inv_id):
    inv = _load_invoice_or_404(inv_id)
    # Ownership: Applicant must own it
    if g.role == "Applicant" and inv["applicant_id"] != g.user_id:
        raise APIError(ERR_FORBIDDEN, "Applicant is not the owner", 403)

    if inv["ocr_status"] != "OCR_RECOGNIZED":
        raise APIError(ERR_INVALID_STATE,
                        "Invoice must be in OCR_RECOGNIZED to verify", 409)

    # External pinned outcome
    verdict = STORE.pinned_tax_verdict.pop(inv["id"], "VALID")

    if verdict == "INVALID":
        inv["ocr_status"] = "REJECTED"
        inv["rejection_reason"] = "Tax authority returned INVALID"
        bump_inv(inv)
        return success(ser_invoice(inv))

    # Duplicate check across other invoices in {TAX_VERIFIED, ATTACHED, CONSUMED}
    if _duplicate_exists(inv["invoice_code"], inv["invoice_number"],
                          exclude_id=inv["id"],
                          statuses={"TAX_VERIFIED", "ATTACHED", "CONSUMED"}):
        raise APIError(ERR_INVOICE_DUPLICATE,
                        "Duplicate invoice already verified elsewhere", 409)

    # Amount > 0
    if inv.get("amount") is None or inv["amount"] <= 0:
        raise APIError(ERR_VALIDATION, "amount must be > 0", 422)

    inv["ocr_status"] = "TAX_VERIFIED"
    bump_inv(inv)
    emit_external_sync(
        subject_type="INVOICE",
        subject_id=inv["id"],
        target="ELECTRONIC_INVOICE",
        event="VERIFIED",
        actor_id=g.user_id,
    )
    return success(ser_invoice(inv))
