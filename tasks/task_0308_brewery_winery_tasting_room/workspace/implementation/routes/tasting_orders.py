"""TastingOrder routes (PRD §3.9). POS order with per-line-rounded totals."""
from flask import Blueprint, request

import constants as C
import calculations as calc
from db import db, common_fields, touch
from errors import (
    err, ERR_INVALID_STATE, ERR_INVALID_REQUEST, ERR_FK_NOT_FOUND,
    ERR_INSUFFICIENT_INVENTORY, ERR_AGE_RESTRICTION, ERR_INSUFFICIENT_POINTS,
)
from middleware import authenticate, authorize
from response import success
from serialize import public
from domain import recompute_winery_loyalty_liability, is_of_age
from validate import (
    get_json_body, require_str, require_positive_int, require_enum,
    opt_bool, opt_int, get_or_404, resolve_winery_fk, resolve_fk,
)
from pagination import paginate, sorted_by_creation

bp = Blueprint("tasting_orders", __name__)


def _attached_membership(order):
    """The membership used for tier discount / loyalty: the first membership of
    the attached member (if any). PRD attaches a Member; loyalty/tier come from
    that member's membership."""
    member_id = order.get("member_id")
    if not member_id:
        return None
    candidates = [m for m in db.memberships.values() if m["member_id"] == member_id]
    if not candidates:
        return None
    candidates.sort(key=lambda m: m.get("_seq", 0))
    return candidates[0]


def _validate_lines(line_items, winery_id):
    """Validate and normalize line items; resolve each product (FK-scoped)."""
    if not isinstance(line_items, list) or len(line_items) == 0:
        raise err(ERR_INVALID_REQUEST, "line_items must be a non-empty array")
    resolved = []
    for raw in line_items:
        if not isinstance(raw, dict):
            raise err(ERR_INVALID_REQUEST, "Each line item must be an object")
        product_id = raw.get("product_id")
        if not isinstance(product_id, str) or not product_id:
            raise err(ERR_INVALID_REQUEST, "line item product_id is required")
        kind = raw.get("kind")
        if kind not in C.LINE_KINDS:
            raise err(ERR_INVALID_REQUEST, "line item kind must be FLIGHT, BOTTLE, or GLASS")
        quantity = raw.get("quantity")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
            raise err(ERR_INVALID_REQUEST, "line item quantity must be a positive integer")
        unit_price = raw.get("unit_price_cents")
        if unit_price is not None and (isinstance(unit_price, bool) or not isinstance(unit_price, int)):
            raise err(ERR_INVALID_REQUEST, "line item unit_price_cents must be an integer")
        # FK-resolve product within the winery
        product = resolve_fk(db.products, product_id, winery_id)
        resolved.append({
            "product_id": product_id,
            "kind": kind,
            "quantity": quantity,
            "unit_price_cents": unit_price if unit_price is not None else product["list_price_cents"],
            "_product": product,
            "_raw_unit_price": unit_price,
        })
    return resolved


def _compute_totals(order, lines):
    membership = _attached_membership(order)
    tier = membership["tier"] if membership else None
    subtotal, member_discount, redeemed, total, _ = calc.pos_order_total(
        lines, tier, order.get("redeem_points", 0)
    )
    order["subtotal_cents"] = subtotal
    order["member_discount_cents"] = member_discount
    order["loyalty_redeemed_cents"] = redeemed
    order["total_cents"] = total


@bp.route("/tasting-orders", methods=["POST"])
def create_order():
    _, role = authenticate()
    authorize(role, ["TastingRoomStaff"])
    body = get_json_body()
    winery_id = require_str(body, "winery_id")
    line_items = body.get("line_items")
    member_id = body.get("member_id")
    guest_age_verified = opt_bool(body, "guest_age_verified", False)
    redeem_points = opt_int(body, "redeem_points", 0)
    if redeem_points < 0:
        raise err(ERR_INVALID_REQUEST, "redeem_points must not be negative")
    with db.lock:
        resolve_winery_fk(winery_id)
        if member_id is not None:
            if not isinstance(member_id, str):
                raise err(ERR_INVALID_REQUEST, "member_id must be a string")
            resolve_fk(db.members, member_id, winery_id)
        lines = _validate_lines(line_items, winery_id)

        o = common_fields()
        o.update({
            "winery_id": winery_id,
            "member_id": member_id,
            "line_items": [
                {k: v for k, v in ln.items() if not k.startswith("_")} for ln in lines
            ],
            "guest_age_verified": guest_age_verified,
            "subtotal_cents": 0,
            "member_discount_cents": 0,
            "loyalty_redeemed_cents": 0,
            "total_cents": 0,
            "loyalty_points_earned": 0,
            "redeem_points": redeem_points,
            "status": "OPEN",
        })
        _compute_totals(o, lines)
        db.tasting_orders[o["id"]] = o
        return success(public(o), status=201)


@bp.route("/tasting-orders", methods=["GET"])
def list_orders():
    _, role = authenticate()
    authorize(role, ["TastingRoomStaff", "ComplianceOfficer"])
    with db.lock:
        items = list(db.tasting_orders.values())
        winery_id = request.args.get("winery_id")
        member_id = request.args.get("member_id")
        status = request.args.get("status")
        if winery_id is not None:
            items = [o for o in items if o["winery_id"] == winery_id]
        if member_id is not None:
            items = [o for o in items if o.get("member_id") == member_id]
        if status is not None:
            items = [o for o in items if o["status"] == status]
        items = sorted_by_creation(items)
        page, pg = paginate(items)
        return success([public(o) for o in page], pagination=pg)


