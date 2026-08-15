"""Invoice and Payment routes."""
from datetime import timedelta

from flask import Blueprint, request

import db
from db import stamp_new, touch, _parse_iso, _format_iso
from errors import (err_order_not_found, err_invoice_not_found,
                    err_invalid_request, err_insufficient_permissions,
                    err_order_not_invoicable, err_invoice_not_payable,
                    err_invalid_fx_rate, err_currency_mismatch,
                    err_payment_overpayment)
from middleware import require_roles, require_any_authenticated
from response import success_object, success_list, parse_pagination
from services.exposure import recompute_agent_exposure
from services.money import fx_convert, round_half_up_cents
from services.pricing import final_invoice_pricing, FX_CLOSING_TOLERANCE_CENTS
from services.validate import get_body, req_number, req_int, req_enum

bp = Blueprint("invoice", __name__)

CURRENCIES = ("USD", "EUR", "GBP", "SGD")


def _order_call(order):
    quotation = db.quotations.get(order.get("quotation_id"))
    if quotation is None:
        return None
    requisition = db.requisitions.get(quotation.get("requisition_id"))
    if requisition is None:
        return None
    return db.vessel_calls.get(requisition.get("vessel_call_id"))


def _recompute_outstanding(inv):
    inv["outstanding_cents"] = (inv["total_cents"] - inv["paid_amount_cents"]
                                - inv["credited_amount_cents"]
                                - inv["fx_writeoff_cents"])


def _rederive_invoice_status(inv):
    """Re-derive invoice status after a credit apply/revoke (PRD §3.13).

    CREDITED when outstanding is fully covered and some credit stands;
    otherwise ISSUED with no payments, PARTIALLY_PAID with partial payments.
    (PAID is only ever reached via a closing payment, never re-derived here —
    a CREDITED invoice that is revoked returns to ISSUED or PARTIALLY_PAID.)
    """
    if inv["status"] == "VOID":
        return
    if inv["outstanding_cents"] == 0 and inv["credited_amount_cents"] > 0 \
            and inv["paid_amount_cents"] + inv["credited_amount_cents"] >= inv["total_cents"]:
        inv["status"] = "CREDITED"
    elif inv["paid_amount_cents"] > 0:
        inv["status"] = "PARTIALLY_PAID"
    else:
        inv["status"] = "ISSUED"


def _sync_order_payment_status(order, inv):
    """Order payment dimension follows the invoice (PRD §3.10)."""
    if inv["status"] == "PAID":
        order["payment_status"] = "PAID"
    elif inv["status"] == "PARTIALLY_PAID":
        order["payment_status"] = "PARTIALLY_PAID"
    elif inv["status"] == "CREDITED":
        order["payment_status"] = "CREDITED"
    elif inv["status"] == "ISSUED":
        order["payment_status"] = "INVOICED"
    touch(order)


# ---------------------------------------------------------------------------
# Invoice
# ---------------------------------------------------------------------------

@bp.route("/chandlery/orders/<order_id>/invoices", methods=["POST"])
@require_roles("FinanceController")
def issue_invoice(user_id, role, order_id):
    order = db.orders.get(order_id)
    if order is None:
        raise err_order_not_found()
    body = get_body()
    fx_rate = req_number(body, "fx_rate_to_settlement")
    if not (fx_rate > 0):
        raise err_invalid_fx_rate()

    vessel_call = _order_call(order)
    # state gate: payment UNINVOICED and (fulfillment DELIVERED or
    # (PARTIALLY_DELIVERED with vessel DEPARTED)); at most one non-VOID invoice
    if order["payment_status"] != "UNINVOICED":
        raise err_order_not_invoicable()
    fulfillment = order["fulfillment_status"]
    if fulfillment == "DELIVERED":
        pass
    elif fulfillment == "PARTIALLY_DELIVERED" and vessel_call is not None \
            and vessel_call["status"] == "DEPARTED":
        pass
    else:
        raise err_order_not_invoicable()
    for inv in db.invoices.values():
        if inv["order_id"] == order_id and inv["status"] != "VOID":
            raise err_order_not_invoicable()

    agent = db.ship_agents[order["agent_id"]]
    # cold hours read the LAST delivered delivery's confirmed_at
    last_confirmed_at = None
    for d in db.deliveries.values():
        if d["order_id"] == order_id and d["status"] == "DELIVERED" and d.get("confirmed_at"):
            dt = _parse_iso(d["confirmed_at"])
            if last_confirmed_at is None or dt > last_confirmed_at:
                last_confirmed_at = dt

    priced = final_invoice_pricing(order, vessel_call, db.catalog_items, last_confirmed_at)
    total_cents = round_half_up_cents(priced["total_usd_cents"] * fx_rate)
    issued_at = db.now_dt()
    due_date = issued_at + timedelta(days=agent["payment_terms_days"])

    invoice = {
        "order_id": order_id,
        "settlement_currency": agent["settlement_currency"],
        "fx_rate_to_settlement": fx_rate,
        "lines": priced["lines"],
        "duty_free_subtotal_cents": priced["duty_free_subtotal_cents"],
        "dutiable_subtotal_cents": priced["dutiable_subtotal_cents"],
        "total_duty_cents": priced["total_duty_cents"],
        "subtotal_cents": priced["subtotal_cents"],
        "rebate_cents": priced["rebate_cents"],
        "total_usd_cents": priced["total_usd_cents"],
        "total_cents": total_cents,
        "paid_amount_cents": 0,
        "credited_amount_cents": 0,
        "fx_writeoff_cents": 0,
        "outstanding_cents": total_cents,
        "issued_at": _format_iso(issued_at),
        "due_date": _format_iso(due_date),
        "issued_by_user_id": user_id,
        "status": "ISSUED",
    }
    stamp_new(invoice)
    db.invoices[invoice["id"]] = invoice
    # order payment dimension: UNINVOICED -> INVOICED
    order["payment_status"] = "INVOICED"
    touch(order)
    recompute_agent_exposure(order["agent_id"])
    return success_object(invoice, status=201)


