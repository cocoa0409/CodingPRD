"""Checkout invoices, payment transactions and donor receipts."""
from flask import Blueprint

import calc
import ledger
from core import (
    ALL_ROLES, ApiError, authenticate, body, clock_dt, db, fetch, get_bool,
    get_enum, get_int, get_str, new_row, ok, ok_list, own_check, paged,
    pagination, public, q, q_enum, rows, touch,
)

bp = Blueprint("money", __name__)

INVOICE_STATUSES = ("OPEN", "PENDING_PAYMENT", "PARTIALLY_PAID", "PAID", "VOID")
PAYMENT_STATUSES = ("CAPTURED", "VOIDED")
METHODS = ("CARD", "CASH", "CHECK")


# ---------------------------------------------------------------- invoices
@bp.post("/api/invoices")
def create_invoice():
    authenticate(("FinanceOfficer", "EventOrganizer"))
    payload = body()
    event_id = get_str(payload, "event_id")
    bidder_id = get_str(payload, "bidder_id")
    cover = get_bool(payload, "cover_processing_fee", required=False, default=False)
    event = fetch("events", event_id)
    fetch("bidders", bidder_id)
    calc.gate(event)
    invoice = new_row(event_id=event_id, bidder_id=bidder_id,
                      cover_processing_fee=cover, line_items=[],
                      line_subtotal_cents=0, processing_fee_cents=0,
                      total_due_cents=0, amount_paid_cents=0,
                      balance_due_cents=0, status="OPEN")
    db.invoices[invoice["id"]] = invoice
    return ok(public(invoice), 201)


@bp.get("/api/invoices/<iid>")
def read_invoice(iid):
    authenticate(ALL_ROLES)
    return ok(public(fetch("invoices", iid)))


@bp.get("/api/invoices")
def list_invoices():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    event_id = q("event_id")
    bidder_id = q("bidder_id")
    status = q_enum("status", INVOICE_STATUSES)
    items = [i for i in rows("invoices")
             if (event_id is None or i["event_id"] == event_id)
             and (bidder_id is None or i["bidder_id"] == bidder_id)
             and (status is None or i["status"] == status)]
    window, total = paged(items, limit, offset)
    return ok_list(window, limit, offset, total)


