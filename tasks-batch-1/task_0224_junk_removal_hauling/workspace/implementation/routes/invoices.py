"""Invoice routes: get, settle, dispute, resolve-dispute (parallel status dimensions)."""
from flask import Blueprint
import errors
from errors import err
from db import db
from middleware import authenticate, require_role
from response import success
import models
from services.recompute import recompute_customer_balance
from services import lookups as L

bp = Blueprint("invoices", __name__)


@bp.route("/invoices/<invoice_id>", methods=["GET"])
def get_invoice(invoice_id):
    auth = authenticate()
    require_role(auth, {"PlatformAdmin", "Billing", "Customer"})
    inv = L.get_invoice_or_404(invoice_id)
    if auth.role == "Customer" and inv["customer_id"] != auth.user_id:
        err(errors.ERR_FORBIDDEN_ROLE, "Customer may only read its own invoices")
    return success(models.ser_invoice(inv), 200)


@bp.route("/invoices/<invoice_id>/settle", methods=["POST"])
def settle_invoice(invoice_id):
    auth = authenticate()
    require_role(auth, {"Billing"})
    inv = L.get_invoice_or_404(invoice_id)
    # state (priority 5): billing_status must be ISSUED
    if inv["billing_status"] != "ISSUED":
        err(errors.ERR_INVOICE_NOT_ISSUED, "Settle requires the invoice to be ISSUED")
    # same-row dimension guard: not currently DISPUTED
    if inv["dispute_status"] == "DISPUTED":
        err(errors.ERR_INVOICE_DISPUTED, "Settle is blocked while the invoice is DISPUTED")
    # cross-entity guard (priority 6): linked job in the appropriate terminal state
    job = db.haul_jobs.get(inv["haul_job_id"])
    if inv["kind"] == "SERVICE":
        if job is None or job["status"] != "COMPLETED":
            err(errors.ERR_JOB_NOT_BILLABLE, "SERVICE invoice requires the job to be COMPLETED")
    else:  # CANCELLATION
        if job is None or job["status"] != "CANCELLED":
            err(errors.ERR_JOB_NOT_BILLABLE, "CANCELLATION invoice requires the job to be CANCELLED")

    inv["billing_status"] = "SETTLED"
    models.touch(inv)
    customer = db.customers.get(inv["customer_id"])
    if customer is not None:
        recompute_customer_balance(customer)
    return success(models.ser_invoice(inv), 200)


@bp.route("/invoices/<invoice_id>/dispute", methods=["POST"])
def dispute_invoice(invoice_id):
    auth = authenticate()
    require_role(auth, {"Customer"})
    inv = L.get_invoice_or_404(invoice_id)
    if inv["customer_id"] != auth.user_id:
        err(errors.ERR_FORBIDDEN_ROLE, "Customer may only dispute its own invoices")
    # state (priority 5): both billing ISSUED and dispute NONE required.
    # Order per scaffold: ERR_INVOICE_ALREADY_DISPUTED listed before ERR_INVOICE_NOT_ISSUED.
    if inv["dispute_status"] != "NONE":
        err(errors.ERR_INVOICE_ALREADY_DISPUTED, "Invoice is already disputed")
    if inv["billing_status"] != "ISSUED":
        err(errors.ERR_INVOICE_NOT_ISSUED, "Dispute requires the invoice to be ISSUED")
    inv["dispute_status"] = "DISPUTED"
    models.touch(inv)  # billing_status unchanged
    return success(models.ser_invoice(inv), 200)


@bp.route("/invoices/<invoice_id>/resolve-dispute", methods=["POST"])
def resolve_dispute(invoice_id):
    auth = authenticate()
    require_role(auth, {"Billing"})
    inv = L.get_invoice_or_404(invoice_id)
    if inv["dispute_status"] != "DISPUTED":
        err(errors.ERR_INVOICE_NOT_DISPUTED, "Resolve-dispute requires dispute_status DISPUTED")
    inv["dispute_status"] = "RESOLVED"
    models.touch(inv)  # billing_status unchanged
    return success(models.ser_invoice(inv), 200)
