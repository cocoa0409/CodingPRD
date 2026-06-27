"""Invoice lifecycle: draft, finalize, void, payments, trust-sweep, write-off,
send-to-collections, plus operating-payment reversal."""

from datetime import timedelta

from flask import Blueprint, request

import db
import errors
from common import (get_json_body, stamp_create, touch, require_int,
                    require_datetime, require_enum, optional_int, paginate)
from clock import clock, parse_iso8601
from middleware import authenticate, require_role
from middleware import ROLE_PLATFORM_ADMIN, ROLE_BILLING_CLERK, ROLE_ATTORNEY
from response import object_response, array_response
import serializers
from services import (recompute_collection_status, recompute_client_ar,
                      advance_billing_after_payment, recompute_billing_after_unpay,
                      due_date_of, COLLECTIONS_GRACE_DAYS)

bp = Blueprint("invoices", __name__)

ALL_ROLES = {ROLE_PLATFORM_ADMIN, ROLE_BILLING_CLERK, ROLE_ATTORNEY}
CLERK_ADMIN = {ROLE_BILLING_CLERK, ROLE_PLATFORM_ADMIN}
PAYMENT_METHODS = {"CHECK", "ACH", "CARD"}


# ---------------- Invoice draft / fetch / list ----------------

@bp.route("/firm/invoices", methods=["POST"])
def create_invoice():
    _uid, role = authenticate()
    require_role(role, CLERK_ADMIN)
    body = get_json_body()
    matter_id = body.get("matter_id")
    if matter_id is None or not isinstance(matter_id, str):
        raise errors.invalid_request("Missing required field 'matter_id'.")
    issue_date = require_datetime(body, "issue_date")  # validate format
    net_terms = optional_int(body, "net_terms_days", default=30, minimum=0)

    matter = db.matters.get(matter_id)
    if matter is None:
        raise errors.not_found("Matter not found.")
    with db.LOCK:
        rec = {
            "matter_id": matter_id,
            "client_id": matter["client_id"],
            "issue_date": body["issue_date"],
            "net_terms_days": net_terms,
            "fees_subtotal_cents": 0,
            "expenses_subtotal_cents": 0,
            "written_off_cents": 0,
            "total_cents": 0,
            "amount_paid_cents": 0,
            "billing_status": "DRAFT",
            "collection_status": "CURRENT",
        }
        stamp_create(rec)
        db.invoices[rec["id"]] = rec
    return object_response(serializers.s_invoice(rec), status=201)


@bp.route("/firm/invoices/<iid>", methods=["GET"])
def get_invoice(iid):
    _uid, role = authenticate()
    require_role(role, ALL_ROLES)
    rec = db.invoices.get(iid)
    if rec is None:
        raise errors.not_found()
    with db.LOCK:
        # Reading an invoice recomputes its collection_status from the clock.
        if rec["billing_status"] in ("ISSUED", "PARTIALLY_PAID"):
            recompute_collection_status(rec)
    return object_response(serializers.s_invoice(rec))


@bp.route("/firm/invoices", methods=["GET"])
def list_invoices():
    _uid, role = authenticate()
    require_role(role, ALL_ROLES)
    # Re-age before listing so filters on collection_status are current.
    with db.LOCK:
        for inv in db.invoices.values():
            if inv["billing_status"] in ("ISSUED", "PARTIALLY_PAID"):
                recompute_collection_status(inv)
    items = list(db.invoices.values())
    for key in ("matter_id", "client_id", "billing_status", "collection_status"):
        val = request.args.get(key)
        if val is not None:
            items = [i for i in items if i.get(key) == val]
    page, limit, offset, total = paginate(items)
    return array_response([serializers.s_invoice(i) for i in page], limit, offset, total)


# ---------------- Finalize ----------------

