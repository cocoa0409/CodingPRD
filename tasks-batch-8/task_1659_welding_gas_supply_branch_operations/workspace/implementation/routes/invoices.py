"""Invoices (system-created receivables) and the monthly rental billing run."""
from flask import Blueprint

import db
from db import store, touch
from errors import ApiError
from middleware import require_roles, body
from response import ok, list_response, filter_param
from services import accrual, exposure

bp = Blueprint("invoices", __name__)


def get_invoice(iid):
    inv = store.invoices.get(iid)
    if inv is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Invoice not found")
    return inv


@bp.route("/invoices", methods=["GET"])
@require_roles("CounterRep", "BranchManager")
def list_invoices():
    rows = list(store.invoices.values())
    rows = filter_param(rows, "customer_id")
    rows = filter_param(rows, "order_id")
    rows = filter_param(rows, "status")
    return list_response(rows)


@bp.route("/invoices/<iid>", methods=["GET"])
@require_roles("CounterRep", "BranchManager")
def get_one_invoice(iid):
    return ok(get_invoice(iid))


@bp.route("/invoices/<iid>/void", methods=["POST"])
@require_roles("BranchManager")
def void_invoice(iid):
    inv = get_invoice(iid)
    # Only an untouched OPEN invoice is voidable (non-OPEN or paid_cents > 0
    # both surface ERR_INVOICE_NOT_VOIDABLE).
    if inv["status"] != "OPEN" or inv["paid_cents"] != 0:
        raise ApiError("ERR_INVOICE_NOT_VOIDABLE", 409,
                       "Only an OPEN invoice with no payments can be voided")
    inv["status"] = "VOID"
    touch(inv)
    # ORDER-sourced voids revert the order's payment dimension.
    if inv["source"] == "ORDER" and inv["order_id"]:
        order = store.orders.get(inv["order_id"])
        if order is not None and order["payment_status"] == "INVOICED":
            order["payment_status"] = "UNPAID"
            touch(order)
    # Balance drops out of exposure; may auto-release a CREDIT_HOLD.
    cust = store.customers.get(inv["customer_id"])
    if cust is not None:
        exposure.release_if_cleared(cust)
    return ok(inv)


@bp.route("/billing/run-rental-cycle", methods=["POST"])
@require_roles("BranchManager")
def run_rental_cycle():
    """Monthly billing checkpoint. Every ACTIVE agreement bills its complete-
    period (floor) amount at the clock; positive charges group into one
    RENTAL_CYCLE invoice per customer. SUSPENDED agreements are skipped."""
    run_date = db.clock_date()
    per_customer = {}
    order_of_customers = []
    for ag in sorted(store.rental_agreements.values(), key=lambda a: a.get("_seq", 0)):
        if ag["status"] != "ACTIVE":
            continue
        bill = max(0, accrual.value_floor(ag, run_date)
                   - ag["lifetime_billed_cents"] - ag["waived_cents"])
        if bill <= 0:
            continue
        ag["lifetime_billed_cents"] += bill
        ag["billed_through_date"] = run_date.isoformat()
        touch(ag)
        if ag["customer_id"] not in per_customer:
            per_customer[ag["customer_id"]] = 0
            order_of_customers.append(ag["customer_id"])
        per_customer[ag["customer_id"]] += bill
    invoice_ids = []
    for cust_id in order_of_customers:
        cust = store.customers[cust_id]
        inv = exposure.create_invoice(cust, "RENTAL_CYCLE", per_customer[cust_id],
                                      order_id=None)
        invoice_ids.append(inv["id"])
        # Invoice creation recomputes exposure and may auto-place CREDIT_HOLD.
        exposure.on_invoice_created(cust)
    return ok({
        "invoices_created": len(invoice_ids),
        "invoice_ids": invoice_ids,
        "total_billed_cents": sum(per_customer.values()),
    })
