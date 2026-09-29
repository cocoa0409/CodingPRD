"""Retailer invoices, their lines and off-posted-price validation (PRD section 3.8)."""

from flask import Blueprint

import services
from auth import ALL_ROLES, ROLE_FILING_AGENT, authenticate, require_scope
from envelope import object_response
from errors import raise_err
from serialize import out
from store import bump, db, new_record
from validators import Field, collection_response, must_find, validate_body

bp = Blueprint("invoices", __name__)

VALIDATION_STATUSES = ("DRAFT", "VALIDATED", "FLAGGED")
AUDIT_STATUSES = ("NOT_AUDITED", "UNDER_AUDIT", "ASSESSED")

LINE_COMPUTED_ZEROS = (
    "gross_cents",
    "quantity_discount_cents",
    "allowed_promotional_cents",
    "excess_promotional_cents",
    "allowed_depletion_cents",
    "excess_depletion_cents",
    "net_price_cents",
    "posted_gross_cents",
    "variance_cents",
    "finding_variance_cents",
)


# ---------------------------------------------------------------------------
# retailer invoices
# ---------------------------------------------------------------------------
@bp.post("/retailer-invoices")
def create_retailer_invoice():
    actor = authenticate([ROLE_FILING_AGENT])
    values = validate_body(
        [
            Field("wholesaler_id", "string"),
            Field("retailer_license_number", "string"),
            Field("invoice_date", "datetime"),
        ]
    )
    must_find("wholesaler", values["wholesaler_id"])
    require_scope(actor, values["wholesaler_id"])

    record = new_record(
        {
            "wholesaler_id": values["wholesaler_id"],
            "retailer_license_number": values["retailer_license_number"],
            "invoice_date": values["invoice_date"],
            "validation_status": "DRAFT",
            "audit_status": "NOT_AUDITED",
            "audit_id": None,
            "line_count": 0,
            "subtotal_cents": 0,
            "surcharge_cents": 0,
            "total_cents": 0,
            "total_allowance_cents": 0,
            "off_posted_line_count": 0,
            "total_variance_cents": 0,
        }
    )
    db.retailer_invoices[record["id"]] = record
    return object_response(out(record), 201)


@bp.post("/retailer-invoices/<record_id>/validate")
def validate_retailer_invoice(record_id):
    actor = authenticate([ROLE_FILING_AGENT])
    invoice = must_find("retailer_invoice", record_id)
    require_scope(actor, invoice["wholesaler_id"])

    # Priority 8 -- the regulator's custody freezes the document, and an empty
    # invoice has nothing to validate.
    if invoice["audit_status"] != "NOT_AUDITED":
        raise_err("ERR_INVALID_STATE")
    if not services.lines_of_invoice(invoice["id"]):
        raise_err("ERR_INVALID_STATE")

    # Priority 9 -- a suspended licensee may not invoice.
    wholesaler = db.wholesalers[invoice["wholesaler_id"]]
    if wholesaler["license_status"] != "ACTIVE":
        raise_err("ERR_LICENSE_NOT_ACTIVE")

    services.revalidate_invoice(invoice)
    return object_response(out(invoice))


@bp.get("/retailer-invoices/<record_id>")
def get_retailer_invoice(record_id):
    authenticate(ALL_ROLES)
    return object_response(out(must_find("retailer_invoice", record_id)))


@bp.get("/retailer-invoices")
def list_retailer_invoices():
    authenticate(ALL_ROLES)
    return collection_response(
        list(db.retailer_invoices.values()),
        {
            "wholesaler_id": None,
            "audit_id": None,
            "validation_status": VALIDATION_STATUSES,
            "audit_status": AUDIT_STATUSES,
        },
        out,
    )


# ---------------------------------------------------------------------------
# invoice lines
# ---------------------------------------------------------------------------
@bp.post("/invoice-lines")
def create_invoice_line():
    actor = authenticate([ROLE_FILING_AGENT])
    values = validate_body(
        [
            Field("invoice_id", "string"),
            Field("item_id", "string"),
            Field("cases_quantity", "int", required=False, default=0, minimum=0),
            Field("bottles_quantity", "int", required=False, default=0, minimum=0),
            Field("case_price_charged_cents", "int", minimum=0),
            Field("unit_price_charged_cents", "int", minimum=0),
            Field(
                "promotional_allowance_cents", "int", required=False, default=0, minimum=0
            ),
            Field(
                "depletion_allowance_cents", "int", required=False, default=0, minimum=0
            ),
        ]
    )
    invoice = must_find("retailer_invoice", values["invoice_id"])
    item = must_find("price_schedule_item", values["item_id"])
    require_scope(actor, invoice["wholesaler_id"])

    # Priority 8 -- lines may only be added while the regulator has no custody.
    if invoice["audit_status"] != "NOT_AUDITED":
        raise_err("ERR_INVALID_STATE")

    # Priority 19 -- a line with no quantity at all is degenerate.
    if values["cases_quantity"] == 0 and values["bottles_quantity"] == 0:
        raise_err("ERR_ZERO_QUANTITY_LINE")

    fields = {
        "invoice_id": invoice["id"],
        "item_id": item["id"],
        "cases_quantity": values["cases_quantity"],
        "bottles_quantity": values["bottles_quantity"],
        "case_price_charged_cents": values["case_price_charged_cents"],
        "unit_price_charged_cents": values["unit_price_charged_cents"],
        "promotional_allowance_cents": values["promotional_allowance_cents"],
        "depletion_allowance_cents": values["depletion_allowance_cents"],
    }
    for name in LINE_COMPUTED_ZEROS:
        fields[name] = 0
    fields["is_off_posted"] = False

    record = new_record(fields)
    db.invoice_lines[record["id"]] = record

    invoice["line_count"] += 1
    bump(invoice)
    return object_response(out(record), 201)


@bp.get("/invoice-lines/<record_id>")
def get_invoice_line(record_id):
    authenticate(ALL_ROLES)
    return object_response(out(must_find("invoice_line", record_id)))


@bp.get("/invoice-lines")
def list_invoice_lines():
    authenticate(ALL_ROLES)
    return collection_response(
        list(db.invoice_lines.values()),
        {"invoice_id": None, "item_id": None},
        out,
    )
