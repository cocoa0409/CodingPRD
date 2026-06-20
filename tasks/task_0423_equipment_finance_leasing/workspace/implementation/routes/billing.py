"""Schedule lines, invoices, and payments — PRD §3.9, §4."""
from flask import Blueprint, request

import db
import errors
from middleware import get_user_context, require_roles, ALL_ROLES
from response import object_response, array_response
from services.common import (
    get_json_body, require_string, require_positive_int, serialize, paginate,
    sort_by_created,
)
from services import domain
from services import calculations as calc

bp = Blueprint("billing", __name__)


# --- ScheduleLine reads -------------------------------------------------------

@bp.get("/lessors/<lessor_id>/schedule-lines/<sl_id>")
def get_schedule_line(lessor_id, sl_id):
    user_id, role = get_user_context()
    require_roles(role, ALL_ROLES)
    with db.LOCK:
        domain.get_lessor_or_404(lessor_id)
        rec = domain.get_schedule_line(lessor_id, sl_id)
        return object_response(serialize(rec), 200)


@bp.get("/lessors/<lessor_id>/leases/<lease_id>/schedule-lines")
def list_schedule_lines(lessor_id, lease_id):
    user_id, role = get_user_context()
    require_roles(role, ALL_ROLES)
    with db.LOCK:
        domain.get_lessor_or_404(lessor_id)
        domain.get_lease(lessor_id, lease_id)
        items = domain.schedule_lines_for_lease(lease_id)
        status = request.args.get("status")
        if status is not None and status != "":
            items = [s for s in items if s["status"] == status]
        items = sort_by_created(items)
        page, limit, offset, total = paginate(items)
        return array_response([serialize(r) for r in page], limit, offset, total, 200)


@bp.get("/lessors/<lessor_id>/schedule-lines/<sl_id>/invoices")
def list_invoices_for_schedule_line(lessor_id, sl_id):
    user_id, role = get_user_context()
    require_roles(role, ALL_ROLES)
    with db.LOCK:
        domain.get_lessor_or_404(lessor_id)
        domain.get_schedule_line(lessor_id, sl_id)
        items = [i for i in db.invoices.values() if i["schedule_line_id"] == sl_id]
        items = sort_by_created(items)
        page, limit, offset, total = paginate(items)
        return array_response([serialize(r) for r in page], limit, offset, total, 200)


# --- Invoice ------------------------------------------------------------------

@bp.post("/lessors/<lessor_id>/leases/<lease_id>/invoices")
def create_invoice(lessor_id, lease_id):
    user_id, role = get_user_context()
    require_roles(role, ["Servicer"])
    with db.LOCK:
        lessor = domain.get_lessor_or_404(lessor_id)
        lease = domain.get_lease(lessor_id, lease_id)
        body = get_json_body()
        sl_id = require_string(body, "schedule_line_id")
        sl = db.schedule_lines.get(sl_id)
        # The schedule line must exist and belong to this lease.
        if sl is None or sl["lease_id"] != lease_id or sl["lessor_id"] != lessor_id:
            raise errors.invalid_request("schedule_line_id does not reference a line on this lease")
        # Bill a SCHEDULED installment -> move it to INVOICED.
        if sl["status"] != "SCHEDULED":
            raise errors.invalid_state("Schedule line is not SCHEDULED")
        base_rent = sl["base_rent_cents"]
        sales_tax = calc.invoice_sales_tax(base_rent, lessor["sales_tax_rate_bps"])
        rec = db.init_record({
            "lessor_id": lessor_id,
            "lease_id": lease_id,
            "schedule_line_id": sl_id,
            "base_rent_cents": base_rent,
            "sales_tax_cents": sales_tax,
            "total_due_cents": base_rent + sales_tax,
            "amount_paid_cents": 0,
            "status": "OPEN",
        })
        db.invoices[rec["id"]] = rec
        sl["status"] = "INVOICED"
        db.touch(sl)
        return object_response(serialize(rec), 201)


@bp.get("/lessors/<lessor_id>/invoices/<inv_id>")
def get_invoice(lessor_id, inv_id):
    user_id, role = get_user_context()
    require_roles(role, ALL_ROLES)
    with db.LOCK:
        domain.get_lessor_or_404(lessor_id)
        rec = domain.get_invoice(lessor_id, inv_id)
        return object_response(serialize(rec), 200)


@bp.get("/lessors/<lessor_id>/leases/<lease_id>/invoices")
def list_invoices_for_lease(lessor_id, lease_id):
    user_id, role = get_user_context()
    require_roles(role, ALL_ROLES)
    with db.LOCK:
        domain.get_lessor_or_404(lessor_id)
        domain.get_lease(lessor_id, lease_id)
        items = domain.invoices_for_lease(lease_id)
        status = request.args.get("status")
        if status is not None and status != "":
            items = [i for i in items if i["status"] == status]
        items = sort_by_created(items)
        page, limit, offset, total = paginate(items)
        return array_response([serialize(r) for r in page], limit, offset, total, 200)


