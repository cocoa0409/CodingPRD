"""PremiumInvoice routes: list / post-payment / waive."""

from flask import Blueprint, request, g

from db import db, now_iso
from clock import clock
from errors import raise_error
from middleware import auth_required
from response import success_object, success_array
from services.pagination import parse_pagination, paginate
from services.serializers import serialize_premium_invoice
from services.enrollment_engine import (
    rollup_payment_status,
    maybe_update_coverage_status,
)


bp = Blueprint("invoices", __name__)


# ---- GET /enrollments/{id}/premium-invoices ----

@bp.get("/enrollments/<enrollment_id>/premium-invoices")
@auth_required(allowed_roles={"Applicant", "MarketplaceAdmin", "CustomerService"})
def list_invoices(enrollment_id):
    e = db.enrollments.get(enrollment_id)
    if e is None:
        raise_error("ERR_NOT_FOUND")
    if g.user_role == "Applicant":
        app = db.applications.get(e["application_id"])
        if not app or app["applicant_id"] != g.user_id:
            raise_error("ERR_NOT_APPLICATION_OWNER")

    items = [
        inv for inv in db.premium_invoices.values()
        if inv["enrollment_id"] == enrollment_id
    ]
    status_f = request.args.get("status")
    if status_f:
        items = [i for i in items if i["status"] == status_f]
    # Sort by (billing_month ASC, id ASC)
    items.sort(key=lambda x: (x["billing_month"], x["id"]))
    limit, offset = parse_pagination()
    page, meta = paginate(items, limit, offset)
    return success_array([serialize_premium_invoice(i) for i in page], meta)


# ---- POST /premium-invoices/{id}/post-payment ----

@bp.post("/premium-invoices/<invoice_id>/post-payment")
@auth_required(allowed_roles={"Applicant", "CustomerService"})
def post_payment(invoice_id):
    inv = db.premium_invoices.get(invoice_id)
    if inv is None:
        raise_error("ERR_NOT_FOUND")
    enrollment = db.enrollments.get(inv["enrollment_id"])
    if enrollment is None:
        raise_error("ERR_NOT_FOUND")
    # Applicant ownership
    if g.user_role == "Applicant":
        app = db.applications.get(enrollment["application_id"])
        if not app or app["applicant_id"] != g.user_id:
            raise_error("ERR_NOT_APPLICATION_OWNER")

    if inv["status"] != "ISSUED":
        raise_error("ERR_INVOICE_ALREADY_PAID")

    body = request.get_json(silent=True) or {}
    amount = body.get("amount_cents")
    if not isinstance(amount, int):
        raise_error("ERR_INVALID_STATE", "amount_cents must be int")
    if amount < inv["net_amount_cents"]:
        raise_error("ERR_PAYMENT_INSUFFICIENT")

    inv["status"] = "PAID"
    inv["paid_at"] = now_iso()

    # Update enrollment payment_status + maybe coverage_status
    rollup_payment_status(enrollment)
    maybe_update_coverage_status(enrollment)

    return success_object(serialize_premium_invoice(inv))


# ---- POST /premium-invoices/{id}/waive ----

@bp.post("/premium-invoices/<invoice_id>/waive")
@auth_required(allowed_roles={"CustomerService"})
def waive_invoice(invoice_id):
    inv = db.premium_invoices.get(invoice_id)
    if inv is None:
        raise_error("ERR_NOT_FOUND")
    enrollment = db.enrollments.get(inv["enrollment_id"])
    if enrollment is None:
        raise_error("ERR_NOT_FOUND")
    if inv["status"] != "ISSUED":
        raise_error("ERR_INVALID_STATE")

    body = request.get_json(silent=True) or {}
    # Hardship or zero-net required
    if inv["net_amount_cents"] != 0 and not body.get("reason"):
        raise_error("ERR_INVALID_STATE", "Waive requires zero-net invoice or documented hardship reason")

    inv["status"] = "WAIVED"
    inv["paid_at"] = now_iso()
    if body.get("reason") is not None:
        inv["waive_reason"] = body.get("reason")

    rollup_payment_status(enrollment)
    maybe_update_coverage_status(enrollment)
    return success_object(serialize_premium_invoice(inv))
