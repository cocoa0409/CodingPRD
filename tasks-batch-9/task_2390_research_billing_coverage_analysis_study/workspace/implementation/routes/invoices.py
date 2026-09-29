"""Sponsor invoicing: the waterfall selector, submission, remittance and disputes."""

from flask import Blueprint

import derive
import envelope
import lookup
import serializers
import store
import validation as v
from auth import require
from errors import ApiError

bp = Blueprint("invoices", __name__, url_prefix="/research-billing")

OUTCOMES = ("PAID_IN_FULL", "SHORT_PAID", "DISPUTED")


def _apply_selection(invoice, study, selected, subtotal, indirect):
    money = derive.invoice_money(subtotal, indirect)
    invoice["line_count"] = len(selected)
    invoice.update(money)
    for charge in selected:
        charge["sponsor_invoice_id"] = invoice["id"]
        store.touch(charge)


@bp.post("/sponsor-invoices")
@require("ResearchBillingManager")
def create_invoice():
    body = v.body()
    study_id = v.req_id(body, "study_id")
    period_end_date = v.req_date(body, "period_end_date")
    expected_version = v.req_int(body, "expected_study_version")

    study = lookup.study(study_id)
    if expected_version != study["version"]:
        raise ApiError("ERR_STALE_STUDY_VERSION")

    selected, subtotal, indirect = derive.select_invoice_lines(study, period_end_date)
    if not selected:
        raise ApiError("ERR_NO_INVOICEABLE_CHARGES")

    sequence_number = len(derive.invoices_of(study["id"])) + 1
    rec = store.base_record()
    rec.update({
        "study_id": study["id"],
        "sequence_number": sequence_number,
        "invoice_number": "INV-%s-%03d" % (study["protocol_number"], sequence_number),
        "period_end_date": period_end_date,
        "status": "DRAFT",
        "line_count": 0,
        "subtotal_cents": 0,
        "indirect_cents": 0,
        "gross_total_cents": 0,
        "volume_credit_cents": 0,
        "net_total_cents": 0,
        "amount_paid_cents": 0,
        "short_paid": False,
        "submitted_at": None,
    })
    store.invoices[rec["id"]] = rec
    _apply_selection(rec, study, selected, subtotal, indirect)
    store.touch(study)
    return envelope.created(serializers.invoice(rec))


@bp.post("/sponsor-invoices/<invoice_id>/submit")
@require("ResearchBillingManager")
def submit_invoice(invoice_id):
    rec = lookup.invoice(invoice_id)
    if rec["status"] not in ("DRAFT", "DISPUTED"):
        raise ApiError("ERR_INVOICE_NOT_SUBMITTABLE")

    study = lookup.study(rec["study_id"])
    if derive.billing_hold_posture(study) == "ALL_BLOCKED":
        raise ApiError("ERR_STUDY_BILLING_BLOCKED")

    if rec["status"] == "DISPUTED":
        selected, subtotal, indirect = derive.select_invoice_lines(
            study, rec["period_end_date"])
        if not selected:
            raise ApiError("ERR_NO_INVOICEABLE_CHARGES")
        _apply_selection(rec, study, selected, subtotal, indirect)
    elif rec["line_count"] < 1:
        raise ApiError("ERR_NO_INVOICEABLE_CHARGES")

    rec["status"] = "SUBMITTED"
    rec["submitted_at"] = store.now()
    store.touch(rec)

    for charge in derive.charges_of(study["id"]):
        if charge["sponsor_invoice_id"] == rec["id"] and charge["billing_state"] == "UNBILLED":
            charge["billing_state"] = "INVOICED_SPONSOR"
            store.touch(charge)
    return envelope.ok(serializers.invoice(rec))


@bp.post("/sponsor-invoices/<invoice_id>/remittance")
@require("ResearchBillingManager")
def remittance(invoice_id):
    body = v.body()
    outcome = v.req_enum(body, "outcome", OUTCOMES)
    amount_paid = v.opt_int(body, "amount_paid_cents", default=None)

    rec = lookup.invoice(invoice_id)
    if rec["status"] != "SUBMITTED":
        raise ApiError("ERR_INVOICE_NOT_SUBMITTABLE")

    net_total = rec["net_total_cents"]

    if outcome == "PAID_IN_FULL":
        if amount_paid is not None and amount_paid != net_total:
            raise ApiError("ERR_REMITTANCE_AMOUNT_INVALID")
        recorded = net_total if amount_paid is None else amount_paid
        rec["status"] = "PAID"
        rec["amount_paid_cents"] = recorded
        rec["short_paid"] = recorded < net_total
        store.touch(rec)
        return envelope.ok(serializers.invoice(rec))

    if outcome == "SHORT_PAID":
        if amount_paid is None or amount_paid < 0 or amount_paid >= net_total:
            raise ApiError("ERR_REMITTANCE_AMOUNT_INVALID")
        rec["status"] = "PAID"
        rec["amount_paid_cents"] = amount_paid
        rec["short_paid"] = amount_paid < net_total
        store.touch(rec)
        return envelope.ok(serializers.invoice(rec))

    # DISPUTED - release every line back to the unbilled pool, unbilled_since intact
    rec["status"] = "DISPUTED"
    for charge in derive.charges_of(rec["study_id"]):
        if charge["sponsor_invoice_id"] != rec["id"]:
            continue
        if charge["billing_state"] == "INVOICED_SPONSOR":
            charge["billing_state"] = "UNBILLED"
        charge["sponsor_invoice_id"] = None
        store.touch(charge)

    rec["line_count"] = 0
    rec["subtotal_cents"] = 0
    rec["indirect_cents"] = 0
    rec["gross_total_cents"] = 0
    rec["volume_credit_cents"] = 0
    rec["net_total_cents"] = 0
    store.touch(rec)
    return envelope.ok(serializers.invoice(rec))
