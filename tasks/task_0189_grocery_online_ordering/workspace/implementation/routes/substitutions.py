"""Substitution endpoints + accept/reject state machine (PRD §3.3)."""
from flask import Blueprint, request

import db
import calculations as calc
import lookups
from errors import (
    err,
    ERR_SUBSTITUTION_NOT_FOUND, ERR_LINE_NOT_FOUND, ERR_PRODUCT_NOT_FOUND,
    ERR_PRODUCT_DISCONTINUED, ERR_CROSS_STORE_REFERENCE, ERR_VALIDATION,
    ERR_SUBSTITUTION_NOT_PROPOSED, ERR_LINE_NOT_PENDING, ERR_ORDER_NOT_PICKING,
    ERR_SUBSTITUTION_NOT_ALLOWED, ERR_SUBSTITUTION_PRICE_EXCEEDED,
    ERR_FORBIDDEN_ROLE,
)
from middleware import get_user_context, require_role
import validate as V
from response import object_response, array_response
from serialize import public, public_list
from pagination import get_pagination, paginate

bp = Blueprint("substitutions", __name__)


# ---------------------------------------------------------------------------
# Propose
# ---------------------------------------------------------------------------
@bp.route("/v1/substitutions", methods=["POST"])
def propose_substitution():
    user_id, role = get_user_context()
    require_role(role, {"Picker"})  # PRD §4: Picker only
    body = V.get_body()
    order_line_id = V.require_str(body, "order_line_id")
    substitute_product_id = V.require_str(body, "substitute_product_id")
    substitute_qty = V.require_number(body, "substitute_qty", positive=True)
    substitute_weight = V.opt_number(body, "substitute_weight_kg", None, positive=True)
    with db.lock:
        line = db.order_lines.get(order_line_id)
        if line is None:
            err(ERR_LINE_NOT_FOUND, "Order line not found")
        sub_product = db.products.get(substitute_product_id)
        if sub_product is None:
            err(ERR_PRODUCT_NOT_FOUND, "Substitute product not found")
        order = db.orders.get(line["order_id"])
        # cross-store: substitute product must belong to the order's store
        if sub_product["store_id"] != order["store_id"]:
            err(ERR_CROSS_STORE_REFERENCE, "Substitute product belongs to a different store")
        # DISCONTINUED product cannot be proposed as a substitute (PRD §3.1/§3.3)
        if sub_product["status"] == "DISCONTINUED":
            err(ERR_PRODUCT_DISCONTINUED, "Substitute product is DISCONTINUED")
        if sub_product["pricing_mode"] == "WEIGHT" and substitute_weight is None:
            err(ERR_VALIDATION, "substitute_weight_kg required for WEIGHT substitute")
        # substitute_line_cents via the same per-line rule as final_line_cents
        if sub_product["pricing_mode"] == "UNIT":
            sub_cents = calc.line_charge(sub_product, qty=substitute_qty)
        else:
            sub_cents = calc.line_charge(sub_product, weight_kg=substitute_weight)
        sub = {
            "order_line_id": order_line_id,
            "substitute_product_id": substitute_product_id,
            "substitute_qty": substitute_qty,
            "substitute_weight_kg": substitute_weight,
            "substitute_line_cents": sub_cents,
            "status": "PROPOSED",  # begins PROPOSED
        }
        db.stamp_create(sub)
        db.substitutions[sub["id"]] = sub
        return object_response(public(sub), 201)


@bp.route("/v1/substitutions", methods=["GET"])
def list_substitutions():
    user_id, role = get_user_context()
    require_role(role, {"PlatformAdmin", "StoreOps", "Customer", "Picker"})  # PRD §4
    limit, offset = get_pagination()
    order_line_id = request.args.get("order_line_id")
    substitute_product_id = request.args.get("substitute_product_id")
    with db.lock:
        records = list(db.substitutions.values())
        if order_line_id is not None:
            records = [s for s in records if s["order_line_id"] == order_line_id]
        if substitute_product_id is not None:
            records = [s for s in records if s["substitute_product_id"] == substitute_product_id]
        page, total = paginate(records, limit, offset)
        return array_response(public_list(page), limit, offset, total)