@bp.route("/firm/invoices/<iid>/finalize", methods=["POST"])
def finalize_invoice(iid):
    _uid, role = authenticate()
    require_role(role, CLERK_ADMIN)
    invoice = db.invoices.get(iid)
    if invoice is None:
        raise errors.not_found()
    body = get_json_body()
    line_write_downs = body.get("line_write_downs")
    line_total = _sum_line_write_downs(line_write_downs)

    matter = db.matters.get(invoice["matter_id"])
    if matter is None:
        raise errors.not_found("Matter not found.")

    # State (priority 5): invoice DRAFT and matter OPEN.
    if invoice["billing_status"] != "DRAFT":
        raise errors.invalid_state("Only a DRAFT invoice may be finalized.")
    if matter["status"] != "OPEN":
        raise errors.invalid_state("Matter must be OPEN to finalize an invoice.")

    with db.LOCK:
        # Attachment set: CAPTURED, invoice_id null, same matter; created_at ASC.
        attached_te = [t for t in db.time_entries.values()
                       if t["matter_id"] == invoice["matter_id"]
                       and t["status"] == "CAPTURED" and t["invoice_id"] is None]
        attached_ee = [e for e in db.expense_entries.values()
                       if e["matter_id"] == invoice["matter_id"]
                       and e["status"] == "CAPTURED" and e["invoice_id"] is None]
        attached_te.sort(key=lambda t: t["_seq"])
        attached_ee.sort(key=lambda e: e["_seq"])

        fees_subtotal = sum(t["billable_amount_cents"] for t in attached_te)
        fees_subtotal -= line_total
        expenses_subtotal = sum(e["amount_cents"] for e in attached_ee)
        written_off = line_total
        total = fees_subtotal + expenses_subtotal

        if not (attached_te or attached_ee) or total <= 0:
            raise errors.invalid_state(
                "Finalize requires at least one captured entry yielding a positive total.")

        # Pin amounts.
        invoice["fees_subtotal_cents"] = fees_subtotal
        invoice["expenses_subtotal_cents"] = expenses_subtotal
        invoice["written_off_cents"] = written_off
        invoice["total_cents"] = total

        # Cascade entries -> INVOICED.
        for t in attached_te:
            t["status"] = "INVOICED"
            t["invoice_id"] = invoice["id"]
            touch(t)
        for e in attached_ee:
            e["status"] = "INVOICED"
            e["invoice_id"] = invoice["id"]
            touch(e)

        # Cascade matter WIP down.
        matter["wip_fees_cents"] -= sum(t["billable_amount_cents"] for t in attached_te)
        matter["wip_expenses_cents"] -= sum(e["amount_cents"] for e in attached_ee)
        touch(matter)

        # Issue.
        invoice["billing_status"] = "ISSUED"
        invoice["collection_status"] = "CURRENT"
        touch(invoice)

        # Re-age the collection dimension immediately against the clock.
        recompute_collection_status(invoice)

        # Cascade up to client A/R.
        client = db.clients.get(invoice["client_id"])
        if client is not None:
            recompute_client_ar(client)
            touch(client)
    return object_response(serializers.s_invoice(invoice))


def _sum_line_write_downs(line_write_downs):
    if line_write_downs is None:
        return 0
    if not isinstance(line_write_downs, list):
        raise errors.invalid_request("line_write_downs must be a list.")
    total = 0
    for wd in line_write_downs:
        if not isinstance(wd, dict) or "amount_cents" not in wd:
            raise errors.invalid_request("Each line write-down needs amount_cents.")
        amt = wd["amount_cents"]
        if isinstance(amt, bool) or not isinstance(amt, int) or amt <= 0:
            raise errors.invalid_request("line write-down amount_cents must be a positive integer.")
        total += amt
    return total


# ---------------- Void ----------------

@bp.route("/firm/invoices/<iid>/void", methods=["POST"])
def void_invoice(iid):
    _uid, role = authenticate()
    require_role(role, CLERK_ADMIN)
    invoice = db.invoices.get(iid)
    if invoice is None:
        raise errors.not_found()
    if invoice["billing_status"] != "DRAFT":
        raise errors.invalid_state("Only a DRAFT invoice may be voided.")
    with db.LOCK:
        # Detach attached entries (stay CAPTURED, clear invoice_id).
        for t in db.time_entries.values():
            if t["invoice_id"] == invoice["id"]:
                t["invoice_id"] = None
                touch(t)
        for e in db.expense_entries.values():
            if e["invoice_id"] == invoice["id"]:
                e["invoice_id"] = None
                touch(e)
        invoice["billing_status"] = "VOID"
        invoice["collection_status"] = "SETTLED"
        touch(invoice)
    return object_response(serializers.s_invoice(invoice))


# ---------------- Operating payments ----------------

