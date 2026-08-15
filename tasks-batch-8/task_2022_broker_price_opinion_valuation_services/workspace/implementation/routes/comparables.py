"""Comparable endpoints (PRD 3.5)."""

from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_ADJUSTMENT_EXCEEDS_CAP,
    ERR_ADJUSTMENT_NONPOSITIVE,
    ERR_COMPARABLE_RADIUS_VIOLATION,
)
from middleware import allowed
from response import success_object, success_list
from serializers import ser_comparable
from routes.orders import get_order_or_404, TERMINAL_STATES
from validation import body, req_int, req_num, req_iso, sort_and_page

bp = Blueprint("comparables", __name__)

ADJUSTMENT_CAP_PCT = Decimal("0.25")


def _get_comparable_or_404(order_id: str, comp_id: str) -> dict:
    comp = db.comparables.get(comp_id)
    if comp is None or comp["order_id"] != order_id:
        raise ApiError(ERR_NOT_FOUND, f"Comparable {comp_id} not found on order {order_id}", 404)
    return comp


def _min_radius_for(order: dict) -> Decimal:
    prop = db.properties.get(order["property_id"])
    reg = db.find_state_regulation_by_code(prop["state_code"]) if prop else None
    if reg is None:
        return Decimal("1.0") if order["inspection_level"] == "DRIVE_BY" else Decimal("0.5")
    if order["inspection_level"] == "DRIVE_BY":
        return Decimal(str(reg["min_driveby_radius_miles"]))
    return Decimal(str(reg["min_interior_radius_miles"]))


def _check_adjustment_cap(sale_price_cents: int, adjustment_cents: int) -> None:
    """Priority 13: |adjustment| <= 25% of sale price; adjusted value > 0."""
    cap = int((ADJUSTMENT_CAP_PCT * Decimal(sale_price_cents)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if abs(adjustment_cents) > cap:
        raise ApiError(
            ERR_ADJUSTMENT_EXCEEDS_CAP,
            f"|adjustment_cents| {abs(adjustment_cents)} exceeds cap {cap} (25% of {sale_price_cents})",
            422,
        )
    if sale_price_cents + adjustment_cents <= 0:
        raise ApiError(ERR_ADJUSTMENT_NONPOSITIVE, "adjusted_value_cents would be <= 0", 422)


def _check_radius(order: dict, distance_miles: Decimal) -> None:
    """Priority 14: distance floor per inspection level."""
    if distance_miles < _min_radius_for(order):
        raise ApiError(
            ERR_COMPARABLE_RADIUS_VIOLATION,
            "distance_miles is below the state minimum radius for the inspection level",
            422,
        )


@bp.post("/bpo/valuation-orders/<order_id>/comparables")
@allowed("Broker", "OperationsManager")
def create_comparable(user_id, role, order_id):
    order = get_order_or_404(order_id)
    b = body()

    # Priority 4: body-referenced source property must exist
    source_property_id = b.get("source_property_id")
    if source_property_id is None or not isinstance(source_property_id, str):
        raise ApiError(ERR_INVALID_REQUEST, "Field 'source_property_id': required string", 400)
    if db.properties.get(source_property_id) is None:
        raise ApiError(ERR_NOT_FOUND, f"Property {source_property_id} not found", 404)

    # Priority 5: order must be non-terminal for field work
    if order["fulfillment_status"] in TERMINAL_STATES:
        raise ApiError(ERR_INVALID_STATE, f"Order is {order['fulfillment_status']} (terminal)", 409)

    # Typed values needed for business checks
    sale_price = b.get("sale_price_cents")
    if not isinstance(sale_price, int) or isinstance(sale_price, bool):
        raise ApiError(ERR_INVALID_REQUEST, "Field 'sale_price_cents': required integer", 400)
    adjustment = b.get("adjustment_cents")
    if not isinstance(adjustment, int) or isinstance(adjustment, bool):
        raise ApiError(ERR_INVALID_REQUEST, "Field 'adjustment_cents': required integer", 400)
    distance = req_num(b, "distance_miles")
    distance = distance.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # Priority 13 then 14
    if sale_price <= 0:
        raise ApiError(ERR_INVALID_REQUEST, "Field 'sale_price_cents' must be > 0", 400)
    _check_adjustment_cap(sale_price, adjustment)
    _check_radius(order, distance)

    # Priority 29: remaining range checks
    if distance < Decimal("0.01") or distance > Decimal("100.00"):
        raise ApiError(ERR_INVALID_REQUEST, "Field 'distance_miles' must be between 0.01 and 100.00", 400)
    sale_date = req_iso(b, "sale_date")

    record = db.stamp_new({
        "id": db.new_id(),
        "order_id": order_id,
        "source_property_id": source_property_id,
        "sale_price_cents": sale_price,
        "sale_date": sale_date,
        "distance_miles": distance,
        "adjustment_cents": adjustment,
        "adjusted_value_cents": sale_price + adjustment,
        "status": "DRAFT",
    })
    db.comparables[record["id"]] = record
    return success_object(ser_comparable(record), 201)


@bp.get("/bpo/valuation-orders/<order_id>/comparables")
@allowed("Broker", "OperationsManager", "QCReviewer", "DispatchCoordinator", "PlatformAdmin")
def list_comparables(user_id, role, order_id):
    get_order_or_404(order_id)
    records = [c for c in db.comparables.values() if c["order_id"] == order_id]
    status = request.args.get("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    items, limit, offset, total = sort_and_page(records, ser_comparable)
    return success_list(items, limit, offset, total)


@bp.post("/bpo/valuation-orders/<order_id>/comparables/<comp_id>/select")
@allowed("Broker")
def select_comparable(user_id, role, order_id, comp_id):
    order = get_order_or_404(order_id)
    comp = _get_comparable_or_404(order_id, comp_id)
    if order["fulfillment_status"] in TERMINAL_STATES:
        raise ApiError(ERR_INVALID_STATE, f"Order is {order['fulfillment_status']} (terminal)", 409)
    if comp["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, f"Comparable is {comp['status']}, expected DRAFT", 409)
    # Revalidate cap and radius at SELECT time
    _check_adjustment_cap(comp["sale_price_cents"], comp["adjustment_cents"])
    _check_radius(order, comp["distance_miles"])
    comp["status"] = "SELECTED"
    db.touch(comp)
    return success_object(ser_comparable(comp))


@bp.post("/bpo/valuation-orders/<order_id>/comparables/<comp_id>/reject")
@allowed("Broker", "QCReviewer")
def reject_comparable(user_id, role, order_id, comp_id):
    order = get_order_or_404(order_id)
    comp = _get_comparable_or_404(order_id, comp_id)
    if order["fulfillment_status"] in TERMINAL_STATES:
        raise ApiError(ERR_INVALID_STATE, f"Order is {order['fulfillment_status']} (terminal)", 409)
    if comp["status"] not in ("DRAFT", "SELECTED"):
        raise ApiError(ERR_INVALID_STATE, f"Comparable is {comp['status']}", 409)
    comp["status"] = "REJECTED"
    db.touch(comp)
    return success_object(ser_comparable(comp))
