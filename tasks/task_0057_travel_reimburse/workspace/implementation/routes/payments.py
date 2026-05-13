"""Payment endpoints."""

from __future__ import annotations

from decimal import Decimal

from flask import Blueprint, g, request

from db import STORE
from errors import (
    APIError, ERR_FORBIDDEN, ERR_INVALID_STATE, ERR_NOT_FOUND, ERR_VALIDATION,
    ERR_INVALID_BATCH, ERR_PAYMENT_AMOUNT_MISMATCH, ERR_PAYMENT_RETRY_EXHAUSTED,
)
from middleware import require_auth
from response import success, parse_pagination, paginate
from serializers import payment as ser_payment
from services.audit import emit_external_sync, write_audit_log
from services.travel_application import bump
from services.validate import require_body, get_enum, get_str
from utils import CLOCK, new_uuid


bp = Blueprint("payments", __name__)


CHANNELS = {"BANK_TRANSFER", "CORPORATE_CARD_REFUND", "INTERNAL_WALLET"}
PAYMENT_STATUSES = {"PENDING", "EXECUTING", "SUCCESS", "FAILED", "RETRYING"}
MAX_PAYMENT_ATTEMPTS = 3


def _load_payment_or_404(pid):
    row = STORE.payments.get(pid)
    if not row:
        raise APIError(ERR_NOT_FOUND, f"Payment {pid} not found", 404)
    return row