@bp.post("/lessors/<lessor_id>/invoices/<inv_id>/void")
def void_invoice(lessor_id, inv_id):
    user_id, role = get_user_context()
    require_roles(role, ["Servicer"])
    with db.LOCK:
        domain.get_lessor_or_404(lessor_id)
        rec = domain.get_invoice(lessor_id, inv_id)
        if rec["status"] != "OPEN":
            raise errors.invalid_state("Invoice is not OPEN")
        if rec["amount_paid_cents"] != 0:
            raise errors.conflict(errors.ERR_INVOICE_HAS_PAYMENTS,
                                  "invoice has cleared payments")
        rec["status"] = "VOID"
        db.touch(rec)
        # Cascade: linked schedule line reverts to SCHEDULED.
        sl = db.schedule_lines.get(rec["schedule_line_id"])
        if sl is not None:
            sl["status"] = "SCHEDULED"
            db.touch(sl)
        return object_response(serialize(rec), 200)


# --- Payment ------------------------------------------------------------------

@bp.post("/lessors/<lessor_id>/invoices/<inv_id>/payments")
def create_payment(lessor_id, inv_id):
    user_id, role = get_user_context()
    require_roles(role, ["Servicer"])
    with db.LOCK:
        domain.get_lessor_or_404(lessor_id)
        inv = domain.get_invoice(lessor_id, inv_id)
        body = get_json_body()
        amount_cents = require_positive_int(body, "amount_cents")
        # Invoice must be OPEN to accept a payment.
        if inv["status"] != "OPEN":
            raise errors.invalid_state("Invoice is not OPEN")
        outstanding = inv["total_due_cents"] - inv["amount_paid_cents"]
        if amount_cents > outstanding:
            raise errors.conflict(errors.ERR_PAYMENT_EXCEEDS_DUE,
                                  "payment exceeds outstanding balance")
        rec = db.init_record({
            "lessor_id": lessor_id,
            "invoice_id": inv_id,
            "lease_id": inv["lease_id"],
            "amount_cents": amount_cents,
            "status": "CLEARED",
        })
        db.payments[rec["id"]] = rec
        inv["amount_paid_cents"] += amount_cents
        db.touch(inv)
        # Auto PAID + schedule cascade when covered.
        if inv["amount_paid_cents"] >= inv["total_due_cents"]:
            inv["status"] = "PAID"
            db.touch(inv)
            sl = db.schedule_lines.get(inv["schedule_line_id"])
            if sl is not None:
                sl["status"] = "PAID"
                db.touch(sl)
            lease = db.leases.get(inv["lease_id"])
            if lease is not None:
                _recompute_paid_installments(lease)
        return object_response(serialize(rec), 201)


@bp.get("/lessors/<lessor_id>/payments/<pay_id>")
def get_payment(lessor_id, pay_id):
    user_id, role = get_user_context()
    require_roles(role, ALL_ROLES)
    with db.LOCK:
        domain.get_lessor_or_404(lessor_id)
        rec = domain.get_payment(lessor_id, pay_id)
        return object_response(serialize(rec), 200)


@bp.get("/lessors/<lessor_id>/invoices/<inv_id>/payments")
def list_payments_for_invoice(lessor_id, inv_id):
    user_id, role = get_user_context()
    require_roles(role, ALL_ROLES)
    with db.LOCK:
        domain.get_lessor_or_404(lessor_id)
        domain.get_invoice(lessor_id, inv_id)
        items = [p for p in db.payments.values() if p["invoice_id"] == inv_id]
        items = sort_by_created(items)
        page, limit, offset, total = paginate(items)
        return array_response([serialize(r) for r in page], limit, offset, total, 200)


@bp.get("/lessors/<lessor_id>/leases/<lease_id>/payments")
def list_payments_for_lease(lessor_id, lease_id):
    user_id, role = get_user_context()
    require_roles(role, ALL_ROLES)
    with db.LOCK:
        domain.get_lessor_or_404(lessor_id)
        domain.get_lease(lessor_id, lease_id)
        items = [p for p in db.payments.values() if p["lease_id"] == lease_id]
        items = sort_by_created(items)
        page, limit, offset, total = paginate(items)
        return array_response([serialize(r) for r in page], limit, offset, total, 200)


def _recompute_paid_installments(lease):
    count = sum(
        1 for s in domain.schedule_lines_for_lease(lease["id"])
        if s["status"] == "PAID"
    )
    if lease["paid_installment_count"] != count:
        lease["paid_installment_count"] = count
        db.touch(lease)
