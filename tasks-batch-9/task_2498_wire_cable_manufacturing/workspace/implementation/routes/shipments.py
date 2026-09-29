"""Shipment staging and invoicing (PRD 3.8, 3.9)."""

from flask import Blueprint

import clock
import constants as C
import errors
import lookups
import response
import validation
from auth import deny, require_auth
from db import all_sorted, db, new_record, sort_created, touch
from serializers import view, views
from services import ledger, pricing
from util import D, money, rhu

bp = Blueprint("shipments", __name__)

_READ_ROLES = ("ShippingClerk", "BillingAnalyst", "PlantAdmin", "Customer")


@bp.route("/shipments", methods=["POST"])
def create_shipment():
    require_auth("ShippingClerk", "PlantAdmin")
    b = validation.body()
    order_id = validation.f_str(b, "order_id")
    lot_id = validation.f_str(b, "lot_id")
    reel_id = validation.f_str(b, "reel_id")
    shipped_length_ft = validation.f_num(b, "shipped_length_ft", gt=0)
    ship_date = validation.f_date(b, "ship_date")
    cuts_count = validation.f_int(b, "cuts_count", required=False, default=0, ge=0)
    expected_version = validation.f_int(b, "expected_order_version")

    # PRD 2.10: order_id, then lot_id, then reel_id.
    order = lookups.order(order_id)
    lot = lookups.lot(lot_id)
    reel = lookups.reel(reel_id)

    if expected_version != order["version"]:
        errors.fail(
            errors.ERR_STALE_ORDER_VERSION,
            "expected_order_version %s does not match the order's current version %s"
            % (expected_version, order["version"]),
        )

    if order["fulfillment_status"] == "CANCELLED":
        errors.fail(
            errors.ERR_INVALID_ORDER_STATE,
            "A cancelled order may not be shipped",
        )
    if reel["status"] != "LOADED" or reel["current_lot_id"] != lot["id"]:
        errors.fail(
            errors.ERR_INVALID_REEL_STATE,
            "The reel must be LOADED and must carry the lot named in the payload",
        )
    if lot["process_state"] != "PACKAGED" or lot["quality_state"] != "CONFORMING":
        errors.fail(
            errors.ERR_INVALID_LOT_STATE,
            "Shipping requires a PACKAGED, CONFORMING lot",
        )

    # Rung 8: a held price may not leave the plant.
    if order["pricing_status"] == "HELD":
        errors.fail(
            errors.ERR_ORDER_PRICING_HELD,
            "The order's pricing is HELD (%s) and nothing may ship against it"
            % order["hold_reason"],
        )

    # Rung 23: quantity on both axes at once.
    new_shipped_kft = rhu(
        D(order["shipped_kft"]) + D(shipped_length_ft) / D("1000"), 3
    )
    if new_shipped_kft > D(order["ordered_kft"]):
        errors.fail(
            errors.ERR_SHIPMENT_EXCEEDS_ORDER,
            "Shipping %s ft would carry the order past its ordered quantity"
            % shipped_length_ft,
        )
    if D(shipped_length_ft) > D(lot["packaged_length_ft"]):
        errors.fail(
            errors.ERR_SHIPMENT_EXCEEDS_ORDER,
            "shipped_length_ft exceeds the lot's packaged_length_ft",
        )

    # Rung 26: credit.
    customer = db.customers[order["customer_id"]]
    deposit = D(reel["deposit_usd"])
    if customer["status"] != "ACTIVE":
        errors.fail(
            errors.ERR_CREDIT_LIMIT_EXCEEDED,
            "The account is on CREDIT_HOLD and may not take delivery",
        )
    if D(customer["credit_exposure_usd"]) + deposit > D(customer["credit_limit_usd"]):
        errors.fail(
            errors.ERR_CREDIT_LIMIT_EXCEEDED,
            "The reel deposit would push the account past its credit limit",
        )

    rec = new_record()
    rec.update({
        "order_id": order["id"],
        "lot_id": lot["id"],
        "reel_id": reel["id"],
        "shipped_length_ft": shipped_length_ft,
        "cuts_count": cuts_count,
        "ship_date": ship_date,
        "deposit_charged_usd": money(deposit),
        "metal_price_used_usd_per_lb": None,
        "price_variant_applied": None,
        "unit_price_usd_per_kft": None,
        "extended_amount_usd": None,
        "cut_fee_usd": None,
        "volatility_surcharge_usd": None,
        "invoice_amount_usd": None,
        "invoice_date": None,
        "status": "STAGED",
    })
    db.shipments[rec["id"]] = rec

    # The reel leaves the plant. cycle_count counts completed round trips and is
    # deliberately left alone here.
    instant = clock.now_iso()
    reel["status"] = "SHIPPED"
    reel["held_by_customer_id"] = order["customer_id"]
    reel["shipped_at"] = instant
    reel["occupancy_end_at"] = instant
    touch(reel)

    customer["deposit_charged_total_usd"] = money(
        D(customer["deposit_charged_total_usd"]) + deposit
    )
    ledger.recompute_credit(customer)

    lot["process_state"] = "SHIPPED"
    touch(lot)

    order["shipped_kft"] = new_shipped_kft
    if new_shipped_kft == D(order["ordered_kft"]):
        order["fulfillment_status"] = "FULFILLED"
    elif order["fulfillment_status"] == "OPEN":
        order["fulfillment_status"] = "PARTIALLY_SHIPPED"
    touch(order)

    return response.created(view("shipment", rec))


