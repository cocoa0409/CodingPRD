"""Invoice endpoints: lifecycle actions and lists."""
from flask import Blueprint

import db
import errors
from auth import require_account_owner, require_roles
from clock import clock
from db import stores
from respond import success
from services.domain import (adjust_account_balance, get_or_404,
                             set_billing_status)
from validate import apply_filters, json_body, opt_str, paginate

bp = Blueprint("invoices", __name__)

LIVE_STATES = ("DRAFT", "ISSUED", "DISPUTED")


def _load_invoice(iid):
    return get_or_404("invoices", iid, "Invoice")


def _load_invoice_for_organizer(iid):
    invoice = _load_invoice(iid)
    require_account_owner(invoice["corporate_account_id"])
    return invoice


@bp.get("/chair-massage/invoices")
@require_roles("PlatformAdmin", "Organizer")
def list_invoices():
    items = db.all_sorted("invoices")
    items = apply_filters(items, {
        "status": (lambda e: e["status"], "str"),
        "corporate_account_id": (lambda e: e["corporate_account_id"], "str"),
        "booking_id": (lambda e: e["booking_id"], "str"),
    })
    page, meta = paginate(items)
    return success([db.public(e) for e in page], response_type="array", pagination=meta)


@bp.get("/chair-massage/invoices/<iid>")
@require_roles("PlatformAdmin", "Organizer")
def get_invoice(iid):
    invoice = _load_invoice_for_organizer(iid)
    return success(db.public(invoice))


@bp.post("/chair-massage/invoices/<iid>/issue")
@require_roles("PlatformAdmin")
def issue_invoice(iid):
    invoice = _load_invoice(iid)
    if invoice["status"] != "DRAFT":
        raise errors.invalid_state("Only a DRAFT invoice can be issued")
    booking = get_or_404("bookings", invoice["booking_id"], "Booking")
    if booking["status"] not in ("COMPLETED", "CANCELLED"):
        raise errors.invalid_state(
            "Issuance requires the booking to be COMPLETED or CANCELLED")
    account = get_or_404("corporate_accounts", invoice["corporate_account_id"],
                         "CorporateAccount")
    # Credit-limit guard precedes the live-invoice uniqueness guard.
    if (account["outstanding_balance_cents"] + invoice["total_cents"]
            > account["credit_limit_cents"]):
        raise errors.unprocessable(
            errors.ERR_CREDIT_LIMIT_EXCEEDED,
            "Issuing would push the account's outstanding balance above its credit limit")
    for other in stores["invoices"].values():
        if (other["id"] != iid and other["booking_id"] == invoice["booking_id"]
                and other["status"] in LIVE_STATES):
            raise errors.unprocessable(
                errors.ERR_LIVE_INVOICE_EXISTS,
                "Another DRAFT/ISSUED/DISPUTED invoice already exists for this booking")
    invoice["status"] = "ISSUED"
    invoice["issued_at"] = clock.iso()
    db.touch(invoice)
    adjust_account_balance(account, invoice["total_cents"], invoice["total_cents"])
    set_billing_status(booking, "INVOICED")
    return success(db.public(invoice))


@bp.post("/chair-massage/invoices/<iid>/record-payment")
@require_roles("PlatformAdmin")
def record_payment(iid):
    invoice = _load_invoice(iid)
    if invoice["status"] != "ISSUED":
        raise errors.invalid_state("Only an ISSUED invoice can be paid")
    booking = get_or_404("bookings", invoice["booking_id"], "Booking")
    account = get_or_404("corporate_accounts", invoice["corporate_account_id"],
                         "CorporateAccount")
    invoice["status"] = "PAID"
    db.touch(invoice)
    adjust_account_balance(account, -invoice["total_cents"])
    set_billing_status(booking, "PAID")
    return success(db.public(invoice))


@bp.post("/chair-massage/invoices/<iid>/dispute")
@require_roles("Organizer")
def dispute_invoice(iid):
    invoice = _load_invoice_for_organizer(iid)
    if invoice["status"] != "ISSUED":
        raise errors.invalid_state("Only an ISSUED invoice can be disputed")
    body = json_body()
    reason = opt_str(body, "dispute_reason")
    if not reason:
        raise errors.ApiError(errors.ERR_DISPUTE_REASON_REQUIRED, 400,
                              "dispute_reason must be non-empty")
    booking = get_or_404("bookings", invoice["booking_id"], "Booking")
    invoice["status"] = "DISPUTED"
    invoice["dispute_reason"] = reason
    db.touch(invoice)
    # Disputed invoices still count toward credit utilization: balance unchanged.
    set_billing_status(booking, "DISPUTED")
    return success(db.public(invoice))


@bp.post("/chair-massage/invoices/<iid>/resolve-dispute")
@require_roles("PlatformAdmin")
def resolve_dispute(iid):
    invoice = _load_invoice(iid)
    if invoice["status"] != "DISPUTED":
        raise errors.invalid_state("Only a DISPUTED invoice can be resolved")
    booking = get_or_404("bookings", invoice["booking_id"], "Booking")
    # Totals are NOT recomputed: resolution preserves the disputed numbers.
    invoice["status"] = "ISSUED"
    db.touch(invoice)
    set_billing_status(booking, "INVOICED")
    return success(db.public(invoice))


@bp.post("/chair-massage/invoices/<iid>/void")
@require_roles("PlatformAdmin")
def void_invoice(iid):
    invoice = _load_invoice(iid)
    if invoice["status"] not in ("DRAFT", "DISPUTED"):
        raise errors.invalid_state("Only a DRAFT or DISPUTED invoice can be voided")
    booking = get_or_404("bookings", invoice["booking_id"], "Booking")
    account = get_or_404("corporate_accounts", invoice["corporate_account_id"],
                         "CorporateAccount")
    origin = invoice["status"]
    invoice["status"] = "VOID"
    db.touch(invoice)
    if origin == "DISPUTED":
        adjust_account_balance(account, -invoice["total_cents"])
        set_billing_status(booking, "UNBILLED")
    # From DRAFT nothing was ever counted; billing_status stays UNBILLED.
    return success(db.public(invoice))
