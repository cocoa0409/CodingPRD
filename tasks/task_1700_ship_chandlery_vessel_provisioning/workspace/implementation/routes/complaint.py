"""QualityComplaint and CreditNote routes (PRD §3.12, §3.13)."""
from flask import Blueprint, request

import db
from db import stamp_new, touch
from errors import (err_delivery_not_found, err_complaint_not_found,
                    err_credit_note_not_found, err_catalog_item_not_found,
                    err_invalid_request, err_insufficient_permissions,
                    err_qty_exceeds_remaining, err_complaint_not_reviewable,
                    err_complaint_not_reopenable, err_credit_note_not_revocable,
                    err_no_creditable_invoice, err_segregation_of_duties)
from middleware import require_roles, require_any_authenticated
from response import success_object, success_list, parse_pagination
from services.exposure import recompute_agent_exposure
from services.money import fx_convert, round_half_up_cents
from services.pricing import RESTOCKING_MIN_CENTS, RESTOCKING_PCT
from services.validate import get_body, req_string, req_lines_array, req_enum
from routes.invoice import _recompute_outstanding, _rederive_invoice_status, \
    _sync_order_payment_status

bp = Blueprint("complaint", __name__)

REASONS = ("SPOILED", "DAMAGED", "WRONG_ITEM", "SHORT")


def _delivery_chain(delivery):
    order = db.orders.get(delivery["order_id"])
    vessel_call = None
    if order is not None:
        quotation = db.quotations.get(order.get("quotation_id"))
        if quotation is not None:
            requisition = db.requisitions.get(quotation.get("requisition_id"))
            if requisition is not None:
                vessel_call = db.vessel_calls.get(requisition.get("vessel_call_id"))
    return order, vessel_call


# ---------------------------------------------------------------------------
# QualityComplaint
# ---------------------------------------------------------------------------

@bp.route("/chandlery/deliveries/<delivery_id>/complaints", methods=["POST"])
@require_roles("VesselCateringOfficer")
def create_complaint(user_id, role, delivery_id):
    d = db.deliveries.get(delivery_id)
    if d is None:
        raise err_delivery_not_found()
    order, vessel_call = _delivery_chain(d)
    # ownership: officer must own the delivery's order's vessel call
    if vessel_call is None or user_id != vessel_call["id"]:
        raise err_insufficient_permissions()
    # complaints are filed against a DELIVERED delivery
    if d["status"] != "DELIVERED":
        raise err_invalid_request("complaint requires a DELIVERED delivery")

    body = get_body()
    raw_lines = req_lines_array(body, "lines", min_len=1)
    evidence_note = req_string(body, "evidence_note")
    lines = []
    for line in raw_lines:
        catalog_item_id = line.get("catalog_item_id")
        if not isinstance(catalog_item_id, str) or catalog_item_id.strip() == "":
            raise err_invalid_request("missing or invalid field: catalog_item_id")
        if catalog_item_id not in db.catalog_items:
            raise err_catalog_item_not_found()
        rejected_qty = line.get("rejected_qty")
        if isinstance(rejected_qty, bool) or not isinstance(rejected_qty, int):
            raise err_invalid_request("rejected_qty must be an integer")
        if rejected_qty < 1:
            from errors import err_invalid_qty
            raise err_invalid_qty("rejected_qty must be >= 1")
        reason = req_enum(line, "reason", REASONS)
        lines.append({"catalog_item_id": catalog_item_id,
                      "rejected_qty": rejected_qty, "reason": reason})

    # priority 14c: rejected_qty <= delivered qty for that item on this delivery
    confirmed = d.get("confirmed_lines") or []
    for line in lines:
        delivered_qty = sum(cl["qty"] for cl in confirmed
                            if cl["catalog_item_id"] == line["catalog_item_id"])
        if line["rejected_qty"] > delivered_qty:
            raise err_qty_exceeds_remaining()

    complaint = {
        "delivery_id": delivery_id,
        "lines": lines,
        "evidence_note": evidence_note,
        "reopen_count": 0,
        "last_reviewer_user_id": None,
        "status": "SUBMITTED",
    }
    stamp_new(complaint)
    db.complaints[complaint["id"]] = complaint
    return success_object(complaint, status=201)


