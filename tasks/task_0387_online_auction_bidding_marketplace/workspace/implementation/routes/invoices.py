"""Seller-fee-invoice endpoints. PRD §3.7 (settle)."""
from flask import Blueprint, request

import db
import errors
import response
import middleware as mw
from services import core

bp = Blueprint("invoices", __name__)


@bp.route("/seller-fee-invoices/<invoice_id>", methods=["GET"])
def get_invoice(invoice_id):
    caller = mw.require_auth()
    mw.require_role(caller, {"Seller", "PlatformAdmin"})
    inv = db.seller_fee_invoices.get(invoice_id)
    if inv is None:
        raise errors.not_found("Invoice not found.")
    if caller.role == "Seller" and inv["seller_account_id"] != caller.user_id:
        raise errors.not_owner("Only the invoiced seller may view this invoice.")
    return response.success(core.ser_invoice(inv), status=200)


@bp.route("/seller-fee-invoices", methods=["GET"])
def list_invoices():
    caller = mw.require_auth()
    mw.require_role(caller, {"Seller", "PlatformAdmin"})
    order_id = request.args.get("order_id")
    seller_account_id = request.args.get("seller_account_id")
    items = list(db.seller_fee_invoices.values())
    if order_id is not None:
        items = [i for i in items if i["order_id"] == order_id]
    if seller_account_id is not None:
        items = [i for i in items if i["seller_account_id"] == seller_account_id]
    from routes.helpers import paginate_list
    return paginate_list(items, core.ser_invoice)


@bp.route("/seller-fee-invoices/<invoice_id>/settle", methods=["POST"])
def settle_invoice(invoice_id):
    caller = mw.require_auth()                  # priority 1
    mw.require_role(caller, {"PlatformAdmin"})  # priority 2
    inv = db.seller_fee_invoices.get(invoice_id)  # existence (priority 4)
    if inv is None:
        raise errors.not_found("Invoice not found.")

    # State (priority 6): settle defined only from INVOICED.
    if inv["settlement_status"] != "INVOICED":
        raise errors.invalid_state("Only an INVOICED invoice may be settled.")

    inv["settlement_status"] = "PAID"
    core.touch(inv)
    # Recompute seller fee balance/standing (this invoice now contributes 0).
    core.recompute_account_fee_balance(inv["seller_account_id"])
    return response.success(core.ser_invoice(inv), status=200)