@bp.route("/firm/invoices/<iid>/payments", methods=["POST"])
def apply_payment(iid):
    _uid, role = authenticate()
    require_role(role, CLERK_ADMIN)
    invoice = db.invoices.get(iid)
    if invoice is None:
        raise errors.not_found()
    body = get_json_body()
    amount = require_int(body, "amount_cents", positive=True)
    method = require_enum(body, "method", PAYMENT_METHODS)

    # State: invoice must be ISSUED/PARTIALLY_PAID.
    if invoice["billing_status"] not in ("ISSUED", "PARTIALLY_PAID"):
        raise errors.invalid_state("Payments may only apply to an issued invoice.")

    with db.LOCK:
        remaining = invoice["total_cents"] - invoice["amount_paid_cents"] - invoice["written_off_cents"]
        if amount > remaining:
            raise errors.overpayment()
        rec = {
            "invoice_id": iid,
            "amount_cents": amount,
            "method": method,
            "status": "APPLIED",
        }
        stamp_create(rec)
        db.payments[rec["id"]] = rec
        invoice["amount_paid_cents"] += amount
        advance_billing_after_payment(invoice)
        touch(invoice)
        client = db.clients.get(invoice["client_id"])
        if client is not None:
            recompute_client_ar(client)
            touch(client)
    return object_response(serializers.s_payment(rec), status=201)


@bp.route("/firm/invoices/<iid>/payments", methods=["GET"])
def list_invoice_payments(iid):
    _uid, role = authenticate()
    require_role(role, ALL_ROLES)
    if db.invoices.get(iid) is None:
        raise errors.not_found()
    items = [p for p in db.payments.values() if p["invoice_id"] == iid]
    page, limit, offset, total = paginate(items)
    return array_response([serializers.s_payment(p) for p in page], limit, offset, total)


# ---------------- Trust sweep ----------------

@bp.route("/firm/invoices/<iid>/trust-sweep", methods=["POST"])
def trust_sweep(iid):
    uid, role = authenticate()
    require_role(role, {ROLE_ATTORNEY, ROLE_PLATFORM_ADMIN})
    invoice = db.invoices.get(iid)
    if invoice is None:
        raise errors.not_found()
    body = get_json_body()
    amount = require_int(body, "amount_cents", positive=True)
    ledger_id = body.get("client_trust_ledger_id")
    if ledger_id is None or not isinstance(ledger_id, str):
        raise errors.invalid_request("Missing required field 'client_trust_ledger_id'.")
    initiated_by = body.get("initiated_by_user_id")
    if initiated_by is None or not isinstance(initiated_by, str):
        raise errors.invalid_request("Missing required field 'initiated_by_user_id'.")
    expected_version = require_int(body, "expected_invoice_version")

    # Existence (priority 3): ledger.
    ledger = db.client_trust_ledgers.get(ledger_id)
    if ledger is None:
        raise errors.not_found("Client trust ledger not found.")

    # State (priority 5): invoice ISSUED/PARTIALLY_PAID.
    if invoice["billing_status"] not in ("ISSUED", "PARTIALLY_PAID"):
        raise errors.invalid_state("Trust sweep requires an issued invoice.")

    # OCC (priority 6).
    if expected_version != invoice["version"]:
        raise errors.stale_invoice_version()

    # SoD (priority 7): approver X-User-ID must differ from initiator.
    if uid == initiated_by:
        raise errors.sod_same_actor()

    with db.LOCK:
        # No-overdraw (priority 9).
        if ledger["balance_cents"] - amount < 0:
            raise errors.trust_overdraw()
        # Ledger-belongs-to-client (priority 10).
        if ledger["client_id"] != invoice["client_id"]:
            raise errors.ledger_account_mismatch()
        # Overpayment (priority 13).
        remaining = invoice["total_cents"] - invoice["amount_paid_cents"] - invoice["written_off_cents"]
        if amount > remaining:
            raise errors.overpayment()

        # Record the SWEEP_TO_OPERATING transaction (PENDING).
        tx = {
            "client_trust_ledger_id": ledger_id,
            "kind": "SWEEP_TO_OPERATING",
            "amount_cents": amount,
            "status": "PENDING",
            "invoice_id": iid,
            "initiated_by_user_id": initiated_by,
            "approved_by_user_id": uid,
        }
        from clock import server_now_iso
        tx["id"] = db.new_id()
        tx["created_at"] = server_now_iso()
        tx["_seq"] = db.next_seq()
        db.trust_transactions[tx["id"]] = tx

        # Book + client ledger move now (bank lags until confirm).
        ledger["balance_cents"] -= amount
        touch(ledger)
        account = db.trust_accounts.get(ledger["trust_account_id"])
        if account is not None:
            account["book_balance_cents"] -= amount
            touch(account)

        # Apply against the invoice.
        invoice["amount_paid_cents"] += amount
        advance_billing_after_payment(invoice)
        touch(invoice)

        # Cascade up to client A/R.
        client = db.clients.get(invoice["client_id"])
        if client is not None:
            recompute_client_ar(client)
            touch(client)
        # Retainer replenishment flag is informational; no field to set per PRD.
    return object_response(serializers.s_trust_transaction(tx), status=201)


