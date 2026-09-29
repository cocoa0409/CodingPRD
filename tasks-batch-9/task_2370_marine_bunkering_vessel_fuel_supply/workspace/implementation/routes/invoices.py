"""Invoicing, indexation and settlement (PRD 3.9)."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

import db
import serializers
from db import store, touch
from errors import ApiError
from lookup import body_ref, path_ref
from middleware import roles
from response import success, success_list
from services import calc, cascade
from validation import apply_page, body, pagination, q_enum, q_str, v_datetime, v_string

bp = Blueprint("invoices", __name__)

INVOICE_READERS = ("CreditController", "OpsCoordinator", "CustomerRep")
INVOICE_STATUSES = ("PROVISIONAL", "ISSUED", "CREDIT_APPLIED", "VOID")


@bp.post("/invoices")
@roles("CreditController")
def create_invoice():
    data = body()
    order = body_ref(
        data, "delivery_order_id", store.delivery_orders, "ERR_DELIVERY_ORDER_NOT_FOUND"
    )
    v_string(data, "delivery_order_id", min_len=1)
    pricing_date = v_datetime(data, "pricing_date")
    if order is None:
        raise ApiError("ERR_DELIVERY_ORDER_NOT_FOUND")

    nomination, port, grade, customer, asset = calc.order_context(order)
    if order["logistics_status"] != "DELIVERED":
        raise ApiError("ERR_INVALID_ORDER_STATE")
    if order["measurement_status"] != "AGREED" or order["agreed_quantity_mt"] is None:
        raise ApiError("ERR_MEASUREMENT_NOT_AGREED")
    for existing in calc.invoices_of_order(order["id"]):
        if existing["status"] in calc.NON_VOID_INVOICE_STATES:
            raise ApiError("ERR_INVOICE_ALREADY_EXISTS")

    invoice = db.new_record()
    invoice.update(
        {
            "delivery_order_id": order["id"],
            "customer_id": nomination["customer_id"],
            "pricing_date": pricing_date,
            "index_price_usd_per_mt": None,
            "quantity_basis_mt": None,
            "fuel_cost_usd": None,
            "baf_pct": None,
            "baf_usd": None,
            "barging_fee_usd": None,
            "eca_surcharge_usd": None,
            "provisional_amount_usd": None,
            "claim_credit_usd": Decimal("0.00"),
            "final_amount_usd": None,
            "status": "PROVISIONAL",
            "issued_at": None,
            "due_date": None,
        }
    )
    # Raises ERR_INDEX_QUOTE_UNAVAILABLE when no quote governs the pricing date.
    calc.compute_invoice_amounts(invoice, order, nomination, port, grade)
    store.invoices[invoice["id"]] = invoice
    return success(serializers.invoice(invoice), 201)


@bp.get("/invoices/<rec_id>")
@roles(*INVOICE_READERS)
def get_invoice(rec_id):
    invoice = path_ref(store.invoices, rec_id, "ERR_INVOICE_NOT_FOUND")
    return success(serializers.invoice(invoice))


@bp.get("/invoices")
@roles(*INVOICE_READERS)
def list_invoices():
    delivery_order_id = q_str("delivery_order_id")
    customer_id = q_str("customer_id")
    status = q_enum("status", INVOICE_STATUSES)
    limit, offset = pagination()

    def match(row):
        if delivery_order_id is not None and row["delivery_order_id"] != delivery_order_id:
            return False
        if customer_id is not None and row["customer_id"] != customer_id:
            return False
        if status is not None and row["status"] != status:
            return False
        return True

    rows = db.sorted_rows(store.invoices, match)
    page = apply_page(rows, limit, offset)
    return success_list([serializers.invoice(r) for r in page], limit, offset, len(rows))


@bp.post("/invoices/<rec_id>/issue")
@roles("CreditController")
def issue_invoice(rec_id):
    invoice = path_ref(store.invoices, rec_id, "ERR_INVOICE_NOT_FOUND")
    order = store.delivery_orders.get(invoice["delivery_order_id"])
    if order["logistics_status"] != "DELIVERED":
        raise ApiError("ERR_INVALID_ORDER_STATE")
    if order["measurement_status"] != "AGREED" or order["agreed_quantity_mt"] is None:
        raise ApiError("ERR_MEASUREMENT_NOT_AGREED")
    if calc.issued_note_of_order(order["id"]) is None:
        raise ApiError("ERR_BDN_NOT_ISSUED")
    if invoice["status"] != "PROVISIONAL":
        raise ApiError("ERR_INVALID_INVOICE_STATE")

    customer = store.customers.get(invoice["customer_id"])
    invoice["status"] = "ISSUED"
    invoice["issued_at"] = db.now()
    invoice["due_date"] = db.now() + timedelta(days=customer["payment_terms_days"])
    touch(invoice)

    cascade.recompute_customer_exposure(customer)
    nomination = calc.order_nomination(order)
    if nomination is not None and nomination["fulfillment_status"] == "DELIVERED":
        nomination["fulfillment_status"] = "CLOSED"
        touch(nomination)
    return success(serializers.invoice(invoice))


@bp.post("/invoices/<rec_id>/void")
@roles("CreditController")
def void_invoice(rec_id):
    invoice = path_ref(store.invoices, rec_id, "ERR_INVOICE_NOT_FOUND")
    if invoice["status"] not in calc.NON_VOID_INVOICE_STATES:
        raise ApiError("ERR_INVALID_INVOICE_STATE")

    was_billed = invoice["status"] in calc.BILLED_INVOICE_STATES
    invoice["status"] = "VOID"
    touch(invoice)

    if was_billed:
        cascade.recompute_customer_exposure(store.customers.get(invoice["customer_id"]))
        order = store.delivery_orders.get(invoice["delivery_order_id"])
        remaining = [
            i
            for i in calc.invoices_of_order(invoice["delivery_order_id"])
            if i["status"] in calc.BILLED_INVOICE_STATES
        ]
        nomination = calc.order_nomination(order) if order else None
        if (
            not remaining
            and nomination is not None
            and nomination["fulfillment_status"] == "CLOSED"
        ):
            nomination["fulfillment_status"] = "DELIVERED"
            touch(nomination)
    return success(serializers.invoice(invoice))
