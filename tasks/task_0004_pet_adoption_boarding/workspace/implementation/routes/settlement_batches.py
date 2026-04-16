from flask import Blueprint, request
from db import (
    settlement_batches,
    fee_invoices,
    shelters,
    gen_id,
    now_iso,
    parse_iso,
)
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_SHELTER_NOT_FOUND,
    ERR_SETTLEMENT_BATCH_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_INVOICE_STATUS_CHANGED,
)
from middleware import require_roles, parse_pagination
from response import success_response, list_response
from services.fee_service import serialize_settlement_batch

settlement_batches_bp = Blueprint("settlement_batches", __name__)


@settlement_batches_bp.route("/petcare/settlement-batches", methods=["POST"])
def create_batch():
    require_roles("ShelterManager")
    body = request.get_json(silent=True) or {}

    shelter_id = body.get("shelter_id")
    period_start = body.get("period_start")
    period_end = body.get("period_end")

    if not shelter_id:
        raise_error(ERR_INVALID_REQUEST, "shelter_id is required")
    if shelter_id not in shelters:
        raise_error(ERR_SHELTER_NOT_FOUND, "Shelter not found")
    if not period_start or not period_end:
        raise_error(ERR_INVALID_REQUEST, "period_start and period_end are required")

    ps = parse_iso(period_start)
    pe = parse_iso(period_end)
    if ps is None or pe is None:
        raise_error(ERR_INVALID_REQUEST, "Invalid period dates")
    if pe <= ps:
        raise_error(ERR_INVALID_REQUEST, "period_end must be strictly greater than period_start")

    # Walk eligible invoices
    eligible_invoice_ids = []
    gross = 0
    refund_total = 0

    candidates = []
    for inv in fee_invoices.values():
        if inv["shelter_id"] != shelter_id:
            continue
        if inv.get("settlement_batch_id") is not None:
            continue
        if inv["status"] == "PAID":
            paid_at = parse_iso(inv.get("paid_at"))
            if paid_at is None:
                continue
            if ps <= paid_at < pe:
                candidates.append((paid_at, inv))
        elif inv["status"] == "REFUNDED":
            refunded_at = parse_iso(inv.get("refunded_at"))
            if refunded_at is None:
                continue
            if ps <= refunded_at < pe:
                candidates.append((refunded_at, inv))

    candidates.sort(key=lambda t: t[0])
    for _, inv in candidates:
        eligible_invoice_ids.append(inv["id"])
        if inv["status"] == "PAID":
            gross += inv["total_amount_cents"]
        elif inv["status"] == "REFUNDED":
            refund_total += inv["refund_amount_cents"]

    net = max(0, gross - refund_total)

    bid = gen_id()
    ts = now_iso()
    batch = {
        "id": bid,
        "created_at": ts,
        "shelter_id": shelter_id,
        "period_start": period_start,
        "period_end": period_end,
        "invoice_ids": eligible_invoice_ids,
        "gross_amount_cents": gross,
        "refund_amount_cents": refund_total,
        "net_amount_cents": net,
        "approved_by": None,
        "status": "DRAFT",
    }
    settlement_batches[bid] = batch
    return success_response(serialize_settlement_batch(batch), status_code=201)


@settlement_batches_bp.route("/petcare/settlement-batches", methods=["GET"])
def list_batches():
    require_roles("ShelterManager")
    limit, offset = parse_pagination()
    shelter_id = request.args.get("shelter_id")
    status = request.args.get("status")
    items = []
    for b in settlement_batches.values():
        if shelter_id and b["shelter_id"] != shelter_id:
            continue
        if status and b["status"] != status:
            continue
        items.append(b)
    items.sort(key=lambda x: x["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return list_response([serialize_settlement_batch(x) for x in page], total, limit, offset)


@settlement_batches_bp.route("/petcare/settlement-batches/<bid>", methods=["GET"])
def get_batch(bid):
    require_roles("ShelterManager")
    b = settlement_batches.get(bid)
    if not b:
        raise_error(ERR_SETTLEMENT_BATCH_NOT_FOUND, "Settlement batch not found")
    return success_response(serialize_settlement_batch(b))


@settlement_batches_bp.route("/petcare/settlement-batches/<bid>/approve", methods=["POST"])
def approve_batch(bid):
    user_id, _ = require_roles("ShelterManager")
    b = settlement_batches.get(bid)
    if not b:
        raise_error(ERR_SETTLEMENT_BATCH_NOT_FOUND, "Settlement batch not found")
    if b["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, "Batch must be DRAFT")

    # Recheck invoice statuses: every invoice in invoice_ids that was PAID must still be PAID
    for inv_id in b["invoice_ids"]:
        inv = fee_invoices.get(inv_id)
        if not inv:
            raise_error(ERR_INVOICE_STATUS_CHANGED, f"Invoice {inv_id} missing")
        # Invoices included could be PAID or REFUNDED; we only require the PAID ones to remain PAID
        # (i.e., they haven't been refunded in between)
        # A REFUNDED invoice must still be REFUNDED; a PAID invoice that became REFUNDED fails.
        # We treat any invoice that was PAID at composition time — we track that via presence in gross
        # For simplicity, re-evaluate: if invoice currently not in (PAID, REFUNDED), fail.
        if inv["status"] not in ("PAID", "REFUNDED"):
            raise_error(ERR_INVOICE_STATUS_CHANGED,
                        f"Invoice {inv_id} status changed")

    # Need to distinguish which invoices were counted as PAID vs REFUNDED at creation.
    # Since composition recomputes, recompute gross/refund/net here based on current state for correctness
    gross = 0
    refund_total = 0
    for inv_id in b["invoice_ids"]:
        inv = fee_invoices[inv_id]
        if inv["status"] == "PAID":
            gross += inv["total_amount_cents"]
        elif inv["status"] == "REFUNDED":
            refund_total += inv["refund_amount_cents"]
    # But the specification says approval fails if a PAID invoice is no longer PAID.
    # So if any invoice was listed as PAID at batch creation but is now REFUNDED, fail.
    # We use saved gross_amount_cents vs recomputed to detect that change.
    if gross != b["gross_amount_cents"]:
        # An invoice that was PAID has been refunded between creation and approval
        raise_error(ERR_INVOICE_STATUS_CHANGED, "Invoice status changed since batch creation")

    b["status"] = "APPROVED"
    b["approved_by"] = user_id
    for inv_id in b["invoice_ids"]:
        inv = fee_invoices.get(inv_id)
        if inv:
            inv["settlement_batch_id"] = b["id"]
            inv["updated_at"] = now_iso()
            inv["version"] += 1
    return success_response(serialize_settlement_batch(b))


@settlement_batches_bp.route("/petcare/settlement-batches/<bid>/mark-paid", methods=["POST"])
def mark_paid_batch(bid):
    require_roles("ShelterManager")
    b = settlement_batches.get(bid)
    if not b:
        raise_error(ERR_SETTLEMENT_BATCH_NOT_FOUND, "Settlement batch not found")
    if b["status"] != "APPROVED":
        raise_error(ERR_INVALID_STATE, "Batch must be APPROVED")
    b["status"] = "PAID"
    return success_response(serialize_settlement_batch(b))