@bp.route("/v1/substitutions/<sub_id>", methods=["GET"])
def get_substitution(sub_id):
    user_id, role = get_user_context()
    require_role(role, {"PlatformAdmin", "StoreOps", "Customer", "Picker"})  # PRD §4
    with db.lock:
        sub = db.substitutions.get(sub_id)
        if sub is None:
            err(ERR_SUBSTITUTION_NOT_FOUND, "Substitution not found")
        return object_response(public(sub))


# ---------------------------------------------------------------------------
# Accept (PROPOSED -> ACCEPTED; line PENDING -> SUBSTITUTED)
# ---------------------------------------------------------------------------
@bp.route("/v1/substitutions/<sub_id>/accept", methods=["POST"])
def accept_substitution(sub_id):
    user_id, role = get_user_context()
    require_role(role, {"Customer", "Picker"})  # PRD §4
    with db.lock:
        sub = db.substitutions.get(sub_id)
        if sub is None:
            err(ERR_SUBSTITUTION_NOT_FOUND, "Substitution not found")
        line = db.order_lines.get(sub["order_line_id"])
        order = db.orders.get(line["order_id"])
        # Customer ownership over their own order
        if role == "Customer" and order["customer_id"] != user_id:
            err(ERR_FORBIDDEN_ROLE, "Customer may only decide substitutions on their own orders")
        # preconditions in PRD §3.3 order:
        # substitution still PROPOSED; line still PENDING; order PICKING;
        # policy != NO_SUBSTITUTION; SAME_PRICE_OR_LESS price ceiling.
        if sub["status"] != "PROPOSED":
            err(ERR_SUBSTITUTION_NOT_PROPOSED, "Substitution is not PROPOSED")
        if line["status"] != "PENDING":
            err(ERR_LINE_NOT_PENDING, "Line is not PENDING")
        if order["fulfillment_status"] != "PICKING":
            err(ERR_ORDER_NOT_PICKING, "Order is not PICKING")
        if line["substitution_policy"] == "NO_SUBSTITUTION":
            err(ERR_SUBSTITUTION_NOT_ALLOWED, "Line does not allow substitution")
        if line["substitution_policy"] == "SAME_PRICE_OR_LESS":
            if sub["substitute_line_cents"] > line["estimated_line_cents"]:
                err(ERR_SUBSTITUTION_PRICE_EXCEEDED, "Substitute exceeds estimated line price")
        # --- commit ---
        sub["status"] = "ACCEPTED"
        db.touch(sub)
        line["status"] = "SUBSTITUTED"
        line["final_line_cents"] = sub["substitute_line_cents"]
        db.touch(line)
        return object_response(public(sub))


# ---------------------------------------------------------------------------
# Reject (PROPOSED -> REJECTED; line untouched)
# ---------------------------------------------------------------------------
@bp.route("/v1/substitutions/<sub_id>/reject", methods=["POST"])
def reject_substitution(sub_id):
    user_id, role = get_user_context()
    require_role(role, {"Customer", "Picker"})  # PRD §4
    with db.lock:
        sub = db.substitutions.get(sub_id)
        if sub is None:
            err(ERR_SUBSTITUTION_NOT_FOUND, "Substitution not found")
        line = db.order_lines.get(sub["order_line_id"])
        order = db.orders.get(line["order_id"])
        if role == "Customer" and order["customer_id"] != user_id:
            err(ERR_FORBIDDEN_ROLE, "Customer may only decide substitutions on their own orders")
        # only requires PROPOSED (PRD §3.3)
        if sub["status"] != "PROPOSED":
            err(ERR_SUBSTITUTION_NOT_PROPOSED, "Substitution is not PROPOSED")
        sub["status"] = "REJECTED"
        db.touch(sub)
        return object_response(public(sub))
