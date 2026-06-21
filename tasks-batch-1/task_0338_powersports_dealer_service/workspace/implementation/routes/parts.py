"""Parts inventory and part-line reservations (PRD 3.9) with OCC + conservation."""

from flask import Blueprint, request

import errors
from common import get_body, stamp_new, serialize, touch, paginate, as_int, as_str
from db import db
from lookups import get_part, get_part_line, get_repair_order
from middleware import get_user_context, require_role
from response import ok, ok_list

bp = Blueprint("parts", __name__)


# ---------------------------------------------------------------------------
# Parts
# ---------------------------------------------------------------------------
@bp.route("/parts", methods=["POST"])
def create_part():
    _, role = get_user_context()
    require_role(role, {"PartsClerk", "DealerPrincipal"})
    body = get_body()
    sku = as_str(body, "sku", non_empty=True)
    description = as_str(body, "description")
    unit_price = as_int(body, "unit_price_cents", minimum=0)
    on_hand = as_int(body, "on_hand_qty", minimum=0)

    for p in db.parts.values():
        if p["sku"] == sku:
            errors.err(errors.ERR_DUPLICATE_RESOURCE, "SKU already exists")

    rec = stamp_new({
        "sku": sku,
        "description": description,
        "unit_price_cents": unit_price,
        "on_hand_qty": on_hand,
        "reserved_qty": 0,
        "consumed_qty": 0,
        "available_qty": on_hand,
    })
    db.parts[rec["id"]] = rec
    return ok(serialize(rec), 201)


@bp.route("/parts", methods=["GET"])
def list_parts():
    _, role = get_user_context()
    require_role(role, {"PartsClerk", "ServiceAdvisor", "DealerPrincipal"})
    sku = request.args.get("sku")
    records = [p for p in db.parts.values() if sku is None or p["sku"] == sku]
    items, limit, offset, total = paginate(records)
    return ok_list(items, limit, offset, total)


@bp.route("/parts/<pid>", methods=["GET"])
def get_part_route(pid):
    _, role = get_user_context()
    require_role(role, {"PartsClerk", "ServiceAdvisor", "DealerPrincipal"})
    rec = get_part(pid)
    return ok(serialize(rec), 200)


@bp.route("/parts/<pid>/restock", methods=["POST"])
def restock_part(pid):
    _, role = get_user_context()
    require_role(role, {"PartsClerk", "DealerPrincipal"})
    part = get_part(pid)
    body = get_body()
    add_qty = as_int(body, "add_qty")
    if add_qty <= 0:
        errors.err(errors.ERR_INVALID_REQUEST, "add_qty must be > 0")
    part["on_hand_qty"] += add_qty
    part["available_qty"] += add_qty
    touch(part)
    return ok(serialize(part), 200)


# ---------------------------------------------------------------------------
# Part lines
# ---------------------------------------------------------------------------
@bp.route("/part-lines", methods=["POST"])
def create_part_line():
    _, role = get_user_context()
    require_role(role, {"PartsClerk", "ServiceAdvisor"})
    body = get_body()
    # existence in declared order: repair_order_id, part_id
    repair_order_id = as_str(body, "repair_order_id")
    get_repair_order(repair_order_id)
    part_id = as_str(body, "part_id")
    part = get_part(part_id)

    # body validation
    quantity = as_int(body, "quantity")
    if quantity <= 0:
        errors.err(errors.ERR_INVALID_REQUEST, "quantity must be > 0")
    expected_version = as_int(body, "expected_part_version")

    # OCC (412)
    if expected_version != part["version"]:
        errors.err(errors.ERR_STALE_PART_VERSION, "Part version is stale")

    # stock (409)
    if quantity > part["available_qty"]:
        errors.err(errors.ERR_PART_INSUFFICIENT_STOCK, "Requested quantity exceeds available stock")

    extended = quantity * part["unit_price_cents"]
    rec = stamp_new({
        "repair_order_id": repair_order_id,
        "part_id": part_id,
        "quantity": quantity,
        "extended_cents": extended,
        "status": "RESERVED",
    }, common=False)
    db.part_lines[rec["id"]] = rec

    part["reserved_qty"] += quantity
    part["available_qty"] -= quantity
    touch(part)
    return ok(serialize(rec), 201)


@bp.route("/part-lines", methods=["GET"])
def list_part_lines():
    _, role = get_user_context()
    require_role(role, {"PartsClerk", "ServiceAdvisor", "DealerPrincipal"})
    repair_order_id = request.args.get("repair_order_id")
    part_id = request.args.get("part_id")
    records = []
    for pl in db.part_lines.values():
        if repair_order_id is not None and pl["repair_order_id"] != repair_order_id:
            continue
        if part_id is not None and pl["part_id"] != part_id:
            continue
        records.append(pl)
    items, limit, offset, total = paginate(records)
    return ok_list(items, limit, offset, total)


@bp.route("/part-lines/<plid>", methods=["GET"])
def get_part_line_route(plid):
    _, role = get_user_context()
    require_role(role, {"PartsClerk", "ServiceAdvisor", "DealerPrincipal"})
    rec = get_part_line(plid)
    return ok(serialize(rec), 200)


@bp.route("/part-lines/<plid>", methods=["DELETE"])
def release_part_line(plid):
    _, role = get_user_context()
    require_role(role, {"PartsClerk", "ServiceAdvisor"})
    pl = get_part_line(plid)
    if pl["status"] != "RESERVED":
        errors.err(errors.ERR_INVALID_STATE, "Part line is not RESERVED")
    ro = db.repair_orders.get(pl["repair_order_id"])
    if ro is not None and ro["billing_status"] != "UNBILLED":
        errors.err(errors.ERR_RO_ALREADY_BILLED, "Repair order is already billed")
    part = db.parts.get(pl["part_id"])
    if part is not None:
        part["reserved_qty"] -= pl["quantity"]
        part["available_qty"] += pl["quantity"]
        touch(part)
    pl["status"] = "RELEASED"
    return ok(serialize(pl), 200)