@bp.route("/chandlery/orders/<order_id>/invoices", methods=["GET"])
@require_any_authenticated
def list_order_invoices(user_id, role, order_id):
    if order_id not in db.orders:
        raise err_order_not_found()
    items = [i for i in db.invoices.values() if i["order_id"] == order_id]
    items.sort(key=lambda r: r["created_at"])
    limit, offset = parse_pagination(request.args)
    return success_list(items[offset:offset + limit], limit, offset, len(items))


@bp.route("/chandlery/invoices/<invoice_id>", methods=["GET"])
@require_any_authenticated
def get_invoice(user_id, role, invoice_id):
    inv = db.invoices.get(invoice_id)
    if inv is None:
        raise err_invoice_not_found()
    return success_object(inv)


# ---------------------------------------------------------------------------
# Payment
# ---------------------------------------------------------------------------

@bp.route("/chandlery/invoices/<invoice_id>/payments", methods=["POST"])
@require_roles("ShipAgentClerk")
def record_payment(user_id, role, invoice_id):
    inv = db.invoices.get(invoice_id)
    if inv is None:
        raise err_invoice_not_found()
    # entity-backed ownership: clerk pays only own agent's invoices
    order = db.orders.get(inv["order_id"])
    if order is None or order.get("agent_id") != user_id:
        raise err_insufficient_permissions()
    body = get_body()
    amount_cents = req_int(body, "amount_cents")
    if amount_cents < 1:
        from errors import err_invalid_qty
        raise err_invalid_qty("amount_cents must be >= 1")
    currency = req_enum(body, "currency", CURRENCIES)

    # state: invoice must be ISSUED or PARTIALLY_PAID
    if inv["status"] not in ("ISSUED", "PARTIALLY_PAID"):
        raise err_invoice_not_payable()

    # currency admissibility + fx conversion
    if currency == inv["settlement_currency"]:
        converted = amount_cents
    else:
        fx_rate = body.get("fx_rate_to_invoice_currency")
        if fx_rate is None:
            raise err_currency_mismatch()
        if isinstance(fx_rate, bool) or not isinstance(fx_rate, (int, float)):
            raise err_invalid_fx_rate()
        if not (fx_rate > 0):
            raise err_invalid_fx_rate()
        converted = fx_convert(amount_cents, fx_rate)

    # fx_payment_settlement (SCAFFOLD §1.3, PRD §3.10): fifty-cent closing
    # tolerance measured between the converted payment and the outstanding
    # balance as it stood BEFORE this payment ("the closing payment lands
    # within +/- 50 cents of outstanding"; overpayment iff the converted sum
    # exceeds outstanding + 50). This reading keeps the pinned invariant
    # paid + credited + writeoff + outstanding == total at every instant.
    outstanding_before = inv["outstanding_cents"]
    delta = converted - outstanding_before
    if delta > FX_CLOSING_TOLERANCE_CENTS:
        raise err_payment_overpayment()

    writeoff_applied = 0
    if delta >= -FX_CLOSING_TOLERANCE_CENTS:
        # closes within the inclusive band [-50, +50]: positive write-off
        # forgives an underpayment; negative books a small overpayment.
        writeoff_applied = outstanding_before - converted
        inv["fx_writeoff_cents"] += writeoff_applied
        inv["paid_amount_cents"] += converted
        inv["outstanding_cents"] = 0
        inv["status"] = "PAID"
    else:
        inv["paid_amount_cents"] += converted
        inv["outstanding_cents"] = outstanding_before - converted
        inv["status"] = "PARTIALLY_PAID"
    touch(inv)

    payment = {
        "invoice_id": invoice_id,
        "amount_cents": amount_cents,
        "currency": currency,
        "fx_rate_to_invoice_currency": (body.get("fx_rate_to_invoice_currency")
                                        if currency != inv["settlement_currency"] else None),
        "converted_amount_cents": converted,
        "writeoff_applied_cents": writeoff_applied,
        "recorded_by_user_id": user_id,
    }
    stamp_new(payment, common=False)  # append-only: id + created_at only
    db.payments[payment["id"]] = payment

    # order payment dimension follows the invoice
    if inv["status"] == "PAID":
        order["payment_status"] = "PAID"
    elif inv["status"] == "PARTIALLY_PAID":
        order["payment_status"] = "PARTIALLY_PAID"
    touch(order)
    recompute_agent_exposure(order["agent_id"])
    return success_object(payment, status=201)


@bp.route("/chandlery/invoices/<invoice_id>/payments", methods=["GET"])
@require_any_authenticated
def list_payments(user_id, role, invoice_id):
    if invoice_id not in db.invoices:
        raise err_invoice_not_found()
    items = [p for p in db.payments.values() if p["invoice_id"] == invoice_id]
    items.sort(key=lambda r: r["created_at"])
    limit, offset = parse_pagination(request.args)
    return success_list(items[offset:offset + limit], limit, offset, len(items))
