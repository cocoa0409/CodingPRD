"""Order booking, the metal pass-through quote, price lock and cancellation (PRD 3.5)."""

from flask import Blueprint

import constants as C
import errors
import lookups
import response
import validation
from auth import deny, require_auth
from db import all_sorted, db, new_record, touch
from serializers import view, views
from services import cascades, pricing
from util import D, money, rhu

bp = Blueprint("orders", __name__)

_READ_ROLES = ("BillingAnalyst", "ShippingClerk", "ProcessEngineer", "PlantAdmin", "Customer")


@bp.route("/customer-orders", methods=["POST"])
def create_order():
    require_auth("BillingAnalyst", "PlantAdmin")
    b = validation.body()
    customer_id = validation.f_str(b, "customer_id")
    product_id = validation.f_str(b, "product_id")
    order_number = validation.f_str(b, "order_number")
    ordered_kft = validation.f_num(b, "ordered_kft", gt=0)
    price_basis = validation.f_enum(b, "price_basis", C.PRICE_BASES)
    conversion_price = validation.f_num(b, "conversion_price_usd_per_kft", gt=0)
    order_date = validation.f_date(b, "order_date")
    cut_service = validation.f_bool(b, "cut_to_length_service", default=False)
    cut_lengths = validation.f_num_array(b, "requested_cut_lengths_ft", default=None)
    if cut_lengths is None:
        cut_lengths = []
    if cut_service and len(cut_lengths) == 0:
        validation.bad("requested_cut_lengths_ft must be non-empty on a cut-to-length order")

    # PRD 2.10 resolves product_id before customer_id.
    product = lookups.product(product_id)
    customer = lookups.customer(customer_id)

    if product["status"] != "RELEASED":
        errors.fail(
            errors.ERR_INVALID_PRODUCT_STATE,
            "Orders may only be booked against a RELEASED SKU (this one is %s)" % product["status"],
        )

    rec = new_record()
    rec.update({
        "customer_id": customer_id,
        "product_id": product_id,
        "order_number": order_number,
        "ordered_kft": ordered_kft,
        "price_basis": price_basis,
        "conversion_price_usd_per_kft": conversion_price,
        "cut_to_length_service": cut_service,
        "requested_cut_lengths_ft": cut_lengths,
        "order_date": order_date,
        "quoted_metal_price_usd_per_lb": None,
        "quoted_unit_price_usd_per_kft": None,
        "quoted_subtotal_usd": None,
        "quoted_cut_fee_usd": None,
        "quoted_surcharge_usd": None,
        "quoted_total_usd": None,
        "shipped_kft": rhu("0", 3),
        "invoiced_total_usd": money("0"),
        "hold_reason": None,
        "pricing_status": "QUOTED",
        "fulfillment_status": "OPEN",
    })
    # Raises ERR_NO_METAL_QUOTE before anything is persisted.
    pricing.order_quoted_total(rec, product, customer)

    db.customer_orders[rec["id"]] = rec
    return response.created(view("customer_order", rec))


@bp.route("/customer-orders/<order_id>", methods=["GET"])
def get_order(order_id):
    actor = require_auth(*_READ_ROLES)
    rec = lookups.order(order_id)
    if actor.is_customer and rec["customer_id"] != actor.user_id:
        deny()
    return response.ok(view("customer_order", rec))


@bp.route("/customer-orders", methods=["GET"])
def list_orders():
    actor = require_auth(*_READ_ROLES)
    limit, offset = validation.pagination()
    customer_id = validation.q_str("customer_id")
    product_id = validation.q_str("product_id")
    pricing_status = validation.q_enum("pricing_status", C.PRICING_STATUSES)
    fulfillment_status = validation.q_enum("fulfillment_status", C.FULFILLMENT_STATUSES)

    if actor.is_customer:
        if customer_id is not None and customer_id != actor.user_id:
            deny()
        customer_id = actor.user_id

    rows = all_sorted(db.customer_orders)
    if customer_id is not None:
        rows = [r for r in rows if r["customer_id"] == customer_id]
    if product_id is not None:
        rows = [r for r in rows if r["product_id"] == product_id]
    if pricing_status is not None:
        rows = [r for r in rows if r["pricing_status"] == pricing_status]
    if fulfillment_status is not None:
        rows = [r for r in rows if r["fulfillment_status"] == fulfillment_status]
    page, total = response.paginate(rows, limit, offset)
    return response.ok_list(views("customer_order", page), limit, offset, total)


@bp.route("/customer-orders/<order_id>/price-lock", methods=["POST"])
def price_lock(order_id):
    require_auth("BillingAnalyst", "PlantAdmin")
    validation.body()
    order = lookups.order(order_id)
    status = order["pricing_status"]
    if status == "QUOTED":
        if order["fulfillment_status"] not in ("OPEN", "PARTIALLY_SHIPPED"):
            errors.fail(
                errors.ERR_INVALID_ORDER_STATE,
                "A quoted order may only be locked while it is open or partially shipped",
            )
    elif status != "HELD":
        errors.fail(
            errors.ERR_INVALID_ORDER_STATE,
            "An order whose pricing status is %s may not be locked" % status,
        )
    order["pricing_status"] = "LOCKED"
    order["hold_reason"] = None
    touch(order)
    return response.ok(view("customer_order", order))


@bp.route("/customer-orders/<order_id>/cancel", methods=["POST"])
def cancel_order(order_id):
    require_auth("BillingAnalyst", "PlantAdmin")
    b = validation.body()
    validation.f_str(b, "reason", required=False, default=None, allow_empty=True)

    order = lookups.order(order_id)
    if order["fulfillment_status"] != "OPEN":
        errors.fail(
            errors.ERR_INVALID_ORDER_STATE,
            "Only an OPEN order may be cancelled (this one is %s)" % order["fulfillment_status"],
        )
    for shipment in db.shipments.values():
        if shipment["order_id"] == order["id"]:
            errors.fail(
                errors.ERR_ORDER_HAS_SHIPMENTS,
                "An order that has shipped may not be cancelled",
            )

    order["fulfillment_status"] = "CANCELLED"
    touch(order)
    cascades.order_cancelled(order)
    return response.ok(view("customer_order", order))