@bp.route("/shipments/<shipment_id>", methods=["GET"])
def get_shipment(shipment_id):
    actor = require_auth(*_READ_ROLES)
    rec = lookups.shipment(shipment_id)
    if actor.is_customer:
        order = db.customer_orders.get(rec["order_id"])
        if order is None or order["customer_id"] != actor.user_id:
            deny()
    return response.ok(view("shipment", rec))


@bp.route("/shipments", methods=["GET"])
def list_shipments():
    actor = require_auth(*_READ_ROLES)
    limit, offset = validation.pagination()
    order_id = validation.q_str("order_id")
    lot_id = validation.q_str("lot_id")
    reel_id = validation.q_str("reel_id")
    status = validation.q_enum("status", C.SHIPMENT_STATUSES)

    rows = all_sorted(db.shipments)
    if actor.is_customer:
        own = {
            o["id"] for o in db.customer_orders.values()
            if o["customer_id"] == actor.user_id
        }
        if order_id is not None and order_id not in own:
            deny()
        rows = [r for r in rows if r["order_id"] in own]
    if order_id is not None:
        rows = [r for r in rows if r["order_id"] == order_id]
    if lot_id is not None:
        rows = [r for r in rows if r["lot_id"] == lot_id]
    if reel_id is not None:
        rows = [r for r in rows if r["reel_id"] == reel_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = response.paginate(rows, limit, offset)
    return response.ok_list(views("shipment", page), limit, offset, total)


@bp.route("/shipments/<shipment_id>/invoice", methods=["POST"])
def invoice_shipment(shipment_id):
    require_auth("BillingAnalyst", "PlantAdmin")
    validation.body()
    shipment = lookups.shipment(shipment_id)
    if shipment["status"] != "STAGED":
        errors.fail(
            errors.ERR_SHIPMENT_ALREADY_INVOICED,
            "The shipment has already been invoiced",
        )
    order = db.customer_orders[shipment["order_id"]]
    if order["pricing_status"] not in ("QUOTED", "LOCKED"):
        errors.fail(
            errors.ERR_INVALID_ORDER_STATE,
            "An order whose pricing status is %s may not be invoiced"
            % order["pricing_status"],
        )
    product = db.catalog_products[order["product_id"]]
    customer = db.customers[order["customer_id"]]

    # Raises ERR_INSUFFICIENT_PRICE_HISTORY under SHIP_DATE_FLOAT with a thin
    # window, leaving the shipment exactly where it was.
    pricing.shipment_invoice_amount(shipment, order, product, customer)
    amount = shipment["invoice_amount_usd"]
    shipment["status"] = "INVOICED"
    touch(shipment)

    order["invoiced_total_usd"] = money(D(order["invoiced_total_usd"]) + D(amount))
    if order["fulfillment_status"] == "FULFILLED" and order["pricing_status"] == "LOCKED":
        siblings = [s for s in db.shipments.values() if s["order_id"] == order["id"]]
        if all(s["status"] == "INVOICED" for s in siblings):
            order["pricing_status"] = "INVOICED"
    touch(order)

    reel = db.reels.get(shipment["reel_id"])
    if reel is not None and reel["status"] == "SHIPPED":
        reel["status"] = (
            "RETIRED" if reel["reel_type"] == "NON_RETURNABLE" else "RETURN_PENDING"
        )
        touch(reel)

    # open_ar_usd is the sum of invoiced shipment amounts; the recompute picks up
    # the row just promoted and re-evaluates the account's standing.
    ledger.recompute_credit(customer)

    return response.ok(view("shipment", shipment))


@bp.route("/shipments/<shipment_id>/reel-returns", methods=["GET"])
def list_shipment_reel_returns(shipment_id):
    require_auth("ShippingClerk", "BillingAnalyst", "PlantAdmin")
    limit, offset = validation.pagination()
    condition = validation.q_enum("condition", C.RETURN_CONDITIONS)
    shipment = lookups.shipment(shipment_id)

    rows = [r for r in db.reel_returns.values() if r["shipment_id"] == shipment["id"]]
    if condition is not None:
        rows = [r for r in rows if r["condition"] == condition]
    rows = sort_created(rows)
    page, total = response.paginate(rows, limit, offset)
    return response.ok_list(views("reel_return", page), limit, offset, total)