# ---------------- Write-off ----------------

@bp.route("/firm/invoices/<iid>/write-off", methods=["POST"])
def write_off_invoice(iid):
    _uid, role = authenticate()
    require_role(role, {ROLE_ATTORNEY})
    invoice = db.invoices.get(iid)
    if invoice is None:
        raise errors.not_found()
    body = get_json_body()
    amount = require_int(body, "amount_cents", positive=True)

    if invoice["billing_status"] not in ("ISSUED", "PARTIALLY_PAID"):
        raise errors.invalid_state("Only an issued invoice may be written off.")

    with db.LOCK:
        remaining = invoice["total_cents"] - invoice["amount_paid_cents"]
        if amount != remaining:
            raise errors.partial_writeoff()
        invoice["written_off_cents"] += remaining
        invoice["billing_status"] = "WRITTEN_OFF"
        invoice["collection_status"] = "SETTLED"
        touch(invoice)
        client = db.clients.get(invoice["client_id"])
        if client is not None:
            recompute_client_ar(client)
            touch(client)
    return object_response(serializers.s_invoice(invoice))


# ---------------- Send to collections ----------------

@bp.route("/firm/invoices/<iid>/send-to-collections", methods=["POST"])
def send_to_collections(iid):
    _uid, role = authenticate()
    require_role(role, CLERK_ADMIN)
    invoice = db.invoices.get(iid)
    if invoice is None:
        raise errors.not_found()
    if invoice["billing_status"] not in ("ISSUED", "PARTIALLY_PAID"):
        raise errors.invalid_state("Only an issued invoice may be sent to collections.")
    with db.LOCK:
        # Re-age first.
        recompute_collection_status(invoice)
        if invoice["collection_status"] != "OVERDUE":
            raise errors.invalid_state("Invoice must be OVERDUE to send to collections.")
        # Grace must have fully elapsed.
        grace_end = due_date_of(invoice) + timedelta(days=COLLECTIONS_GRACE_DAYS)
        if not (clock.now() > grace_end):
            raise errors.collections_too_early()
        invoice["collection_status"] = "IN_COLLECTIONS"
        touch(invoice)
    return object_response(serializers.s_invoice(invoice))


# ---------------- Payment fetch / reverse ----------------

@bp.route("/firm/payments/<pid>", methods=["GET"])
def get_payment(pid):
    _uid, role = authenticate()
    require_role(role, ALL_ROLES)
    rec = db.payments.get(pid)
    if rec is None:
        raise errors.not_found()
    return object_response(serializers.s_payment(rec))


@bp.route("/firm/payments/<pid>/reverse", methods=["POST"])
def reverse_payment(pid):
    _uid, role = authenticate()
    require_role(role, CLERK_ADMIN)
    payment = db.payments.get(pid)
    if payment is None:
        raise errors.not_found()
    invoice = db.invoices.get(payment["invoice_id"])
    if invoice is None:
        raise errors.not_found("Invoice not found.")
    if payment["status"] != "APPLIED":
        raise errors.invalid_state("Only an APPLIED payment may be reversed.")
    if invoice["billing_status"] == "WRITTEN_OFF":
        raise errors.invalid_state("Cannot reverse a payment on a written-off invoice.")
    with db.LOCK:
        payment["status"] = "REVERSED"
        touch(payment)
        invoice["amount_paid_cents"] -= payment["amount_cents"]
        recompute_billing_after_unpay(invoice)
        touch(invoice)
        client = db.clients.get(invoice["client_id"])
        if client is not None:
            recompute_client_ar(client)
            touch(client)
    return object_response(serializers.s_payment(payment))