@bp.route("/chandlery/deliveries/<delivery_id>/complaints", methods=["GET"])
@require_any_authenticated
def list_complaints(user_id, role, delivery_id):
    if delivery_id not in db.deliveries:
        raise err_delivery_not_found()
    items = [c for c in db.complaints.values() if c["delivery_id"] == delivery_id]
    items.sort(key=lambda r: r["created_at"])
    limit, offset = parse_pagination(request.args)
    return success_list(items[offset:offset + limit], limit, offset, len(items))


def _review_gate(complaint, user_id):
    """Shared preconditions for accept/reject: SUBMITTED + four-eyes rule."""
    if complaint["status"] != "SUBMITTED":
        raise err_complaint_not_reviewable()
    if complaint.get("reopen_count", 0) >= 1 \
            and user_id == complaint.get("last_reviewer_user_id"):
        raise err_segregation_of_duties()


def _select_creditable_invoice(order_id):
    """Latest created_at first, tie-break higher total_cents first, over the
    order's invoices in ISSUED | PARTIALLY_PAID. None if the set is empty."""
    candidates = [inv for inv in db.invoices.values()
                  if inv["order_id"] == order_id
                  and inv["status"] in ("ISSUED", "PARTIALLY_PAID")]
    if not candidates:
        return None
    candidates.sort(key=lambda inv: (inv["created_at"], inv["total_cents"]),
                    reverse=True)
    return candidates[0]


@bp.route("/chandlery/complaints/<complaint_id>/accept", methods=["POST"])
@require_roles("QualityAssuranceLead")
def accept_complaint(user_id, role, complaint_id):
    complaint = db.complaints.get(complaint_id)
    if complaint is None:
        raise err_complaint_not_found()
    _review_gate(complaint, user_id)

    delivery = db.deliveries[complaint["delivery_id"]]
    order, vessel_call = _delivery_chain(delivery)

    # creditable invoice selector + amount computation (PRD §3.13)
    invoice = _select_creditable_invoice(order["id"])
    if invoice is None:
        raise err_no_creditable_invoice()
    # gross USD value over accepted complaint lines (match by catalog_item_id;
    # items absent from the invoice contribute 0)
    gross_usd_cents = 0
    for cl in complaint["lines"]:
        inv_line = next((il for il in invoice["lines"]
                         if il["catalog_item_id"] == cl["catalog_item_id"]), None)
        if inv_line is None:
            continue
        gross_usd_cents += inv_line["unit_price_cents"] * cl["rejected_qty"]
    gross_amount_cents = fx_convert(gross_usd_cents, invoice["fx_rate_to_settlement"])
    restocking_fee_cents = max(
        RESTOCKING_MIN_CENTS,
        round_half_up_cents(gross_amount_cents * RESTOCKING_PCT / 100))
    creditable_remaining = invoice["total_cents"] - invoice["credited_amount_cents"]
    amount_cents = min(gross_amount_cents - restocking_fee_cents, creditable_remaining)
    if amount_cents <= 0:
        raise err_no_creditable_invoice()

    # commit complaint
    complaint["status"] = "ACCEPTED"
    complaint["last_reviewer_user_id"] = user_id
    touch(complaint)

    # cascade hop 1: auto-create CreditNote (APPLIED)
    note = {
        "complaint_id": complaint["id"],
        "invoice_id": invoice["id"],
        "gross_amount_cents": gross_amount_cents,
        "restocking_fee_cents": restocking_fee_cents,
        "amount_cents": amount_cents,
        "status": "APPLIED",
    }
    stamp_new(note)
    db.credit_notes[note["id"]] = note

    # cascade hop 2 (CreditNote -> Invoice)
    invoice["credited_amount_cents"] += amount_cents
    _recompute_outstanding(invoice)
    _rederive_invoice_status(invoice)
    touch(invoice)

    # cascade hop 3 (Invoice -> ShipAgent); order payment dimension follows
    _sync_order_payment_status(order, invoice)
    recompute_agent_exposure(order["agent_id"])
    return success_object(complaint)


