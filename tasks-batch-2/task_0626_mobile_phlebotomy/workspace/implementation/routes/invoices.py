"""Invoices: get, issue, void (PRD 3.11, 3.10)."""
from flask import Blueprint

import common
import errors
import serializers
from db import db, touch
from middleware import require_roles
from services import billing

bp = Blueprint("invoices", __name__)


@bp.get("/invoices/<rid>")
@require_roles("OrderingProvider", "BillingAgent")
def get_invoice(rid):
    rec = common.find_invoice(rid)
    return common.object_response(serializers.invoice(rec))


@bp.post("/invoices/<rid>/issue")
@require_roles("BillingAgent")
def issue_invoice(rid):
    inv = common.find_invoice(rid)

    # Priority 7: state legality.
    if inv["status"] != "DRAFT":
        errors.fail(errors.ERR_INVOICE_NOT_ISSUABLE, "Invoice is not DRAFT.")
    order = db.lab_orders.get(inv["lab_order_id"])
    if order is None or order["status"] != "RESULTED":
        errors.fail(errors.ERR_ORDER_NOT_RESULTED, "Owning order is not RESULTED.")

    # Recompute fees via the order's active billing variant (chronological final).
    panel = common.find_panel_by_code(order["panel_code"])
    partner = db.lab_partners.get(order["lab_partner_id"])
    fee, convenience, waiver, total = billing.compute_billing(
        order["billing_mode"], panel, partner, order["priority"], order["redraw_count"]
    )
    inv["lab_fee_cents"] = fee
    inv["convenience_fee_cents"] = convenience
    inv["redraw_waiver_cents"] = waiver
    inv["total_cents"] = total
    inv["status"] = "ISSUED"
    touch(inv)

    return common.object_response(serializers.invoice(inv))


@bp.post("/invoices/<rid>/void")
@require_roles("BillingAgent")
def void_invoice(rid):
    inv = common.find_invoice(rid)
    if inv["status"] != "DRAFT":
        errors.fail(errors.ERR_INVOICE_NOT_VOIDABLE, "Invoice is not DRAFT.")
    inv["status"] = "VOID"
    touch(inv)
    return common.object_response(serializers.invoice(inv))
