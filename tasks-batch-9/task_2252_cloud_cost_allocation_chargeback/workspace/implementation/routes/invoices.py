"""Chargeback invoice issuance and settlement (PRD 3.6)."""
from flask import Blueprint

from db import add_hours, db, fmt_dt, now, touch
from errors import fail
from middleware import authorize
from routes.common import lookup, require_bu_owner, serve, serve_list
from services import derived
from services.calc import DISPUTE_WINDOW_HOURS
from validation import body, req_int, req_str

bp = Blueprint("chargeback_invoices", __name__)

READERS = ("FinOpsController", "FinOpsAnalyst", "PlatformAdmin", "BusinessUnitOwner")


@bp.route("/finops/chargeback-invoices", methods=["GET"])
@authorize(*READERS)
def list_invoices():
    for invoice in list(db.chargeback_invoices.values()):
        derived.invoice_sync(invoice, bump=False)
    return serve_list(
        db.chargeback_invoices.values(),
        {
            "allocation_run_id": "allocation_run_id",
            "business_unit_id": "business_unit_id",
            "settlement_status": "settlement_status",
            "dispute_status": "dispute_status",
        },
    )


@bp.route("/finops/chargeback-invoices/<invoice_id>", methods=["GET"])
@authorize(*READERS)
def get_invoice(invoice_id):
    invoice = lookup("chargeback_invoices", invoice_id)
    derived.invoice_sync(invoice, bump=False)
    return serve(invoice)


@bp.route("/finops/chargeback-invoices/<invoice_id>/issue", methods=["POST"])
@authorize("FinOpsController")
def issue_invoice(invoice_id):
    invoice = lookup("chargeback_invoices", invoice_id)
    if invoice["settlement_status"] != "UNBILLED":
        fail("ERR_INVOICE_STATE_INVALID", "Only an UNBILLED invoice may be issued.")

    run = db.allocation_runs.get(invoice["allocation_run_id"])
    if run is None or run["status"] != "PUBLISHED":
        fail("ERR_RUN_STATE_INVALID", "The issuing allocation run is not PUBLISHED.")

    bu = db.business_units.get(invoice["business_unit_id"])
    if bu is None or bu["status"] != "ACTIVE":
        fail("ERR_BU_SUSPENDED", "The billed business unit is not ACTIVE.")
    if not bu["chargeback_enabled"]:
        fail(
            "ERR_BU_NOT_CHARGEBACK_ENABLED",
            "The billed business unit is not chargeback enabled.",
        )

    issued = now()
    invoice["settlement_status"] = "ISSUED"
    invoice["issued_at"] = fmt_dt(issued)
    invoice["dispute_window_ends_at"] = fmt_dt(add_hours(issued, DISPUTE_WINDOW_HOURS))
    invoice["_issued_at_dt"] = issued
    invoice["_dispute_window_ends_at_dt"] = add_hours(issued, DISPUTE_WINDOW_HOURS)
    derived.invoice_sync(invoice, bump=False)
    touch(invoice)
    derived.bu_sync_id(bu["id"])
    return serve(invoice)


@bp.route("/finops/chargeback-invoices/<invoice_id>/settle", methods=["POST"])
@authorize("BusinessUnitOwner")
def settle_invoice(invoice_id):
    invoice = lookup("chargeback_invoices", invoice_id)
    require_bu_owner(invoice["business_unit_id"])
    data = body()
    payment = req_int(data, "payment_cents", minimum=0)

    if invoice["settlement_status"] not in ("ISSUED", "PARTIALLY_CREDITED"):
        fail(
            "ERR_INVOICE_STATE_INVALID",
            "Only an ISSUED or PARTIALLY_CREDITED invoice may be settled.",
        )
    if invoice["dispute_status"] == "DISPUTED":
        fail("ERR_INVOICE_STATE_INVALID", "A disputed invoice may not be settled.")

    outstanding = invoice["gross_amount_cents"] - invoice["credited_amount_cents"]
    if invoice["paid_amount_cents"] + payment != outstanding:
        fail(
            "ERR_OVERPAYMENT",
            "The payment must exactly clear the invoice's outstanding amount.",
        )

    invoice.setdefault("_payments", []).append(payment)
    invoice["settlement_status"] = "SETTLED"
    derived.invoice_sync(invoice, bump=False)
    touch(invoice)
    derived.bu_sync_id(invoice["business_unit_id"])
    return serve(invoice)


@bp.route("/finops/chargeback-invoices/<invoice_id>/write-off", methods=["POST"])
@authorize("FinOpsController")
def write_off_invoice(invoice_id):
    invoice = lookup("chargeback_invoices", invoice_id)
    data = body()
    memo = req_str(data, "memo")

    if invoice["settlement_status"] not in ("ISSUED", "PARTIALLY_CREDITED"):
        fail(
            "ERR_INVOICE_STATE_INVALID",
            "Only an ISSUED or PARTIALLY_CREDITED invoice may be written off.",
        )
    if invoice["dispute_status"] == "DISPUTED":
        fail("ERR_INVOICE_STATE_INVALID", "A disputed invoice may not be written off.")

    invoice["settlement_status"] = "WRITTEN_OFF"
    invoice["_write_off_memo"] = memo
    derived.invoice_sync(invoice, bump=False)
    touch(invoice)
    derived.bu_sync_id(invoice["business_unit_id"])
    return serve(invoice)
