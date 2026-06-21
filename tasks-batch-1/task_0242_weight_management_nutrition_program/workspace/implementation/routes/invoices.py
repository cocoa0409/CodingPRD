"""Invoice endpoints + lifecycle (PRD 3.5)."""
from flask import Blueprint, request

from common import parse_pagination, sort_by_creation, touch
from db import db
from errors import (ERR_CANNOT_VOID_INITIAL_INVOICE, ERR_INVALID_STATE,
                    ERR_INVOICE_NOT_ISSUED, raise_error)
from lookups import get_enrollment, get_invoice, get_member
from middleware import require_roles
from response import paginated, success
from serializers import serialize
import services

bp = Blueprint("invoices", __name__)

ALL_READ = ("ProgramAdmin", "BillingAgent", "Member")


def _view(invoice):
    """Serialise an invoice with hsa_fsa_eligible_cents derived live from the
    enrollment's current approved+eligible determination (PRD 3.9)."""
    services.recompute_invoice_hsa_fsa(invoice)
    return serialize(invoice)


@bp.route("/wm/invoices", methods=["GET"])
@require_roles(*ALL_READ)
def list_invoices():
    limit, offset = parse_pagination()
    items = list(db.invoices.values())
    enrollment_id = request.args.get("enrollment_id")
    member_id = request.args.get("member_id")
    status = request.args.get("status")
    if enrollment_id is not None:
        items = [i for i in items if i["enrollment_id"] == enrollment_id]
    if member_id is not None:
        items = [i for i in items if i["member_id"] == member_id]
    if status is not None:
        items = [i for i in items if i["status"] == status]
    items = sort_by_creation(items)
    total = len(items)
    page = items[offset:offset + limit]
    return paginated([_view(i) for i in page], limit, offset, total)


@bp.route("/wm/invoices/<invoice_id>", methods=["GET"])
@require_roles(*ALL_READ)
def get_one_invoice(invoice_id):
    return success(_view(get_invoice(invoice_id)), 200)


@bp.route("/wm/invoices/<invoice_id>/pay", methods=["POST"])
@require_roles("BillingAgent")
def pay_invoice(invoice_id):
    invoice = get_invoice(invoice_id)
    if invoice["status"] != "ISSUED":
        raise_error(ERR_INVOICE_NOT_ISSUED, "Invoice must be ISSUED to pay")
    invoice["status"] = "PAID"
    touch(invoice)
    enrollment = get_enrollment(invoice["enrollment_id"])
    if enrollment["billing_status"] == "PAST_DUE":
        enrollment["billing_status"] = "CURRENT"
        touch(enrollment)
    return success(_view(invoice), 200)


@bp.route("/wm/invoices/<invoice_id>/mark-past-due", methods=["POST"])
@require_roles("BillingAgent")
def mark_past_due(invoice_id):
    invoice = get_invoice(invoice_id)
    enrollment = get_enrollment(invoice["enrollment_id"])
    # enrollment.billing_status must be CURRENT (priority 8 state)
    if enrollment["billing_status"] != "CURRENT":
        raise_error(ERR_INVALID_STATE, "billing_status must be CURRENT")
    if invoice["status"] != "ISSUED":
        raise_error(ERR_INVOICE_NOT_ISSUED, "Target invoice must be ISSUED")
    enrollment["billing_status"] = "PAST_DUE"
    touch(enrollment)
    return success(_view(invoice), 200)


@bp.route("/wm/invoices/<invoice_id>/void", methods=["POST"])
@require_roles("BillingAgent")
def void_invoice(invoice_id):
    invoice = get_invoice(invoice_id)
    if invoice["status"] != "ISSUED":
        raise_error(ERR_INVOICE_NOT_ISSUED, "Invoice must be ISSUED to void")
    if invoice["cycle_index"] <= 0:
        raise_error(ERR_CANNOT_VOID_INITIAL_INVOICE,
                    "Cycle-0 invoice cannot be voided")
    invoice["status"] = "VOID"
    touch(invoice)
    enrollment = get_enrollment(invoice["enrollment_id"])
    member = get_member(invoice["member_id"])
    member["account_balance_cents"] += invoice["subtotal_cents"]
    touch(member)
    enrollment["cycles_billed"] -= 1
    touch(enrollment)
    return success(_view(invoice), 200)