@bp.post("/api/invoices/<iid>/finalize")
def finalize_invoice(iid):
    authenticate(("FinanceOfficer",))
    invoice = fetch("invoices", iid)
    calc.gate(fetch("events", invoice["event_id"]))
    if invoice["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "invoice is not OPEN")

    orders = [o for o in rows("orders")
              if o["event_id"] == invoice["event_id"]
              and o["bidder_id"] == invoice["bidder_id"]
              and o["payment_status"] == "UNBILLED"]
    gifts = [g for g in rows("paddles")
             if g["event_id"] == invoice["event_id"]
             and g["bidder_id"] == invoice["bidder_id"]
             and g["settlement_status"] == "UNSETTLED"]

    prospective = sum(l["amount_cents"] for l in invoice["line_items"]
                      if l["line_type"] != "PROCESSING_FEE")
    prospective += sum(o["subtotal_cents"] for o in orders)
    prospective += sum(g["level_cents"] for g in gifts)
    if prospective <= 0:
        raise ApiError("ERR_INVALID_STATE", "the invoice has nothing to bill")

    for order in orders:
        order["payment_status"] = "INVOICED"
        order["invoice_id"] = invoice["id"]
        touch(order)
        calc.append_line(invoice, "TICKET", order["id"], order["subtotal_cents"])
    for gift in gifts:
        gift["settlement_status"] = "INVOICED"
        gift["invoice_id"] = invoice["id"]
        touch(gift)
        calc.append_line(invoice, "PADDLE_RAISE", gift["id"], gift["level_cents"])

    invoice["status"] = "PENDING_PAYMENT"
    calc.recompute_invoice(invoice)
    ledger.bump_bidder(invoice["bidder_id"])
    ledger.bump_event(invoice["event_id"])
    return ok(public(invoice))


@bp.post("/api/invoices/<iid>/void")
def void_invoice(iid):
    authenticate(("FinanceOfficer",))
    invoice = fetch("invoices", iid)
    calc.gate(fetch("events", invoice["event_id"]))
    status = invoice["status"]
    if status not in ("OPEN", "PENDING_PAYMENT"):
        raise ApiError("ERR_INVALID_STATE", "invoice cannot be voided from %s" % status)
    if status == "PENDING_PAYMENT" and invoice["amount_paid_cents"] != 0:
        raise ApiError("ERR_INVOICE_NOT_PAYABLE", "the invoice has already taken money")

    if status == "OPEN":
        ledger.detach_lots(invoice)
        invoice["status"] = "VOID"
        touch(invoice)
    else:
        ledger.detach_all(invoice)
        invoice["status"] = "VOID"
        touch(invoice)
        ledger.bump_event(invoice["event_id"])
        ledger.bump_bidder(invoice["bidder_id"])
    return ok(public(invoice))


# ---------------------------------------------------------------- payments
@bp.post("/api/payments")
def capture_payment():
    uid, role = authenticate(("FinanceOfficer", "Bidder"))
    payload = body()
    invoice_id = get_str(payload, "invoice_id")
    amount = get_int(payload, "amount_cents", minimum=1)
    method = get_enum(payload, "method", METHODS)
    invoice = fetch("invoices", invoice_id)
    if role == "Bidder":
        own_check(invoice["bidder_id"] == uid)
    calc.gate(fetch("events", invoice["event_id"]))
    if invoice["status"] not in ("PENDING_PAYMENT", "PARTIALLY_PAID"):
        raise ApiError("ERR_INVOICE_NOT_PAYABLE", "the invoice is not payable")
    if amount > invoice["balance_due_cents"]:
        raise ApiError("ERR_PAYMENT_EXCEEDS_BALANCE", "amount exceeds the balance due")

    payment = new_row(invoice_id=invoice["id"], amount_cents=amount, method=method,
                      status="CAPTURED", captured_by_user_id=uid,
                      voided_by_user_id=None, void_reason=None)
    db.payments[payment["id"]] = payment

    paid = sum(p["amount_cents"] for p in db.payments.values()
               if p["invoice_id"] == invoice["id"] and p["status"] == "CAPTURED")
    became_paid = paid >= invoice["total_due_cents"]
    invoice["status"] = "PAID" if became_paid else "PARTIALLY_PAID"
    calc.recompute_invoice(invoice)
    if became_paid:
        ledger.settle_paid(invoice)
    ledger.bump_event(invoice["event_id"])
    ledger.bump_bidder(invoice["bidder_id"])
    return ok(public(payment), 201)


@bp.get("/api/payments/<pid>")
def read_payment(pid):
    authenticate(ALL_ROLES)
    return ok(public(fetch("payments", pid)))


@bp.get("/api/payments")
def list_payments():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    invoice_id = q("invoice_id")
    status = q_enum("status", PAYMENT_STATUSES)
    items = [p for p in rows("payments")
             if (invoice_id is None or p["invoice_id"] == invoice_id)
             and (status is None or p["status"] == status)]
    window, total = paged(items, limit, offset)
    return ok_list(window, limit, offset, total)


@bp.post("/api/payments/<pid>/void")
def void_payment(pid):
    uid, _role = authenticate(("FinanceOfficer",))
    payload = body()
    reason = get_str(payload, "reason")
    payment = fetch("payments", pid)
    invoice = db.invoices.get(payment["invoice_id"])
    if invoice is not None:
        calc.gate(fetch("events", invoice["event_id"]))
    if payment["status"] != "CAPTURED":
        raise ApiError("ERR_INVALID_STATE", "payment is not CAPTURED")
    if any(r["invoice_id"] == payment["invoice_id"] for r in db.receipts.values()):
        raise ApiError("ERR_RECEIPT_ALREADY_ISSUED", "a receipt has already been issued")
    if uid == payment["captured_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "the capturing user may not void the payment")

    payment["status"] = "VOIDED"
    payment["voided_by_user_id"] = uid
    payment["void_reason"] = reason
    touch(payment)

    if invoice is not None:
        was_paid = invoice["status"] == "PAID"
        paid = sum(p["amount_cents"] for p in db.payments.values()
                   if p["invoice_id"] == invoice["id"] and p["status"] == "CAPTURED")
        if was_paid:
            ledger.unsettle_paid(invoice)
        invoice["status"] = "PARTIALLY_PAID" if paid > 0 else "PENDING_PAYMENT"
        calc.recompute_invoice(invoice)
        ledger.bump_event(invoice["event_id"])
        ledger.bump_bidder(invoice["bidder_id"])
    return ok(public(payment))


# ---------------------------------------------------------------- receipts
@bp.post("/api/receipts")
def issue_receipt():
    authenticate(("FinanceOfficer",))
    payload = body()
    invoice_id = get_str(payload, "invoice_id")
    invoice = fetch("invoices", invoice_id)
    calc.gate(fetch("events", invoice["event_id"]))
    if invoice["status"] != "PAID":
        raise ApiError("ERR_INVALID_STATE", "the invoice is not fully paid")
    if any(r["invoice_id"] == invoice["id"] for r in db.receipts.values()):
        raise ApiError("ERR_RECEIPT_ALREADY_ISSUED", "a receipt already exists")
    benefit, deductible = calc.receipt_amounts(invoice)
    receipt = new_row(invoice_id=invoice["id"], bidder_id=invoice["bidder_id"],
                      total_paid_cents=invoice["amount_paid_cents"],
                      benefit_value_cents=benefit,
                      tax_deductible_cents=deductible,
                      issued_at_utc=db.clock)
    db.receipts[receipt["id"]] = receipt
    return ok(public(receipt), 201)


@bp.get("/api/receipts/<rid>")
def read_receipt(rid):
    authenticate(ALL_ROLES)
    return ok(public(fetch("receipts", rid)))


@bp.get("/api/receipts")
def list_receipts():
    authenticate(ALL_ROLES)
    limit, offset = pagination()
    invoice_id = q("invoice_id")
    bidder_id = q("bidder_id")
    items = [r for r in rows("receipts")
             if (invoice_id is None or r["invoice_id"] == invoice_id)
             and (bidder_id is None or r["bidder_id"] == bidder_id)]
    window, total = paged(items, limit, offset)
    return ok_list(window, limit, offset, total)
