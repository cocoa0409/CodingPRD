from flask import Blueprint
from db import db, now_iso
from errors import err
from response import ok
from middleware import authenticate, require_role
from services import serialize
from services.inventory import recompute_components
from services.orders import (
    get_line_or_404, line_has_approved_proof, allocations_for_line, lines_for_order,
)
from services.common import touch

bp = Blueprint("production", __name__)


@bp.route("/order-lines/<line_id>/engrave", methods=["POST"])
def engrave(line_id):
    caller = authenticate()
    require_role(caller, ("ShopStaff",))
    line = get_line_or_404(line_id)
    order = db.orders.get(line["order_id"])

    if line["line_status"] != "ALLOCATED":
        raise err("ERR_INVALID_STATE", "Line must be ALLOCATED to engrave")
    if order["production_status"] != "IN_PRODUCTION":
        raise err("ERR_INVALID_STATE", "Order must be IN_PRODUCTION to engrave a line")
    if not line_has_approved_proof(line_id):
        raise err("ERR_PROOF_NOT_APPROVED", "Line must have an approved proof to engrave")

    line["line_status"] = "ENGRAVING"
    touch(line)
    return ok(serialize.order_line(line))


@bp.route("/order-lines/<line_id>/assemble", methods=["POST"])
def assemble(line_id):
    caller = authenticate()
    require_role(caller, ("ShopStaff",))
    line = get_line_or_404(line_id)
    order = db.orders.get(line["order_id"])

    if line["line_status"] != "ENGRAVING":
        raise err("ERR_INVALID_STATE", "Line must be ENGRAVING to assemble")

    # physical stock check across this line's RESERVED allocations
    allocs = [a for a in allocations_for_line(line_id) if a["alloc_status"] == "RESERVED"]
    for alloc in allocs:
        comp = db.components.get(alloc["component_id"])
        if comp is None or comp["on_hand_qty"] < alloc["qty"]:
            raise err("ERR_COMPONENT_SHORTAGE", "Insufficient physical stock to assemble")

    # consume
    affected = []
    for alloc in allocs:
        comp = db.components[alloc["component_id"]]
        comp["on_hand_qty"] -= alloc["qty"]
        alloc["alloc_status"] = "CONSUMED"
        touch(alloc)
        affected.append(alloc["component_id"])
    recompute_components(affected)

    line["assembled_count"] = line["quantity"]
    line["line_status"] = "ASSEMBLED"
    touch(line)

    # bubble-up: if every line on the order is ASSEMBLED -> order READY
    all_lines = lines_for_order(order["id"])
    if order["production_status"] == "IN_PRODUCTION" and all_lines and \
            all(l["line_status"] == "ASSEMBLED" for l in all_lines):
        order["ready_at"] = now_iso()
        order["production_status"] = "READY"
        touch(order)

    return ok(serialize.order_line(line))