@bp.route("/chandlery/complaints/<complaint_id>/reject", methods=["POST"])
@require_roles("QualityAssuranceLead")
def reject_complaint(user_id, role, complaint_id):
    complaint = db.complaints.get(complaint_id)
    if complaint is None:
        raise err_complaint_not_found()
    _review_gate(complaint, user_id)
    complaint["status"] = "REJECTED"
    complaint["last_reviewer_user_id"] = user_id
    touch(complaint)
    return success_object(complaint)


@bp.route("/chandlery/complaints/<complaint_id>/reopen", methods=["POST"])
@require_roles("VesselCateringOfficer")
def reopen_complaint(user_id, role, complaint_id):
    complaint = db.complaints.get(complaint_id)
    if complaint is None:
        raise err_complaint_not_found()
    delivery = db.deliveries.get(complaint["delivery_id"])
    order, vessel_call = _delivery_chain(delivery) if delivery else (None, None)
    # ownership: officer of the delivery's order's vessel call
    if vessel_call is None or user_id != vessel_call["id"]:
        raise err_insufficient_permissions()
    if complaint["status"] != "REJECTED":
        raise err_complaint_not_reopenable()
    complaint["status"] = "SUBMITTED"
    complaint["reopen_count"] = complaint.get("reopen_count", 0) + 1
    touch(complaint)
    return success_object(complaint)


# ---------------------------------------------------------------------------
# CreditNote
# ---------------------------------------------------------------------------

@bp.route("/chandlery/credit-notes", methods=["GET"])
@require_any_authenticated
def list_credit_notes(user_id, role):
    complaint_id = request.args.get("complaint_id")
    invoice_id = request.args.get("invoice_id")
    items = list(db.credit_notes.values())
    if complaint_id is not None:
        items = [n for n in items if n["complaint_id"] == complaint_id]
    if invoice_id is not None:
        items = [n for n in items if n["invoice_id"] == invoice_id]
    items.sort(key=lambda r: r["created_at"])
    limit, offset = parse_pagination(request.args)
    return success_list(items[offset:offset + limit], limit, offset, len(items))


@bp.route("/chandlery/credit-notes/<note_id>", methods=["GET"])
@require_any_authenticated
def get_credit_note(user_id, role, note_id):
    note = db.credit_notes.get(note_id)
    if note is None:
        raise err_credit_note_not_found()
    return success_object(note)


@bp.route("/chandlery/credit-notes/<note_id>/revoke", methods=["POST"])
@require_roles("FinanceController")
def revoke_credit_note(user_id, role, note_id):
    note = db.credit_notes.get(note_id)
    if note is None:
        raise err_credit_note_not_found()
    if note["status"] != "APPLIED":
        raise err_credit_note_not_revocable()
    note["status"] = "REVOKED"
    touch(note)

    # compensation (CreditNote -> Invoice)
    invoice = db.invoices.get(note["invoice_id"])
    if invoice is not None:
        invoice["credited_amount_cents"] -= note["amount_cents"]
        _recompute_outstanding(invoice)
        _rederive_invoice_status(invoice)
        touch(invoice)
        # compensation (Invoice -> ShipAgent); order payment dimension follows
        order = db.orders.get(invoice["order_id"])
        if order is not None:
            _sync_order_payment_status(order, invoice)
            recompute_agent_exposure(order["agent_id"])
    return success_object(note)
