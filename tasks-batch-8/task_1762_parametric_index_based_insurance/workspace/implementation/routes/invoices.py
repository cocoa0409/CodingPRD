"""PremiumInvoice endpoints (PRD §3.5)."""

from flask import Blueprint, request

import db
from errors import (
    err, ERR_INVALID_REQUEST, ERR_INVOICE_NOT_PAYABLE, ERR_OVERPAYMENT,
    ERR_INVOICE_NOT_FOUND,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from routes.common import (
    body, require_fields, pagination_params, paginate, sorted_by_created,
    get_program, get_invoice_in_program,
)
from services import domain

bp = Blueprint("invoices", __name__)


@bp.get("/programs/<programId>/invoices")
def list_invoices(programId):
    require_roles(*ALL_ROLES)
    domain.run_expiry_sweep()
    prog = get_program(programId)
    limit, offset = pagination_params()
    items = _invoices_for_program(prog["id"])
    items = _apply_invoice_filters(items)
    items = sorted_by_created(items)
    page, total = paginate(items, limit, offset)
    return success_list(domain.serialize_list(page), limit, offset, total)


def _invoices_for_program(program_id):
    out = []
    for inv in db.invoices.values():
        pol = db.policies.get(inv["policy_id"])
        if pol and pol["program_id"] == program_id:
            out.append(inv)
    return out


def _apply_invoice_filters(items):
    pid = request.args.get("policy_id")
    st = request.args.get("status")
    if pid is not None:
        items = [i for i in items if i["policy_id"] == pid]
    if st is not None:
        items = [i for i in items if i["status"] == st]
    return items


@bp.get("/programs/<programId>/invoices/<invoiceId>")
def get_invoice(programId, invoiceId):
    require_roles(*ALL_ROLES)
    domain.run_expiry_sweep()
    prog = get_program(programId)
    inv = get_invoice_in_program(prog, invoiceId)
    return success_object(domain.serialize(inv))


@bp.post("/programs/<programId>/invoices/<invoiceId>/payments")
def apply_payment(programId, invoiceId):
    require_roles("ServicingAgent")
    prog = get_program(programId)
    inv = get_invoice_in_program(prog, invoiceId)
    data = body()
    require_fields(data, ["amount_cents"])
    amount = data["amount_cents"]
    if not isinstance(amount, int) or amount <= 0:
        raise err(ERR_INVALID_REQUEST, 400, "amount_cents must be a positive integer")
    if inv["status"] not in ("ISSUED", "PARTIALLY_PAID"):
        raise err(ERR_INVOICE_NOT_PAYABLE, 409,
                  "Payment requires invoice ISSUED or PARTIALLY_PAID")
    if int(inv["amount_paid_cents"]) + amount > int(inv["invoice_amount_cents"]):
        raise err(ERR_OVERPAYMENT, 422, "Payment would exceed invoice_amount_cents")
    inv["amount_paid_cents"] = int(inv["amount_paid_cents"]) + amount
    inv["status"] = "PAID" if inv["amount_paid_cents"] == int(inv["invoice_amount_cents"]) else "PARTIALLY_PAID"
    domain.touch(inv)
    return success_object(domain.serialize(inv))


# --- Flat reads ---

@bp.get("/programs/invoices")
def list_invoices_flat():
    require_roles(*ALL_ROLES)
    domain.run_expiry_sweep()
    limit, offset = pagination_params()
    items = list(db.invoices.values())
    items = _apply_invoice_filters(items)
    items = sorted_by_created(items)
    page, total = paginate(items, limit, offset)
    return success_list(domain.serialize_list(page), limit, offset, total)


@bp.get("/programs/invoices/<invoiceId>")
def get_invoice_flat(invoiceId):
    require_roles(*ALL_ROLES)
    domain.run_expiry_sweep()
    inv = db.invoices.get(invoiceId)
    if not inv:
        raise err(ERR_INVOICE_NOT_FOUND, 404, "Invoice id does not exist")
    return success_object(domain.serialize(inv))
