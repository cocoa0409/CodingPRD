"""PurchaseOrder endpoints (PRD §3.6): issue, receive (with lot upsert,
backorder promotion, and first-receipt cycle auto-advance), pay, cancel,
close."""

from decimal import Decimal

from flask import Blueprint, request

import serializers
from db import bump, refresh, store
from errors import (ERR_OVER_RECEIPT, ERR_PAYMENT_EXCEEDS_BALANCE,
                    ERR_PO_NOT_CLOSABLE, budget_exceeded, conflict,
                    invalid_state)
from middleware import (ALL_ROLES, auth_context, get_body, get_or_404, req_decimal,
                        req_enum, req_int, require_roles)
from response import paginate, sort_created, success_object
from services import cascades
from services.calculations import (ledger_available,
                                   recompute_open_backorder_count)

bp = Blueprint("purchase_orders", __name__)


def _get_po(po_id):
    return get_or_404(store.purchase_orders, po_id, "PurchaseOrder")


@bp.route("/purchase-orders", methods=["GET"])
def list_purchase_orders():
    user_id, role = auth_context()
    require_roles(role, ALL_ROLES)
    items = list(store.purchase_orders.values())
    cycle_id = request.args.get("cycle_id")
    quote_id = request.args.get("quote_id")
    order_status = request.args.get("order_status")
    payment_status = request.args.get("payment_status")
    if cycle_id is not None:
        items = [p for p in items if p["cycle_id"] == cycle_id]
    if quote_id is not None:
        items = [p for p in items if p["quote_id"] == quote_id]
    if order_status is not None:
        items = [p for p in items if p["order_status"] == order_status]
    if payment_status is not None:
        items = [p for p in items if p["payment_status"] == payment_status]
    return paginate(sort_created(items), serializers.purchase_order)


@bp.route("/purchase-orders/<poId>", methods=["GET"])
def get_purchase_order(poId):
    user_id, role = auth_context()
    require_roles(role, ALL_ROLES)
    return success_object(serializers.purchase_order(_get_po(poId)))


@bp.route("/purchase-orders/<poId>/issue", methods=["POST"])
def issue_purchase_order(poId):
    user_id, role = auth_context()
    require_roles(role, ("ProcurementOfficer",))
    po = _get_po(poId)
    if po["order_status"] != "DRAFT":
        raise invalid_state("only a DRAFT purchase order may be issued")
    # Tier 12 fiscal envelope (inclusive: an exactly equal balance passes).
    ledger = store.ledgers.get(po["cycle_id"])
    if ledger is None or ledger_available(ledger) < po["total_amount"]:
        raise budget_exceeded()
    po["order_status"] = "ISSUED"
    po["payment_status"] = "ENCUMBERED"
    bump(po)
    ledger["encumbered_total"] += po["total_amount"]
    refresh(ledger)
    return success_object(serializers.purchase_order(po))


@bp.route("/purchase-orders/<poId>/receive", methods=["POST"])
def receive_purchase_order(poId):
    user_id, role = auth_context()
    require_roles(role, ("WarehouseManager",))
    po = _get_po(poId)
    body = get_body()
    qty_received = req_int(body, "qty_received", minimum=1)
    if po["order_status"] not in ("ISSUED", "PARTIALLY_RECEIVED"):
        raise invalid_state("receipts post against ISSUED or PARTIALLY_RECEIVED "
                            "purchase orders")
    if po["received_print_qty"] + qty_received > po["print_quantity"]:
        raise conflict(ERR_OVER_RECEIPT,
                       "the receipt would exceed the ordered print quantity")

    po["received_print_qty"] += qty_received
    po["order_status"] = ("RECEIVED" if po["received_print_qty"] == po["print_quantity"]
                          else "PARTIALLY_RECEIVED")
    bump(po)

    quote = store.quotes.get(po["quote_id"])
    material_id = quote["material_id"] if quote else None
    if material_id is not None:
        lot = cascades.lot_for_receipt(material_id)
        lot["on_hand_units"] += qty_received
        lot["total_received_units"] += qty_received
        refresh(lot)
        cascades.run_backorder_promotion(store.materials[material_id])

    cycle = store.cycles.get(po["cycle_id"])
    if cycle is not None:
        recompute_open_backorder_count(cycle)
        if cycle["status"] == "PROCURING":
            # The first receipt for the cycle auto-advances it to DISTRIBUTING.
            cycle["status"] = "DISTRIBUTING"
            bump(cycle)
    return success_object(serializers.purchase_order(po))


@bp.route("/purchase-orders/<poId>/pay", methods=["POST"])
def pay_purchase_order(poId):
    user_id, role = auth_context()
    require_roles(role, ("ProcurementOfficer",))
    po = _get_po(poId)
    body = get_body()
    amount = req_decimal(body, "amount", minimum=Decimal("0"),
                         exclusive_minimum=True)
    if (po["order_status"] not in ("ISSUED", "PARTIALLY_RECEIVED", "RECEIVED")
            or po["payment_status"] not in ("ENCUMBERED", "PARTIALLY_PAID")):
        raise invalid_state("payments post against an issued order with an open "
                            "encumbrance")
    outstanding = po["total_amount"] - po["amount_paid"]
    if amount > outstanding:
        raise conflict(ERR_PAYMENT_EXCEEDS_BALANCE,
                       "the payment exceeds the outstanding balance")
    po["amount_paid"] += amount
    po["payment_status"] = ("PAID" if po["amount_paid"] == po["total_amount"]
                            else "PARTIALLY_PAID")
    bump(po)
    ledger = store.ledgers.get(po["cycle_id"])
    if ledger is not None:
        ledger["encumbered_total"] -= amount
        ledger["expended_total"] += amount
        refresh(ledger)
    return success_object(serializers.purchase_order(po))


@bp.route("/purchase-orders/<poId>/cancel", methods=["POST"])
def cancel_purchase_order(poId):
    user_id, role = auth_context()
    require_roles(role, ("ProcurementOfficer",))
    po = _get_po(poId)
    if po["order_status"] not in ("DRAFT", "ISSUED", "PARTIALLY_RECEIVED"):
        raise invalid_state("only a DRAFT, ISSUED, or PARTIALLY_RECEIVED order "
                            "may be cancelled")
    # Compensation: release the unpaid remainder when the order carried an
    # encumbrance; expended money stays expended (PRD §3.6).
    if po["payment_status"] in ("ENCUMBERED", "PARTIALLY_PAID"):
        ledger = store.ledgers.get(po["cycle_id"])
        if ledger is not None:
            ledger["encumbered_total"] -= (po["total_amount"] - po["amount_paid"])
            refresh(ledger)
    po["order_status"] = "CANCELLED"
    po["payment_status"] = "RELEASED"
    bump(po)
    return success_object(serializers.purchase_order(po))


@bp.route("/purchase-orders/<poId>/transitions", methods=["POST"])
def purchase_order_transition(poId):
    user_id, role = auth_context()
    require_roles(role, ("ProcurementOfficer",))
    po = _get_po(poId)
    body = get_body()
    to_state = req_enum(body, "to_state", ("CLOSED",))
    if po["order_status"] != "RECEIVED":
        raise invalid_state("only a RECEIVED purchase order may be closed")
    if po["payment_status"] != "PAID":
        raise conflict(ERR_PO_NOT_CLOSABLE,
                       "the purchase order must be fully paid before closing")
    po["order_status"] = "CLOSED"
    bump(po)
    return success_object(serializers.purchase_order(po))
