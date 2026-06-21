"""Shipment and Invoice routes (PRD §3.6, §3.7)."""
from flask import Blueprint, request

from db import db, lock, base_fields, touch
from errors import err
from middleware import require_roles, require_auth
from helpers import (
    get_body, require_fields, as_int, as_str, parse_datetime,
    paginate, serialize, serialize_list,
)
from response import success, list_response
import calculations as calc
import services as svc

bp = Blueprint("shipments", __name__)


def get_shipment_or_404(shipment_id):
    s = db.shipments.get(shipment_id)
    if s is None:
        raise err("ERR_NOT_FOUND", "Shipment not found")
    return s


def get_invoice_or_404(invoice_id):
    inv = db.invoices.get(invoice_id)
    if inv is None:
        raise err("ERR_NOT_FOUND", "Invoice not found")
    return inv


# ---------------------------------------------------------------------------
# Shipment
# ---------------------------------------------------------------------------


@bp.route("/shipments", methods=["POST"])
def create_shipment():
    require_roles("ShopAdmin")
    body = get_body()
    require_fields(body, "work_order_id", "qty_shipped", "promised_date", "actual_ship_date")
    work_order_id = as_str(body, "work_order_id")
    qty_shipped = as_int(body, "qty_shipped", minimum=1)
    promised_date_raw = body["promised_date"]
    actual_ship_date_raw = body["actual_ship_date"]
    promised_dt = parse_datetime(promised_date_raw, "promised_date")
    actual_dt = parse_datetime(actual_ship_date_raw, "actual_ship_date")
    with lock():
        wo = db.work_orders.get(work_order_id)
        if wo is None:
            raise err("ERR_NOT_FOUND", "WorkOrder not found")
        # state legality: WO must be COMPLETED or SHIPPED to ship (PRD §3.6)
        if wo["status"] not in ("COMPLETED", "SHIPPED"):
            raise err("ERR_INVALID_STATE", "WorkOrder must be COMPLETED or SHIPPED to ship")

        result = calc.shipment_on_time_and_penalty(qty_shipped, promised_dt, actual_dt)
        rec = base_fields()
        rec.update({
            "work_order_id": work_order_id,
            "qty_shipped": qty_shipped,
            "promised_date": promised_date_raw,
            "actual_ship_date": actual_ship_date_raw,
            "on_time": result["on_time"],
            "days_late": result["days_late"],
            "late_penalty_cents": result["late_penalty_cents"],
            "status": "SHIPPED",
        })
        db.shipments[rec["id"]] = rec

        # increase WO.qty_shipped; bubble-up COMPLETED -> SHIPPED
        wo["qty_shipped"] += qty_shipped
        touch(wo)
        svc.maybe_bubble_wo_completed_to_shipped(wo)

        return success(serialize(rec), status=201)


@bp.route("/shipments/<shipment_id>", methods=["GET"])
def get_shipment(shipment_id):
    require_auth()
    with lock():
        return success(serialize(get_shipment_or_404(shipment_id)))


@bp.route("/shipments", methods=["GET"])
def list_shipments():
    require_auth()
    work_order_id = request.args.get("work_order_id")
    status = request.args.get("status")
    with lock():
        items = list(db.shipments.values())
        if work_order_id:
            items = [s for s in items if s["work_order_id"] == work_order_id]
        if status:
            items = [s for s in items if s["status"] == status]
        page, limit, offset, total = paginate(items)
        return list_response(serialize_list(page), limit, offset, total)


@bp.route("/shipments/<shipment_id>/void", methods=["POST"])
def void_shipment(shipment_id):
    require_roles("ShopAdmin")
    with lock():
        s = get_shipment_or_404(shipment_id)
        if s["status"] != "SHIPPED":
            raise err("ERR_INVALID_STATE", "Shipment must be SHIPPED to void")
        # no ISSUED/PAID invoice references it
        for inv in db.invoices.values():
            if inv["shipment_id"] == shipment_id and inv["status"] in ("ISSUED", "PAID"):
                raise err("ERR_SHIPMENT_HAS_INVOICE", "Shipment has an active invoice")
        s["status"] = "VOIDED"
        touch(s)
        # compensation: reverse WO.qty_shipped; SHIPPED -> COMPLETED
        wo = db.work_orders.get(s["work_order_id"])
        if wo is not None:
            wo["qty_shipped"] -= s["qty_shipped"]
            if wo["status"] == "SHIPPED":
                wo["status"] = "COMPLETED"
            touch(wo)
        return success(serialize(s))


# ---------------------------------------------------------------------------
# Invoice
# ---------------------------------------------------------------------------


@bp.route("/invoices", methods=["POST"])
def create_invoice():
    require_roles("ShopAdmin")
    body = get_body()
    require_fields(body, "shipment_id")
    shipment_id = as_str(body, "shipment_id")
    with lock():
        shipment = db.shipments.get(shipment_id)
        if shipment is None:
            raise err("ERR_NOT_FOUND", "Shipment not found")
        # state legality: only a SHIPPED shipment can be invoiced (PRD §3.7)
        if shipment["status"] != "SHIPPED":
            raise err("ERR_INVALID_STATE", "Shipment must be SHIPPED to invoice")

        wo = db.work_orders.get(shipment["work_order_id"])
        quote = db.quotes.get(wo["quote_id"]) if wo else None
        quoted_unit = quote["quoted_unit_price_cents"] if quote else 0

        result = calc.invoice_total(quoted_unit, shipment["qty_shipped"],
                                    shipment["late_penalty_cents"])
        rec = base_fields()
        rec.update({
            "shipment_id": shipment_id,
            "work_order_id": shipment["work_order_id"],
            "subtotal_cents": result["subtotal_cents"],
            "tax_cents": result["tax_cents"],
            "penalty_credit_cents": result["penalty_credit_cents"],
            "total_cents": result["total_cents"],
            "status": "ISSUED",
        })
        db.invoices[rec["id"]] = rec
        return success(serialize(rec), status=201)


@bp.route("/invoices/<invoice_id>", methods=["GET"])
def get_invoice(invoice_id):
    require_auth()
    with lock():
        return success(serialize(get_invoice_or_404(invoice_id)))


@bp.route("/invoices", methods=["GET"])
def list_invoices():
    require_auth()
    shipment_id = request.args.get("shipment_id")
    work_order_id = request.args.get("work_order_id")
    status = request.args.get("status")
    with lock():
        items = list(db.invoices.values())
        if shipment_id:
            items = [i for i in items if i["shipment_id"] == shipment_id]
        if work_order_id:
            items = [i for i in items if i["work_order_id"] == work_order_id]
        if status:
            items = [i for i in items if i["status"] == status]
        page, limit, offset, total = paginate(items)
        return list_response(serialize_list(page), limit, offset, total)


@bp.route("/invoices/<invoice_id>/pay", methods=["POST"])
def pay_invoice(invoice_id):
    require_roles("ShopAdmin")
    with lock():
        inv = get_invoice_or_404(invoice_id)
        if inv["status"] != "ISSUED":
            raise err("ERR_INVALID_STATE", "Invoice must be ISSUED to pay")
        inv["status"] = "PAID"
        touch(inv)
        return success(serialize(inv))


@bp.route("/invoices/<invoice_id>/void", methods=["POST"])
def void_invoice(invoice_id):
    require_roles("ShopAdmin")
    with lock():
        inv = get_invoice_or_404(invoice_id)
        if inv["status"] != "ISSUED":
            raise err("ERR_INVALID_STATE", "Invoice must be ISSUED to void")
        inv["status"] = "VOIDED"
        touch(inv)
        return success(serialize(inv))