@bp.route("/tasting-orders/<order_id>", methods=["GET"])
def get_order(order_id):
    _, role = authenticate()
    authorize(role, ["TastingRoomStaff"])
    with db.lock:
        o = get_or_404(db.tasting_orders, order_id)
        return success(public(o))


def _rebuild_lines(order):
    """Re-attach product references to the stored line items."""
    lines = []
    for ln in order["line_items"]:
        product = db.products.get(ln["product_id"])
        lines.append({
            "product_id": ln["product_id"],
            "kind": ln["kind"],
            "quantity": ln["quantity"],
            "unit_price_cents": ln["unit_price_cents"],
            "_product": product,
        })
    return lines


@bp.route("/tasting-orders/<order_id>/transitions", methods=["POST"])
def transition_order(order_id):
    _, role = authenticate()
    authorize(role, ["TastingRoomStaff"])
    with db.lock:
        o = get_or_404(db.tasting_orders, order_id)
        body = get_json_body()
        action = require_enum(body, "action", {"PAY", "VOID", "REFUND"})

        if action == "PAY":
            return _do_pay(o)
        elif action == "VOID":
            if o["status"] != "OPEN":
                raise err(ERR_INVALID_STATE, "Order is not OPEN")
            o["status"] = "VOID"
            touch(o)
            return success(public(o))
        else:  # REFUND
            return _do_refund(o)


def _do_pay(o):
    if o["status"] != "OPEN":
        raise err(ERR_INVALID_STATE, "Order is not OPEN")
    lines = _rebuild_lines(o)
    membership = _attached_membership(o)

    # age gate (priority 8): any age-restricted line requires verification or member age
    any_age_restricted = any(ln["_product"] and ln["_product"]["is_age_restricted"] for ln in lines)
    if any_age_restricted:
        member_ok = False
        if o.get("member_id"):
            member = db.members.get(o["member_id"])
            if member is not None and is_of_age(member["date_of_birth"]):
                member_ok = True
        if not (o["guest_age_verified"] or member_ok):
            raise err(ERR_AGE_RESTRICTION, "Age verification required for age-restricted lines")

    # inventory sufficiency (priority 15): each BOTTLE line product ACTIVE + free >= qty
    for ln in lines:
        if ln["kind"] == "BOTTLE":
            product = ln["_product"]
            if product is None or product["status"] != "ACTIVE":
                raise err(ERR_INSUFFICIENT_INVENTORY, "BOTTLE line product is not ACTIVE")
            if product["free_bottles"] < ln["quantity"]:
                raise err(ERR_INSUFFICIENT_INVENTORY, "Insufficient free inventory for BOTTLE line")

    # loyalty sufficiency (priority 16): redeem_points <= membership.loyalty_points
    redeem_points = o.get("redeem_points", 0)
    if redeem_points > 0:
        if membership is None or redeem_points > membership["loyalty_points"]:
            raise err(ERR_INSUFFICIENT_POINTS, "redeem_points exceeds available loyalty points")

    # side effects: remove BOTTLE inventory
    for ln in lines:
        if ln["kind"] == "BOTTLE":
            product = ln["_product"]
            product["on_hand_bottles"] = product["on_hand_bottles"] - ln["quantity"]
            product["free_bottles"] = product["on_hand_bottles"] - product["allocated_bottles"]
            touch(product)

    # loyalty mint + redeem
    if membership is not None:
        earned = calc.loyalty_earned(o["total_cents"], membership["tier"])
        o["loyalty_points_earned"] = earned
        membership["loyalty_points"] = membership["loyalty_points"] + earned
        if o["loyalty_redeemed_cents"] > 0:
            consumed = calc.points_consumed(o["loyalty_redeemed_cents"])
            membership["loyalty_points"] = membership["loyalty_points"] - consumed
        touch(membership)
        winery = db.wineries.get(o["winery_id"])
        recompute_winery_loyalty_liability(winery)
        touch(winery)

    o["status"] = "PAID"
    touch(o)
    return success(public(o))


def _do_refund(o):
    if o["status"] != "PAID":
        raise err(ERR_INVALID_STATE, "Order is not PAID")
    lines = _rebuild_lines(o)
    membership = _attached_membership(o)

    # restore BOTTLE inventory
    for ln in lines:
        if ln["kind"] == "BOTTLE":
            product = ln["_product"]
            if product is not None:
                product["on_hand_bottles"] = product["on_hand_bottles"] + ln["quantity"]
                product["free_bottles"] = product["on_hand_bottles"] - product["allocated_bottles"]
                touch(product)

    # reverse loyalty: earned off, redeemed restored
    if membership is not None:
        membership["loyalty_points"] = membership["loyalty_points"] - o["loyalty_points_earned"]
        if o["loyalty_redeemed_cents"] > 0:
            consumed = calc.points_consumed(o["loyalty_redeemed_cents"])
            membership["loyalty_points"] = membership["loyalty_points"] + consumed
        touch(membership)
        winery = db.wineries.get(o["winery_id"])
        recompute_winery_loyalty_liability(winery)
        touch(winery)

    o["status"] = "REFUNDED"
    touch(o)
    return success(public(o))
