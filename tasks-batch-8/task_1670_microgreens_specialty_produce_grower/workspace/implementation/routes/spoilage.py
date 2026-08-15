"""SpoilageCredit endpoints (PRD 3.7)."""
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, g, request

from db import db
from errors import (
    ApiError,
    ERR_CREDIT_EXCEEDS_DELIVERY,
    ERR_CREDIT_NOT_FOUND,
    ERR_FORBIDDEN,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_ORDER_ITEM_NOT_FOUND,
    ERR_STOP_NOT_FOUND,
)
from middleware import get_body, req_num, req_str, require_roles
from response import success, serialize
from services import line_extension_cents, new_resource, q3, touch
from routes.listing import list_response

bp = Blueprint("spoilage", __name__)

ALL = ("Grower", "Chef", "OpsManager")
PLAN_CAP_THRESHOLD = Decimal("0.70")
PLAN_CAP_FACTOR = Decimal("0.85")
OVERWEIGHT_ALLOWANCE = Decimal("1.10")
MAX_PRICE_REDUCTION = Decimal("0.25")


def _compute_credit_cents(item, credit_qty_kg, pricing_variant):
    """Dual-variant spoilage pricing (PRD 3.7). Single final rounding."""
    unit_price = Decimal(item["unit_price_cents_per_kg"])
    if pricing_variant == "ORIGINAL_PAPER":
        # Credit at the invoiced line price.
        return line_extension_cents(credit_qty_kg, item["unit_price_cents_per_kg"])
    # POST_HARVEST_PRICING: pinned evaluation order — plan cap factor first,
    # then price adjustment, then capped unit price, then multiply and round.
    plan = _latest_harvested_plan(item["variety_id"])
    if plan is None or Decimal(str(plan["base_harvest_kg"])) <= 0:
        capped = unit_price
    else:
        harvested = Decimal("0")
        for b in db.tray_batches.values():
            if b["crop_plan_id"] == plan["id"] and b["status"] == "HARVESTED":
                harvested += Decimal(str(b["harvested_kg"]))
        ratio = harvested / Decimal(str(plan["base_harvest_kg"]))
        plan_cap_factor = (
            Decimal("1.00") if ratio >= PLAN_CAP_THRESHOLD else PLAN_CAP_FACTOR
        )
        overweight_excess = max(Decimal("0"), ratio - OVERWEIGHT_ALLOWANCE)
        price_adjustment = Decimal("1.00") - min(MAX_PRICE_REDUCTION, overweight_excess)
        capped = unit_price * plan_cap_factor * price_adjustment
    cents = (Decimal(credit_qty_kg) * capped).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return int(cents)


def _latest_harvested_plan(variety_id):
    """The crop plan supplying this variety: most recently created plan having
    at least one HARVESTED tray batch."""
    candidates = []
    for plan in db.crop_plans.values():
        if plan["variety_id"] != variety_id:
            continue
        if any(
            b["crop_plan_id"] == plan["id"] and b["status"] == "HARVESTED"
            for b in db.tray_batches.values()
        ):
            candidates.append(plan)
    if not candidates:
        return None
    return max(candidates, key=lambda p: p["_seq"])


