"""OrderLine endpoints + line state machine (PRD §3.2, §3.3, §3.4, §3.7)."""
from flask import Blueprint, request

import db
import calculations as calc
import lookups
from errors import (
    err,
    ERR_LINE_NOT_FOUND, ERR_ORDER_NOT_FOUND, ERR_PRODUCT_NOT_FOUND,
    ERR_PRODUCT_DISCONTINUED, ERR_CROSS_STORE_REFERENCE,
    ERR_FORBIDDEN_ROLE, ERR_VALIDATION,
    ERR_INVALID_ORDER_STATE, ERR_LINE_NOT_PENDING, ERR_ORDER_NOT_PICKING,
    ERR_INVALID_PICK_QUANTITY, ERR_LINE_NOT_PICKED, ERR_ORDER_NOT_STAGED,
    ERR_PAYMENT_NOT_CAPTURED,
)
from middleware import get_user_context, require_role
import validate as V
from response import object_response, array_response
from serialize import public, public_list
from pagination import get_pagination, paginate

bp = Blueprint("order_lines", __name__)


def _customer_owns_order(role, user_id, order):
    return not (role == "Customer" and order["customer_id"] != user_id)


# ---------------------------------------------------------------------------
# Add line to a PLACED order (cart edit)
# ---------------------------------------------------------------------------
@bp.route("/v1/order-lines", methods=["POST"])
def add_line():
    user_id, role = get_user_context()
    require_role(role, {"Customer", "StoreOps"})  # PRD §4
    body = V.get_body()
    order_id = V.require_str(body, "order_id")
    product_id = V.require_str(body, "product_id")
    requested_qty = V.require_number(body, "requested_qty", positive=True)
    est_weight = V.opt_number(body, "estimated_weight_kg", None, positive=True)
    sub_policy = V.opt_enum(
        body, "substitution_policy",
        {"NO_SUBSTITUTION", "SAME_PRICE_OR_LESS", "SHOPPER_CHOICE"},
        "NO_SUBSTITUTION",
    )
    with db.lock:
        order = db.orders.get(order_id)
        if order is None:
            err(ERR_ORDER_NOT_FOUND, "Order not found")
        if not _customer_owns_order(role, user_id, order):
            err(ERR_FORBIDDEN_ROLE, "Customer may only edit their own orders")
        product = db.products.get(product_id)
        if product is None:
            err(ERR_PRODUCT_NOT_FOUND, "Product not found")
        if product["store_id"] != order["store_id"]:
            err(ERR_CROSS_STORE_REFERENCE, "Product belongs to a different store")
        if product["status"] == "DISCONTINUED":
            err(ERR_PRODUCT_DISCONTINUED, "Product is DISCONTINUED")
        # cart edit allowed only while PLACED, before claim (PRD §3.2)
        if order["fulfillment_status"] != "PLACED":
            err(ERR_INVALID_ORDER_STATE, "Order is not PLACED")
        if product["pricing_mode"] == "WEIGHT" and est_weight is None:
            err(ERR_VALIDATION, "estimated_weight_kg required for WEIGHT product")
        if product["pricing_mode"] == "UNIT":
            est = calc.line_charge(product, qty=requested_qty)
        else:
            est = calc.line_charge(product, weight_kg=est_weight)
        line = {
            "order_id": order_id,
            "product_id": product_id,
            "requested_qty": requested_qty,
            "estimated_weight_kg": est_weight,
            "picked_qty": None,
            "actual_weight_kg": None,
            "substitution_policy": sub_policy,
            "estimated_line_cents": est,
            "final_line_cents": 0,
            "status": "PENDING",
        }
        db.stamp_create(line)
        db.order_lines[line["id"]] = line
        # recompute order estimated totals (PRD §2.5/§3.2)
        lookups.recompute_estimated_totals(order)
        db.touch(order)
        return object_response(public(line), 201)


@bp.route("/v1/order-lines", methods=["GET"])
def list_lines():
    user_id, role = get_user_context()
    require_role(role, {"PlatformAdmin", "StoreOps", "Customer", "Picker"})  # PRD §4
    limit, offset = get_pagination()
    order_id = request.args.get("order_id")
    product_id = request.args.get("product_id")
    with db.lock:
        records = list(db.order_lines.values())
        if order_id is not None:
            records = [l for l in records if l["order_id"] == order_id]
        if product_id is not None:
            records = [l for l in records if l["product_id"] == product_id]
        if role == "Customer":
            owned = {o["id"] for o in db.orders.values() if o["customer_id"] == user_id}
            records = [l for l in records if l["order_id"] in owned]
        page, total = paginate(records, limit, offset)
        return array_response(public_list(page), limit, offset, total)


@bp.route("/v1/order-lines/<line_id>", methods=["GET"])
def get_line(line_id):
    user_id, role = get_user_context()
    require_role(role, {"PlatformAdmin", "StoreOps", "Customer", "Picker"})  # PRD §4
    with db.lock:
        line = db.order_lines.get(line_id)
        if line is None:
            err(ERR_LINE_NOT_FOUND, "Order line not found")
        if role == "Customer":
            order = db.orders.get(line["order_id"])
            if order is not None and order["customer_id"] != user_id:
                err(ERR_FORBIDDEN_ROLE, "Customer may only access their own lines")
        return object_response(public(line))


