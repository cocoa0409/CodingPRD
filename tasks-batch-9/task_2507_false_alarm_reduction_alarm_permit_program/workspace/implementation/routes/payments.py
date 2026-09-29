"""Payments: the dunning waterfall, the explicit split and the compensating void."""

from flask import Blueprint

import engine
import rt
from core import (F, authenticate, check_owner, created, listing, ok, q,
                  q_instant, validate)
from errors import ApiError
from store import add_days, base_row, now, order_key, store, touch

bp = Blueprint("payments", __name__)

POST_ROLES = ["BillingClerk", "ProgramAdministrator"]
ADMIN = ["ProgramAdministrator"]
READ_ROLES = ["ProgramAdministrator", "BillingClerk", "PermitClerk", "AlarmUser"]

METHODS = ("CARD", "CHECK", "CASH", "ACH")
MODES = ("AUTO_WATERFALL", "EXPLICIT")
VOID_WINDOW_DAYS = 2
PAYABLE_STATUSES = ("UNPAID", "PARTIALLY_PAID")

CREATE_FIELDS = [
    F("alarm_site_id", "uuid"),
    F("amount_cents", "int", min=1),
    F("tendered_on", "ts"),
    F("method", "enum", values=METHODS),
    F("allocation_mode", "enum", values=MODES),
    F("expected_alarm_site_version", "int"),
    F("explicit_allocations", "array", required=False),
]

VOID_FIELDS = [F("void_reason", "string")]


def _candidates(site_id):
    rows = [inv for inv in engine.site_invoices(site_id)
            if inv.get("payment_status") in PAYABLE_STATUSES
            and inv.get("collections_stage") != "WRITTEN_OFF"]
    for inv in rows:
        engine.recompute_outstanding(inv)
    return sorted(rows, key=lambda inv: (
        -engine.STAGE_RANK.get(inv.get("collections_stage"), 0),
        inv.get("due_on"), order_key(inv)))


def _new_allocation(payment, invoice, amount, sequence_index):
    row = base_row(with_common=False)
    row["payment_record_id"] = payment["id"]
    row["penalty_invoice_id"] = invoice["id"]
    row["amount_cents"] = amount
    row["sequence_index"] = sequence_index
    row["status"] = "APPLIED"
    store.payment_allocations[row["id"]] = row
    invoice["paid_cents"] = (invoice.get("paid_cents") or 0) + amount
    engine.settle_check(invoice)
    touch(invoice)
    return row


def _read_explicit(entries):
    """Shape check for the explicit split, reported at position 5."""
    parsed = []
    if not isinstance(entries, list) or not entries:
        raise ApiError("ERR_INVALID_FIELD_VALUE",
                       "explicit_allocations must be a non-empty array.")
    for entry in entries:
        if not isinstance(entry, dict):
            raise ApiError("ERR_INVALID_FIELD_VALUE",
                           "explicit_allocations entries must be objects.")
        invoice_id = entry.get("penalty_invoice_id")
        amount = entry.get("amount_cents")
        if not isinstance(invoice_id, str) or isinstance(amount, bool) \
                or not isinstance(amount, int) or amount < 0:
            raise ApiError("ERR_INVALID_FIELD_VALUE",
                           "explicit_allocations entries are malformed.")
        parsed.append((invoice_id, amount))
    return parsed


