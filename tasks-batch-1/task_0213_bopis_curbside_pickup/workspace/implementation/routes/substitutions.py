"""Substitution endpoints (propose / accept / decline / withdraw)."""

from flask import Blueprint, request

from db import db, stamp_common, touch
from errors import err
from middleware import require_auth, get_json_body
from response import object_response, array_response
from services.common import (
    require_str, require_pos_int, ref_or_404, get_or_404,
    parse_pagination, paginate, ser_substitution,
)
from services import inventory as inv_svc
from services import money

bp = Blueprint("substitutions", __name__)


def _owning_order(sub):
    line = db.order_lines.get(sub["order_line_id"])
    if line is None:
        return None
    return db.orders.get(line["order_id"])


def _check_sub_owner(role, user_id, sub):
    if role == "Customer":
        order = _owning_order(sub)
        if order is None or order["customer_id"] != user_id:
            raise err("ERR_NOT_RESOURCE_OWNER",
                      "customer does not own the substitution's order")


@bp.post("/substitutions")
def propose():
    require_auth({"StorePicker"})
    body = get_json_body()
    order_line_id = require_str(body, "order_line_id")
    substitute_product_id = require_str(body, "substitute_product_id")
    substitute_qty = require_pos_int(body, "substitute_qty")
    # FK existence (priority 5)
    line = ref_or_404(db.order_lines, order_line_id, "order_line")
    sub_prod = ref_or_404(db.products, substitute_product_id, "product")

    # state guard (priority 8): line must be SHORT_PICKED
    if line["line_status"] != "SHORT_PICKED":
        raise err("ERR_INVALID_STATE", "line is not SHORT_PICKED")

    # substitution-group match (priority 11)
    orig_prod = db.products.get(line["product_id"])
    orig_group = orig_prod["substitution_group"] if orig_prod else None
    if orig_group is None or sub_prod["substitution_group"] != orig_group:
        raise err("ERR_SUBSTITUTION_GROUP_MISMATCH",
                  "substitute product does not share the original substitution group")

    rec = {
        "order_line_id": order_line_id,
        "substitute_product_id": substitute_product_id,
        "substitute_qty": substitute_qty,
        "decision_status": "PROPOSED",
        "price_delta_cents": 0,
    }
    stamp_common(rec)
    db.substitutions[rec["id"]] = rec
    line["line_status"] = "SUBSTITUTION_PROPOSED"
    touch(line)
    return object_response(ser_substitution(rec), 201)


@bp.get("/substitutions")
def list_subs():
    require_auth({"StorePicker", "StoreManager", "PlatformAdmin"})
    limit, offset = parse_pagination(request.args)
    items = list(db.substitutions.values())
    for key in ("substitute_product_id", "order_line_id"):
        val = request.args.get(key)
        if val is not None:
            items = [s for s in items if s.get(key) == val]
    page, total = paginate(items, limit, offset)
    return array_response([ser_substitution(s) for s in page], limit, offset, total)


@bp.get("/substitutions/<sid>")
def get_sub(sid):
    require_auth({"Customer", "StorePicker", "StoreManager", "PlatformAdmin"})
    rec = get_or_404(db.substitutions, sid)
    return object_response(ser_substitution(rec))


@bp.post("/substitutions/<sid>/accept")
def accept_sub(sid):
    user_id, role = require_auth({"Customer"})
    sub = get_or_404(db.substitutions, sid)
    _check_sub_owner(role, user_id, sub)
    # state guard (priority 8)
    if sub["decision_status"] != "PROPOSED":
        raise err("ERR_INVALID_STATE", "substitution is not PROPOSED")
    line = db.order_lines.get(sub["order_line_id"])
    order = _owning_order(sub)

    # availability of the substitute (priority 22)
    inv = inv_svc.find_inventory(order["store_id"], sub["substitute_product_id"])
    avail = inv["available"] if inv is not None else 0
    if inv is None or avail < sub["substitute_qty"]:
        raise err("ERR_INSUFFICIENT_AVAILABILITY",
                  "insufficient availability for the substitute")

    # --- commit ---
    delta = money.substitution_price_delta(sub)
    sub["decision_status"] = "ACCEPTED"
    sub["price_delta_cents"] = delta
    reason = "ORDER:%s" % order["id"]
    inv_svc.reserve(inv, sub["substitute_qty"], reason)
    line["line_status"] = "SUBSTITUTED"
    # PRD §3.5: "its already-picked units plus the substitute units are treated
    # as picked for staging" — the substitute units count toward the line's
    # effective picked quantity, which governs the §3.6 hand-over ceiling.
    line["qty_picked"] = line["qty_picked"] + sub["substitute_qty"]
    touch(line)
    order["authorized_total_cents"] += delta
    touch(order)
    touch(sub)
    return object_response(ser_substitution(sub))


@bp.post("/substitutions/<sid>/decline")
def decline_sub(sid):
    user_id, role = require_auth({"Customer"})
    sub = get_or_404(db.substitutions, sid)
    _check_sub_owner(role, user_id, sub)
    if sub["decision_status"] != "PROPOSED":
        raise err("ERR_INVALID_STATE", "substitution is not PROPOSED")
    sub["decision_status"] = "DECLINED"
    line = db.order_lines.get(sub["order_line_id"])
    if line is not None:
        line["line_status"] = "SHORT_PICKED"
        touch(line)
    touch(sub)
    return object_response(ser_substitution(sub))


@bp.post("/substitutions/<sid>/withdraw")
def withdraw_sub(sid):
    require_auth({"StorePicker"})
    sub = get_or_404(db.substitutions, sid)
    if sub["decision_status"] != "PROPOSED":
        raise err("ERR_INVALID_STATE", "substitution is not PROPOSED")
    sub["decision_status"] = "WITHDRAWN"
    line = db.order_lines.get(sub["order_line_id"])
    if line is not None:
        line["line_status"] = "SHORT_PICKED"
        touch(line)
    touch(sub)
    return object_response(ser_substitution(sub))