# ---------------------------------------------------------------------------
# Pick (PENDING -> PICKED)
# ---------------------------------------------------------------------------
@bp.route("/v1/order-lines/<line_id>/pick", methods=["POST"])
def pick_line(line_id):
    user_id, role = get_user_context()
    require_role(role, {"Picker"})  # PRD §4: Picker only
    body = V.get_body()
    with db.lock:
        line = db.order_lines.get(line_id)
        if line is None:
            err(ERR_LINE_NOT_FOUND, "Order line not found")
        order = db.orders.get(line["order_id"])
        # state: line PENDING, order PICKING (PRD §3.3)
        if line["status"] != "PENDING":
            err(ERR_LINE_NOT_PENDING, "Line is not PENDING")
        if order["fulfillment_status"] != "PICKING":
            err(ERR_ORDER_NOT_PICKING, "Order is not PICKING")
        product = db.products.get(line["product_id"])
        if product["pricing_mode"] == "UNIT":
            picked_qty = body.get("picked_qty")
            if picked_qty is None or isinstance(picked_qty, bool) \
                    or not isinstance(picked_qty, (int, float)) or not (picked_qty > 0):
                err(ERR_INVALID_PICK_QUANTITY, "picked_qty must be present and > 0 for UNIT")
            line["picked_qty"] = picked_qty
            line["final_line_cents"] = calc.line_charge(product, qty=picked_qty)
        else:  # WEIGHT
            actual = body.get("actual_weight_kg")
            if actual is None or isinstance(actual, bool) \
                    or not isinstance(actual, (int, float)) or not (actual > 0):
                err(ERR_INVALID_PICK_QUANTITY, "actual_weight_kg must be present and > 0 for WEIGHT")
            line["actual_weight_kg"] = actual
            line["final_line_cents"] = calc.line_charge(product, weight_kg=actual)
        line["status"] = "PICKED"
        db.touch(line)
        return object_response(public(line))


# ---------------------------------------------------------------------------
# Out-of-stock: PENDING (pre-capture) OR PICKED (post-capture refund cascade)
# ---------------------------------------------------------------------------
@bp.route("/v1/order-lines/<line_id>/out-of-stock", methods=["POST"])
def out_of_stock(line_id):
    user_id, role = get_user_context()
    require_role(role, {"Picker", "StoreOps"})  # PRD §4
    with db.lock:
        line = db.order_lines.get(line_id)
        if line is None:
            err(ERR_LINE_NOT_FOUND, "Order line not found")
        order = db.orders.get(line["order_id"])

        # Two transitions share this endpoint (SCAFFOLD OrderLine state machine):
        #  - PENDING -> OUT_OF_STOCK (pre-capture): order must be PICKING; no refund.
        #  - PICKED  -> OUT_OF_STOCK (post-capture): order STAGED + payment captured;
        #    refund cascade.
        # A line that is PICKED is treated as the post-capture transition (its
        # state precondition is ERR_LINE_NOT_PICKED via the order-state gate);
        # any other non-PENDING line on a PICKING order fails ERR_LINE_NOT_PENDING.
        if line["status"] == "PICKED":
            # Post-capture refund cascade.
            if order["fulfillment_status"] != "STAGED":
                err(ERR_ORDER_NOT_STAGED, "Order is not STAGED")
            if order["payment_status"] not in ("CAPTURED", "PARTIALLY_REFUNDED"):
                err(ERR_PAYMENT_NOT_CAPTURED, "Payment is not CAPTURED")
            refunded = line["final_line_cents"]  # captured amount, read before zeroing
            line["final_line_cents"] = 0
            line["status"] = "OUT_OF_STOCK"
            db.touch(line)
            # append-only Refund (no common_fields version/updated_at)
            refund = {
                "order_id": order["id"],
                "order_line_id": line["id"],
                "amount_cents": refunded,
                "reason": "OUT_OF_STOCK",
            }
            db.stamp_create(refund, common_fields=False)
            db.refunds[refund["id"]] = refund
            order["refunded_total_cents"] += refunded
            # recompute final_total, net_captured, payment cascade
            lookups.recompute_final_totals(order)
            lookups.recompute_net_captured(order)
            captured_total = order["ebt_charged_cents"] + order["card_charged_cents"]
            if order["refunded_total_cents"] >= captured_total:
                order["payment_status"] = "REFUNDED"
                order["net_captured_cents"] = 0
            elif order["refunded_total_cents"] > 0:
                order["payment_status"] = "PARTIALLY_REFUNDED"
            db.touch(order)
            return object_response(public(line))

        # Pre-capture variant: requires order PICKING then line PENDING.
        if order["fulfillment_status"] != "PICKING":
            # Post-capture intent on a non-PICKED line, or pre-capture on a
            # non-PICKING order. STAGED captured orders expect a PICKED line.
            if order["fulfillment_status"] == "STAGED" and \
                    order["payment_status"] in ("CAPTURED", "PARTIALLY_REFUNDED"):
                err(ERR_LINE_NOT_PICKED, "Line is not PICKED")
            err(ERR_ORDER_NOT_PICKING, "Order is not PICKING")
        if line["status"] != "PENDING":
            err(ERR_LINE_NOT_PENDING, "Line is not PENDING")
        line["status"] = "OUT_OF_STOCK"
        line["final_line_cents"] = 0
        db.touch(line)
        return object_response(public(line))