@bp.post("/payment-records")
def post_payment():
    ctx = authenticate(POST_ROLES)
    data = validate(ctx.body, CREATE_FIELDS)
    site = rt.resolve("AlarmSite", data["alarm_site_id"])
    mode = data["allocation_mode"]
    entries = []
    if mode == "EXPLICIT":
        entries = _read_explicit(data.get("explicit_allocations"))
    targets = [rt.resolve("PenaltyInvoice", invoice_id)
               for invoice_id, _ in entries]
    if data["expected_alarm_site_version"] != site.get("version"):
        raise ApiError("ERR_STALE_ALARM_SITE_VERSION",
                       "The premises has been modified since it was read.")
    for invoice in targets:
        if invoice.get("collections_stage") == "WRITTEN_OFF":
            raise ApiError("ERR_INVOICE_WRITTEN_OFF",
                           "A written-off invoice may not be paid.")

    amount = data["amount_cents"]
    plan = []
    if mode == "EXPLICIT":
        total = 0
        seen = []
        for (invoice_id, entry_amount), invoice in zip(entries, targets):
            engine.recompute_outstanding(invoice)
            if entry_amount < 1 \
                    or entry_amount > invoice["outstanding_cents"] \
                    or invoice.get("alarm_site_id") != site["id"] \
                    or invoice.get("payment_status") not in PAYABLE_STATUSES \
                    or invoice_id in seen:
                raise ApiError("ERR_ALLOCATION_MISMATCH",
                               "The explicit split is not payable as written.")
            seen.append(invoice_id)
            total += entry_amount
            plan.append((invoice, entry_amount))
        if total != amount:
            raise ApiError("ERR_ALLOCATION_MISMATCH",
                           "The allocation lines must sum to the tender.")
        credited = 0
    else:
        remainder = amount
        for invoice in _candidates(site["id"]):
            if remainder <= 0:
                break
            applied = min(remainder, invoice["outstanding_cents"])
            if applied <= 0:
                continue
            plan.append((invoice, applied))
            remainder -= applied
        credited = remainder

    payment = base_row()
    payment["alarm_site_id"] = site["id"]
    payment["amount_cents"] = amount
    payment["tendered_on"] = data["tendered_on"]
    payment["method"] = data["method"]
    payment["allocation_mode"] = mode
    payment["receipt_number"] = store.next_receipt_number()
    payment["recorded_by_user_id"] = ctx.user_id
    payment["status"] = "APPLIED"
    payment["allocated_cents"] = amount - credited
    payment["credited_cents"] = credited
    payment["voided_at"] = None
    payment["void_reason"] = None
    store.payment_records[payment["id"]] = payment

    for index, (invoice, applied) in enumerate(plan, start=1):
        _new_allocation(payment, invoice, applied, index)
    if credited:
        site["credit_balance_cents"] = (site.get("credit_balance_cents") or 0) \
            + credited
    engine.rollup_site(site)
    return created(payment)


@bp.post("/payment-records/<payment_id>/void")
def void_payment(payment_id):
    ctx = authenticate(ADMIN)
    data = validate(ctx.body, VOID_FIELDS)
    payment = rt.resolve("PaymentRecord", payment_id)
    if payment.get("status") != "APPLIED":
        raise ApiError("ERR_INVALID_STATE",
                       "Only an APPLIED payment may be voided.")
    allocations = engine.allocations_for_payment(payment["id"])
    tendered = payment.get("tendered_on")
    if tendered is not None and now() > add_days(tendered, VOID_WINDOW_DAYS):
        raise ApiError("ERR_PAYMENT_VOID_WINDOW_CLOSED",
                       "The %d-day void window has closed." % VOID_WINDOW_DAYS)
    for allocation in allocations:
        invoice = store.penalty_invoices.get(allocation.get("penalty_invoice_id"))
        if invoice is not None \
                and invoice.get("collections_stage") == "WRITTEN_OFF":
            raise ApiError("ERR_PAYMENT_VOID_WINDOW_CLOSED",
                           "An allocated invoice has since been written off.")

    payment["status"] = "VOIDED"
    payment["voided_at"] = now()
    payment["void_reason"] = data["void_reason"]
    touch(payment)
    for allocation in allocations:
        if allocation.get("status") != "APPLIED":
            continue
        allocation["status"] = "REVERSED"
        invoice = store.penalty_invoices.get(allocation.get("penalty_invoice_id"))
        if invoice is None:
            continue
        invoice["paid_cents"] = max(
            0, (invoice.get("paid_cents") or 0)
            - (allocation.get("amount_cents") or 0))
        engine.settle_check(invoice)
        touch(invoice)
    site = store.alarm_sites.get(payment.get("alarm_site_id"))
    if site is not None:
        credited = payment.get("credited_cents") or 0
        if credited:
            site["credit_balance_cents"] = max(
                0, (site.get("credit_balance_cents") or 0) - credited)
        engine.rollup_site(site)
    return ok(payment)


@bp.get("/payment-records/<payment_id>")
def get_payment(payment_id):
    ctx = authenticate(READ_ROLES)
    payment = rt.resolve("PaymentRecord", payment_id)
    check_owner(ctx, site_id=payment.get("alarm_site_id"))
    return ok(payment)


@bp.get("/payment-records")
def list_payments():
    ctx = authenticate(READ_ROLES)
    rows = rt.scope_reads(ctx, rt.all_rows("PaymentRecord"), company_field=None)
    for field in ("alarm_site_id", "status", "method"):
        value = q(field)
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    tendered_from = q_instant("tendered_from")
    tendered_to = q_instant("tendered_to")
    if tendered_from is not None:
        rows = [r for r in rows if r.get("tendered_on") is not None
                and r["tendered_on"] >= tendered_from]
    if tendered_to is not None:
        rows = [r for r in rows if r.get("tendered_on") is not None
                and r["tendered_on"] <= tendered_to]
    return listing(rows, rt.fields("PaymentRecord"))