@bp.route("/payments/batches", methods=["POST"])
@require_auth(["Finance"])
def create_payment_batch():
    body = require_body(request.get_json(silent=True))
    form_ids = body.get("form_ids")
    if not isinstance(form_ids, list) or len(form_ids) == 0:
        raise APIError(ERR_VALIDATION, "form_ids must be a non-empty list", 422)
    if any(not isinstance(f, str) for f in form_ids):
        raise APIError(ERR_VALIDATION, "form_ids must be strings", 422)
    channel = get_enum(body, "channel", CHANNELS)

    # Validate the whole batch atomically
    if len(set(form_ids)) != len(form_ids):
        raise APIError(ERR_INVALID_BATCH, "Duplicate form_ids in batch", 422)
    forms = []
    for fid in form_ids:
        form = STORE.reimbursement_forms.get(fid)
        if not form:
            raise APIError(ERR_INVALID_BATCH, f"Unknown form_id {fid}", 422)
        if form["status"] != "APPROVED":
            raise APIError(ERR_INVALID_BATCH,
                            f"Form {fid} is not in APPROVED", 422)
        forms.append(form)

    # Sort by (applicant_id ASC, created_at ASC)
    forms.sort(key=lambda f: (f["applicant_id"], f["created_at"]))

    batch_id = new_uuid()
    now = CLOCK.now_iso()
    payments = []
    for form in forms:
        pid = new_uuid()
        amount = form["total_reimbursable"]
        if amount is None or amount <= 0:
            # Required positive amount; spec says amount > 0 to execute
            # Still create payment but mark with the form's total_reimbursable
            amount = amount or Decimal("0.00")
        payment = {
            "id": pid,
            "form_id": form["id"],
            "channel": channel,
            "amount": amount,
            "batch_id": batch_id,
            "status": "PENDING",
            "attempt_count": 0,
            "external_ref": None,
            "failure_reason": None,
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        STORE.payments[pid] = payment
        payments.append(payment)

    batch_total = sum((p["amount"] for p in payments), Decimal("0.00"))
    return success({
        "batch_id": batch_id,
        "channel": channel,
        "batch_total": float(batch_total),
        "payments": [ser_payment(p) for p in payments],
    }, status=201)


@bp.route("/payments/<pid>/execute", methods=["POST"])
@require_auth(["Finance"])
def execute_payment(pid):
    p = _load_payment_or_404(pid)
    if p["status"] not in {"PENDING", "RETRYING"}:
        raise APIError(ERR_INVALID_STATE, "Payment is not in PENDING or RETRYING", 409)
    form = STORE.reimbursement_forms.get(p["form_id"])
    if not form:
        raise APIError(ERR_NOT_FOUND, "Parent form missing", 404)
    if form["status"] != "APPROVED":
        raise APIError(ERR_INVALID_STATE, "Parent form is not APPROVED", 409)
    if p["amount"] != form["total_reimbursable"]:
        raise APIError(ERR_PAYMENT_AMOUNT_MISMATCH,
                        "Payment.amount no longer matches form.total_reimbursable", 422)
    if p["amount"] is None or p["amount"] <= 0:
        raise APIError(ERR_VALIDATION, "Payment amount must be > 0", 422)

    p["status"] = "EXECUTING"
    p["attempt_count"] = p.get("attempt_count", 0) + 1
    bump(p)
    return success(ser_payment(p))


@bp.route("/payments/<pid>/result", methods=["POST"])
@require_auth(["Finance", "Admin"])
def payment_result(pid):
    p = _load_payment_or_404(pid)
    if p["status"] != "EXECUTING":
        raise APIError(ERR_INVALID_STATE, "Payment is not in EXECUTING", 409)
    body = require_body(request.get_json(silent=True))
    outcome = get_enum(body, "outcome", {"SUCCESS", "FAILED"})
    external_ref = body.get("external_ref")
    failure_reason = body.get("failure_reason")
    if external_ref is not None and not isinstance(external_ref, str):
        raise APIError(ERR_VALIDATION, "external_ref must be a string", 422)
    if failure_reason is not None and not isinstance(failure_reason, str):
        raise APIError(ERR_VALIDATION, "failure_reason must be a string", 422)

    form = STORE.reimbursement_forms.get(p["form_id"])
    if not form:
        raise APIError(ERR_NOT_FOUND, "Parent form missing", 404)

    if outcome == "SUCCESS":
        p["status"] = "SUCCESS"
        p["external_ref"] = external_ref
        bump(p)
        # Cascade form APPROVED -> PAID
        form["status"] = "PAID"
        bump(form)
        # Cascade attached invoices ATTACHED -> CONSUMED
        for it in STORE.reimbursement_items.values():
            if it["form_id"] != form["id"]:
                continue
            inv = STORE.invoices.get(it["invoice_id"])
            if inv and inv["ocr_status"] == "ATTACHED":
                inv["ocr_status"] = "CONSUMED"
                inv["updated_at"] = CLOCK.now_iso()
                inv["version"] = inv.get("version", 0) + 1
        # Audit + external sync
        write_audit_log(
            event_type="PAYMENT_EVENT",
            subject_type="PAYMENT",
            subject_id=p["id"],
            actor_id=g.user_id,
            payload={
                "form_id": form["id"],
                "amount": float(p["amount"]),
                "channel": p["channel"],
            },
        )
        emit_external_sync(
            subject_type="REIMBURSEMENT_FORM",
            subject_id=form["id"],
            target="FINANCE_SYSTEM",
            event="REIMBURSEMENT_POSTED",
            actor_id=g.user_id,
        )
        emit_external_sync(
            subject_type="PAYMENT",
            subject_id=p["id"],
            target="BANKING",
            event="PAID",
            actor_id=g.user_id,
        )
    else:
        # FAILED
        p["status"] = "FAILED"
        p["failure_reason"] = failure_reason
        bump(p)
        # If attempt_count reached MAX, cascade form -> FAILED
        if p["attempt_count"] >= MAX_PAYMENT_ATTEMPTS:
            if form["status"] == "APPROVED":
                form["status"] = "FAILED"
                bump(form)
                write_audit_log(
                    event_type="PAYMENT_EVENT",
                    subject_type="REIMBURSEMENT_FORM",
                    subject_id=form["id"],
                    actor_id=g.user_id,
                    payload={"event": "FORM_FAILED_EXHAUSTED"},
                )
        else:
            write_audit_log(
                event_type="PAYMENT_EVENT",
                subject_type="PAYMENT",
                subject_id=p["id"],
                actor_id=g.user_id,
                payload={"event": "FAILED", "failure_reason": failure_reason},
            )
    return success(ser_payment(p))


@bp.route("/payments/<pid>/retry", methods=["POST"])
@require_auth(["Finance"])
def retry_payment(pid):
    p = _load_payment_or_404(pid)
    if p["status"] != "FAILED":
        raise APIError(ERR_INVALID_STATE, "Payment is not in FAILED", 409)
    if p["attempt_count"] >= MAX_PAYMENT_ATTEMPTS:
        raise APIError(ERR_PAYMENT_RETRY_EXHAUSTED,
                        "Payment retry attempts exhausted", 422)
    p["status"] = "RETRYING"
    bump(p)
    return success(ser_payment(p))


@bp.route("/payments/<pid>", methods=["GET"])
@require_auth(["Finance", "Applicant", "Admin"])
def get_payment(pid):
    p = _load_payment_or_404(pid)
    if g.role == "Applicant":
        form = STORE.reimbursement_forms.get(p["form_id"])
        if not form or form["applicant_id"] != g.user_id:
            raise APIError(ERR_FORBIDDEN, "Applicant is not the owner", 403)
    return success(ser_payment(p))


@bp.route("/payments", methods=["GET"])
@require_auth(["Finance", "Admin"])
def list_payments():
    limit, offset = parse_pagination()
    rows = list(STORE.payments.values())
    batch_id = request.args.get("batch_id")
    status_f = request.args.get("status")
    form_id = request.args.get("form_id")
    if batch_id is not None:
        rows = [r for r in rows if r["batch_id"] == batch_id]
    if status_f is not None:
        if status_f not in PAYMENT_STATUSES:
            raise APIError(ERR_VALIDATION, "status filter invalid", 422)
        rows = [r for r in rows if r["status"] == status_f]
    if form_id is not None:
        rows = [r for r in rows if r["form_id"] == form_id]
    rows.sort(key=lambda r: r["created_at"])
    page, pag = paginate(rows, limit, offset)
    return success([ser_payment(r) for r in page], pagination=pag)
