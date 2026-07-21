"""Invoice and InvoiceLine endpoints, including reconcile / resolve-dispute / pay."""

from flask import Blueprint, request

import store
import logic
from store import touch
from common import get_or_404, single, list_result, filter_by, as_str, exists_or_404
from auth import authenticate
from validate import get_body, req_str, req_int
from errors import bad_request, invalid_state

bp = Blueprint("invoices", __name__)

READERS = {"TravelManager", "FinanceOfficer"}


@bp.post("/tmc/invoices")
def create_invoice():
    authenticate({"FinanceOfficer"})
    body = get_body()

    # --- Priority 3: existence (vendor, then each line's booking left-to-right) ---
    exists_or_404(store.vendors, body.get("vendor_id"))
    lines_in = body.get("lines")
    if isinstance(lines_in, list):
        for ln in lines_in:
            if isinstance(ln, dict):
                exists_or_404(store.bookings, ln.get("booking_id"))

    # --- Priority 4: body validation ---
    vendor_id = req_str(body, "vendor_id")
    billing_period = req_str(body, "billing_period")
    invoiced_total = req_int(body, "invoiced_total_cents", min_value=0)
    if not isinstance(lines_in, list):
        raise bad_request("lines must be a list")
    parsed = []
    for ln in lines_in:
        if not isinstance(ln, dict):
            raise bad_request("Each line must be an object")
        booking_id = ln.get("booking_id")
        if booking_id is not None and (not isinstance(booking_id, str) or booking_id == ""):
            raise bad_request("Invalid booking_id on line")
        billed = ln.get("billed_amount_cents")
        if isinstance(billed, bool) or not isinstance(billed, int) or billed < 0:
            raise bad_request("Invalid billed_amount_cents on line")
        parsed.append((booking_id, billed))

    invoice = {
        "vendor_id": vendor_id,
        "billing_period": billing_period,
        "invoiced_total_cents": invoiced_total,
        "reconciled_total_cents": 0,
        "variance_cents": 0,
        "status": "RECEIVED",
    }
    store.stamp_new(invoice)
    store.invoices[invoice["id"]] = invoice

    for booking_id, billed in parsed:
        line = {
            "invoice_id": invoice["id"],
            "booking_id": booking_id,
            "billed_amount_cents": billed,
            "matched_amount_cents": 0,
            "match_status": "UNMATCHED",
        }
        store.stamp_new(line)
        store.invoice_lines[line["id"]] = line

    return single(invoice, 201)


@bp.get("/tmc/invoices/<iid>")
def get_invoice(iid):
    authenticate(READERS)
    return single(get_or_404(store.invoices, iid))


@bp.get("/tmc/invoices")
def list_invoices():
    authenticate(READERS)
    recs = filter_by(store.invoices.values(), request.args,
                     {"vendor_id": as_str, "status": as_str})
    return list_result(recs)


@bp.post("/tmc/invoices/<iid>/reconcile")
def reconcile(iid):
    authenticate({"FinanceOfficer"})
    invoice = get_or_404(store.invoices, iid)
    if invoice["status"] != "RECEIVED":
        raise invalid_state("Invoice is not RECEIVED")
    logic.reconcile_invoice(invoice)
    invoice["status"] = "RECONCILED" if invoice["variance_cents"] == 0 else "DISPUTED"
    touch(invoice)
    return single(invoice)


@bp.post("/tmc/invoices/<iid>/resolve-dispute")
def resolve_dispute(iid):
    authenticate({"FinanceOfficer"})
    invoice = get_or_404(store.invoices, iid)
    body = get_body()
    adjusted = req_int(body, "adjusted_invoiced_total_cents", min_value=0)
    if invoice["status"] != "DISPUTED":
        raise invalid_state("Invoice is not DISPUTED")
    new_variance = adjusted - invoice["reconciled_total_cents"]
    if new_variance != 0:
        raise invalid_state("Adjusted total does not bring variance to zero")
    invoice["invoiced_total_cents"] = adjusted
    invoice["variance_cents"] = 0
    invoice["status"] = "RECONCILED"
    touch(invoice)
    return single(invoice)


@bp.post("/tmc/invoices/<iid>/pay")
def pay_invoice(iid):
    authenticate({"FinanceOfficer"})
    invoice = get_or_404(store.invoices, iid)
    if invoice["status"] != "RECONCILED":
        raise invalid_state("Invoice is not RECONCILED")
    invoice["status"] = "PAID"
    touch(invoice)
    return single(invoice)


@bp.get("/tmc/invoice-lines/<lid>")
def get_invoice_line(lid):
    authenticate(READERS)
    return single(get_or_404(store.invoice_lines, lid))


@bp.get("/tmc/invoice-lines")
def list_invoice_lines():
    authenticate(READERS)
    recs = filter_by(store.invoice_lines.values(), request.args,
                     {"invoice_id": as_str, "booking_id": as_str, "match_status": as_str})
    return list_result(recs)