@bp.post("/spoilage-credits")
@require_roles("Chef", "OpsManager")
def create_credit():
    body = get_body()
    delivery_stop_id = req_str(body, "delivery_stop_id")
    order_item_id = req_str(body, "order_item_id")
    credit_qty_kg = req_num(body, "credit_qty_kg")
    pricing_variant = req_str(body, "pricing_variant")
    if pricing_variant not in ("ORIGINAL_PAPER", "POST_HARVEST_PRICING"):
        raise ApiError(400, ERR_INVALID_REQUEST, "pricing_variant is not valid.")
    stop = db.delivery_stops.get(delivery_stop_id)
    if stop is None:
        raise ApiError(404, ERR_STOP_NOT_FOUND, "delivery stop id does not exist.")
    item = db.order_items.get(order_item_id)
    if item is None:
        raise ApiError(404, ERR_ORDER_ITEM_NOT_FOUND, "order item id does not exist.")
    if g.user_role == "Chef" and stop["customer_id"] != g.user_id:
        raise ApiError(
            403, ERR_FORBIDDEN, "Chef may only report spoilage on their own stops."
        )
    if credit_qty_kg <= 0:
        raise ApiError(400, ERR_INVALID_REQUEST, "credit_qty_kg must be positive.")
    if stop["outcome"] != "DELIVERED":
        raise ApiError(
            409, ERR_INVALID_STATE, "Spoilage can only be reported on a delivered stop."
        )
    credit_cents = _compute_credit_cents(item, credit_qty_kg, pricing_variant)
    rec = new_resource(
        {
            "delivery_stop_id": delivery_stop_id,
            "order_item_id": order_item_id,
            "credit_qty_kg": q3(credit_qty_kg),
            "pricing_variant": pricing_variant,
            "credit_cents": credit_cents,
            "status": "PENDING",
        }
    )
    db.spoilage_credits[rec["id"]] = rec
    return success(serialize(rec), "object", 201)


@bp.get("/spoilage-credits")
@require_roles(*ALL)
def list_credits():
    delivery_stop_id = request.args.get("delivery_stop_id")
    order_item_id = request.args.get("order_item_id")
    status = request.args.get("status")
    records = list(db.spoilage_credits.values())
    if delivery_stop_id is not None:
        records = [r for r in records if r["delivery_stop_id"] == delivery_stop_id]
    if order_item_id is not None:
        records = [r for r in records if r["order_item_id"] == order_item_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    return list_response(records)


@bp.get("/spoilage-credits/<cid>")
@require_roles(*ALL)
def get_credit(cid):
    rec = db.spoilage_credits.get(cid)
    if rec is None:
        raise ApiError(404, ERR_CREDIT_NOT_FOUND, "spoilage credit id does not exist.")
    return success(serialize(rec), "object", 200)


@bp.post("/spoilage-credits/<cid>/approve")
@require_roles("OpsManager")
def approve_credit(cid):
    rec = db.spoilage_credits.get(cid)
    if rec is None:
        raise ApiError(404, ERR_CREDIT_NOT_FOUND, "spoilage credit id does not exist.")
    if rec["status"] != "PENDING":
        raise ApiError(409, ERR_INVALID_STATE, "Credit is not PENDING.")
    item = db.order_items.get(rec["order_item_id"])
    delivered = Decimal("0")
    if item is not None and item["fulfillment"] in ("DELIVERED", "CREDITED"):
        delivered = Decimal(str(item["qty_kg"]))
    if Decimal(str(rec["credit_qty_kg"])) > delivered:
        raise ApiError(
            422,
            ERR_CREDIT_EXCEEDS_DELIVERY,
            "credit_qty_kg exceeds delivered quantity of the order item.",
        )
    rec["status"] = "APPROVED"
    touch(rec)
    stop = db.delivery_stops.get(rec["delivery_stop_id"])
    customer = (
        db.customers.get(stop["customer_id"]) if stop is not None else None
    )
    if customer is not None:
        customer["credit_balance_cents"] += rec["credit_cents"]
        touch(customer)
    # Full-quantity credit flips the line to CREDITED.
    if (
        item is not None
        and delivered > 0
        and Decimal(str(rec["credit_qty_kg"])) == delivered
        and item["fulfillment"] == "DELIVERED"
    ):
        item["fulfillment"] = "CREDITED"
        touch(item)
    return success(serialize(rec), "object", 200)


@bp.post("/spoilage-credits/<cid>/reject")
@require_roles("OpsManager")
def reject_credit(cid):
    rec = db.spoilage_credits.get(cid)
    if rec is None:
        raise ApiError(404, ERR_CREDIT_NOT_FOUND, "spoilage credit id does not exist.")
    if rec["status"] != "PENDING":
        raise ApiError(409, ERR_INVALID_STATE, "Credit is not PENDING.")
    rec["status"] = "REJECTED"
    touch(rec)
    return success(serialize(rec), "object", 200)
