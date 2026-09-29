"""Post-event commission settlement: issuance, cash, disputes (PRD §3.9)."""

from flask import Blueprint

import calc
import serializers as ser
import validators as V
from auth import authenticate
from envelope import created, ok, ok_list, paginate
from errors import fail
from store import STORE, base_record, touch

bp = Blueprint("invoices", __name__, url_prefix="/housing")

BASES = ("BUREAU_CONFIRMED", "HOTEL_REPORTED")
INVOICE_READ_ROLES = ["BureauCoordinator", "BureauController", "EventOrganizer", "HotelManager"]


def _block_of_invoice(invoice):
    return STORE.hotel_blocks.get(invoice["hotel_block_id"])


@bp.post("/hotel-blocks/<block_id>/commission-invoice")
def issue_invoice(block_id):
    authenticate(["BureauCoordinator"])
    body = V.json_body()
    basis = V.field_enum(body, "basis", BASES)

    block = V.get_block(block_id)

    bureau_room_nights, bureau_commission, hotel_commission, latest = calc.commission_figures(block)

    # step 29 — the hotel basis is meaningless without a pickup report.
    if basis == "HOTEL_REPORTED" and latest is None:
        fail("ERR_PICKUP_REPORT_REQUIRED", "the block has filed no pickup report")
    # step 30 — one invoice per block
    if calc.invoices_of_block(block["id"]):
        fail("ERR_INVOICE_ALREADY_EXISTS", "this block already has a commission invoice")

    if basis == "BUREAU_CONFIRMED":
        commission_due = bureau_commission
        billable_room_nights = bureau_room_nights
    else:
        commission_due = hotel_commission
        billable_room_nights = latest["reported_room_nights"]

    variance = None if hotel_commission is None else bureau_commission - hotel_commission

    record = base_record()
    record.update(
        {
            "hotel_block_id": block["id"],
            "basis": basis,
            "bureau_confirmed_commission_cents": bureau_commission,
            "hotel_reported_commission_cents": hotel_commission,
            "commission_due_cents": commission_due,
            "rebate_due_cents": block["rebate_per_room_night_cents"] * billable_room_nights,
            "billable_room_nights": billable_room_nights,
            "variance_cents": variance,
            "paid_cents": 0,
            "written_off_cents": 0,
            "status": "ISSUED",
        }
    )
    STORE.invoices[record["id"]] = record
    calc.recompute_event_of_block(block)
    return created(ser.invoice_out(record))


@bp.get("/commission-invoices/<invoice_id>")
def read_invoice(invoice_id):
    authenticate(INVOICE_READ_ROLES)
    invoice = V.get_invoice(invoice_id)
    return ok(ser.invoice_out(invoice))


@bp.get("/hotel-blocks/<block_id>/commission-invoices")
def list_block_invoices(block_id):
    authenticate(INVOICE_READ_ROLES)
    limit, offset = V.pagination_args()
    block = V.get_block(block_id)

    items = calc.invoices_of_block(block["id"])
    page, pagination = paginate(items, limit, offset)
    return ok_list([ser.invoice_out(i) for i in page], pagination)


@bp.post("/commission-invoices/<invoice_id>/payments")
def pay_invoice(invoice_id):
    principal = authenticate(["HotelManager"])
    body = V.json_body()
    amount_cents = V.field_int(body, "amount_cents", minimum=0)
    V.field_str(body, "reference", required=False, min_len=0)

    invoice = V.get_invoice(invoice_id)
    block = _block_of_invoice(invoice)

    # step 6 — only the owning property remits
    if block is None or block["hotel_id"] != principal.user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "the acting hotel does not own this block")

    # step 8 — own-state
    if invoice["status"] not in ("ISSUED", "PARTIALLY_PAID", "ADJUSTED"):
        fail("ERR_INVOICE_NOT_PAYABLE", "an invoice in %s takes no payment" % invoice["status"])
    outstanding = calc.invoice_outstanding(invoice)
    if invoice["status"] == "ADJUSTED" and amount_cents < outstanding:
        fail(
            "ERR_INVOICE_NOT_PAYABLE",
            "an ADJUSTED invoice is settled only by the full outstanding amount",
        )
    # step 22 — payment ceiling
    if amount_cents > outstanding:
        fail("ERR_PAYMENT_EXCEEDS_OUTSTANDING", "only %d cents remain outstanding" % outstanding)

    invoice["paid_cents"] += amount_cents
    invoice["status"] = "PAID" if amount_cents == outstanding else "PARTIALLY_PAID"
    touch(invoice)
    calc.recompute_event_of_block(block)
    return ok(ser.invoice_out(invoice))


@bp.post("/commission-invoices/<invoice_id>/payment-reversals")
def reverse_payment(invoice_id):
    authenticate(["BureauController"])
    body = V.json_body()
    amount_cents = V.field_int(body, "amount_cents", minimum=0)
    V.field_str(body, "reference", required=False, min_len=0)

    invoice = V.get_invoice(invoice_id)

    # step 8 — own-state
    if invoice["status"] not in ("PARTIALLY_PAID", "PAID"):
        fail("ERR_INVOICE_NOT_PAYABLE", "an invoice in %s has no cash to reverse" % invoice["status"])
    # step 23 — reversal ceiling
    if amount_cents > invoice["paid_cents"]:
        fail("ERR_REVERSAL_EXCEEDS_PAID", "only %d cents have been posted" % invoice["paid_cents"])

    full_reversal = amount_cents == invoice["paid_cents"]
    invoice["paid_cents"] -= amount_cents
    invoice["status"] = "ISSUED" if full_reversal else "PARTIALLY_PAID"
    touch(invoice)
    calc.recompute_event_of_block(_block_of_invoice(invoice))
    return ok(ser.invoice_out(invoice))


@bp.post("/commission-invoices/<invoice_id>/dispute")
def dispute_invoice(invoice_id):
    principal = authenticate(["HotelManager"])
    V.json_body()

    invoice = V.get_invoice(invoice_id)
    block = _block_of_invoice(invoice)

    # step 6
    if block is None or block["hotel_id"] != principal.user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "the acting hotel does not own this block")
    # step 8
    if invoice["status"] not in ("ISSUED", "PARTIALLY_PAID"):
        fail("ERR_INVOICE_NOT_PAYABLE", "an invoice in %s cannot be disputed" % invoice["status"])
    # step 31 — materiality
    variance = invoice["variance_cents"]
    tolerance = calc.commission_variance_tolerance(invoice)
    if variance is None or abs(variance) <= tolerance:
        fail("ERR_VARIANCE_WITHIN_TOLERANCE", "the reconciliation variance is within tolerance")

    invoice["status"] = "DISPUTED"
    touch(invoice)
    return ok(ser.invoice_out(invoice))


@bp.post("/commission-invoices/<invoice_id>/adjust")
def adjust_invoice(invoice_id):
    authenticate(["BureauController"])
    body = V.json_body()
    write_off_cents = V.field_int(body, "write_off_cents", minimum=0)

    invoice = V.get_invoice(invoice_id)

    # step 8
    if invoice["status"] != "DISPUTED":
        fail("ERR_INVOICE_NOT_PAYABLE", "only a DISPUTED invoice may be adjusted")
    # step 22
    outstanding = calc.invoice_outstanding(invoice)
    if write_off_cents > outstanding:
        fail("ERR_PAYMENT_EXCEEDS_OUTSTANDING", "only %d cents remain outstanding" % outstanding)

    invoice["written_off_cents"] += write_off_cents
    invoice["status"] = "ADJUSTED"
    touch(invoice)
    return ok(ser.invoice_out(invoice))
