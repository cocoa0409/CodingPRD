"""Payment allocations: read-only, the sole discovery channel for the waterfall."""

from flask import Blueprint

import rt
from core import authenticate, listing, ok, q
from store import store

bp = Blueprint("allocations", __name__)

READ_ROLES = ["ProgramAdministrator", "BillingClerk", "PermitClerk", "AlarmUser"]


def _site_of(allocation):
    invoice = store.penalty_invoices.get(allocation.get("penalty_invoice_id"))
    return (invoice or {}).get("alarm_site_id")


@bp.get("/payment-allocations/<allocation_id>")
def get_allocation(allocation_id):
    ctx = authenticate(READ_ROLES)
    allocation = rt.resolve("PaymentAllocation", allocation_id)
    rt.own_site(ctx, _site_of(allocation))
    return ok(allocation)


@bp.get("/payment-allocations")
def list_allocations():
    ctx = authenticate(READ_ROLES)
    rows = rt.all_rows("PaymentAllocation")
    if ctx.role == "AlarmUser":
        rows = [r for r in rows if _site_of(r) == ctx.user_id]
    for field in ("payment_record_id", "penalty_invoice_id", "status"):
        value = q(field)
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    return listing(rows, rt.fields("PaymentAllocation"))
