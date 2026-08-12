"""Invoice endpoints: payments with exact-balance boundary, void (PRD §3.7)."""
from flask import Blueprint, request

from calc import touch
from db import STORE
from errors import (
    ERR_ALREADY_TERMINAL,
    ERR_INVALID_STATE,
    ERR_INVOICE_HAS_PAYMENTS,
    ERR_NOT_FOUND,
    ERR_PAYMENT_EXCEEDS_BALANCE,
    raise_err,
)
from middleware import (
    authenticate,
    get_body,
    req_int,
    require_client_scope,
    require_role,
)
from response import paginate, success_object
from serializers import serialize, sorted_by_creation

bp = Blueprint("invoices", __name__)

ALL_ROLES = {"FirmAdmin", "Analyst", "LicensedBroker", "ComplianceManager", "ClientContact"}


def get_invoice_or_404(invoice_id):
    invoice = STORE["invoices"].get(invoice_id)
    if invoice is None:
        raise_err(ERR_NOT_FOUND, f"Invoice {invoice_id} not found")
    return invoice


@bp.route("/customs/invoices/<invoice_id>", methods=["GET"])
def get_invoice(invoice_id):
    user_id, role = authenticate()
    require_role(role, ALL_ROLES)
    invoice = get_invoice_or_404(invoice_id)
    require_client_scope(user_id, role, invoice["client_id"])
    return success_object(serialize(invoice))


@bp.route("/customs/invoices", methods=["GET"])
def list_invoices():
    user_id, role = authenticate()
    require_role(role, ALL_ROLES)
    items = sorted_by_creation(STORE["invoices"].values())
    if role == "ClientContact":
        items = [i for i in items if i["client_id"] == user_id]
    client_id = request.args.get("client_id")
    if client_id is not None:
        items = [i for i in items if i["client_id"] == client_id]
    claim_id = request.args.get("claim_id")
    if claim_id is not None:
        items = [i for i in items if i["claim_id"] == claim_id]
    status = request.args.get("status")
    if status is not None:
        items = [i for i in items if i["status"] == status]
    return paginate([serialize(i) for i in items])


@bp.route("/customs/invoices/<invoice_id>/payments", methods=["POST"])
def pay_invoice(invoice_id):
    _, role = authenticate()
    require_role(role, {"FirmAdmin"})
    invoice = get_invoice_or_404(invoice_id)
    body = get_body()
    amount_cents = req_int(body, "amount_cents", minimum=1)

    if invoice["status"] in ("PAID", "VOID"):
        raise_err(ERR_ALREADY_TERMINAL, f"Invoice is {invoice['status']} (terminal)")
    balance = invoice["fee_cents"] - invoice["amount_paid_cents"]
    if amount_cents > balance:
        raise_err(ERR_PAYMENT_EXCEEDS_BALANCE, "amount_cents exceeds balance_cents")

    invoice["amount_paid_cents"] += amount_cents
    invoice["balance_cents"] = invoice["fee_cents"] - invoice["amount_paid_cents"]
    # Exact-equality boundary settles the invoice.
    invoice["status"] = "PAID" if amount_cents == balance else "PARTIALLY_PAID"
    touch(invoice)
    return success_object(serialize(invoice))


@bp.route("/customs/invoices/<invoice_id>/void", methods=["POST"])
def void_invoice(invoice_id):
    _, role = authenticate()
    require_role(role, {"ComplianceManager"})
    invoice = get_invoice_or_404(invoice_id)
    get_body()
    if invoice["status"] in ("PAID", "VOID"):
        raise_err(ERR_ALREADY_TERMINAL, f"Invoice is {invoice['status']} (terminal)")
    if invoice["amount_paid_cents"] > 0:
        raise_err(ERR_INVOICE_HAS_PAYMENTS, "Invoice has recorded payments")
    if invoice["status"] != "ISSUED":
        raise_err(ERR_INVALID_STATE, f"Only ISSUED invoices may be voided (got {invoice['status']})")
    invoice["status"] = "VOID"
    touch(invoice)
    return success_object(serialize(invoice))
