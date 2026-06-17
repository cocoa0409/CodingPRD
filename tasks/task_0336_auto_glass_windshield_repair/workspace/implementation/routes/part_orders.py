"""PartOrder: reserve/backorder a glass part (OCC-guarded), receive, list (PRD 3.4)."""
from flask import Blueprint, request

import db
import errors
import response
import validation as V
from errors import ApiError
from middleware import require_roles
from services import helpers as H

bp = Blueprint("part_orders", __name__)


@bp.route("/part-orders", methods=["POST"])
@require_roles("ServiceAdvisor")
def create_part_order():
    body = V.get_json()
    work_order_id = V.require_str(body, "work_order_id")
    glass_part_id = V.require_str(body, "glass_part_id")
    # Existence: work order then glass part (FK order).
    wo = H.get_work_order(work_order_id)
    part = H.get_glass_part(glass_part_id)

    quantity = V.opt_int(body, "quantity", 1)
    expected_version = V.require_int(body, "expected_work_order_version")
    if quantity < 1:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "quantity must be >= 1.")

    # OCC check (priority 6, before business safety priority 7).
    if expected_version != wo["version"]:
        raise ApiError(errors.ERR_STALE_WORK_ORDER_VERSION, 412,
                       "expected_work_order_version does not match.")

    # ADAS compatibility (priority 7): an ADAS vehicle needs an adas_compatible part.
    vehicle = db.vehicles[wo["vehicle_id"]]
    if vehicle["adas_equipped"] and not part["adas_compatible"]:
        raise ApiError(errors.ERR_ADAS_PART_INCOMPATIBLE, 422,
                       "ADAS vehicle requires an adas_compatible glass part.")

    po = db.stamp_new({
        "work_order_id": work_order_id,
        "glass_part_id": glass_part_id,
        "quantity": quantity,
        "status": "PENDING",
        "expected_work_order_version": expected_version,
    })

    if part["on_hand_qty"] >= quantity:
        # PENDING -> RESERVED: move stock, bump work order version.
        part["on_hand_qty"] -= quantity
        part["reserved_qty"] += quantity
        db.touch(part)
        po["status"] = "RESERVED"
        db.touch(wo)
    else:
        # PENDING -> BACKORDERED: no stock movement, no work order version bump.
        po["status"] = "BACKORDERED"

    db.part_orders[po["id"]] = po
    return response.success(H.view(po), 201)


@bp.route("/part-orders/<pid>", methods=["GET"])
@require_roles("ServiceAdvisor", "ShopManager")
def get_part_order(pid):
    return response.success(H.view(H.get_part_order(pid)))


@bp.route("/part-orders", methods=["GET"])
@require_roles("ServiceAdvisor", "ShopManager")
def list_part_orders():
    limit, offset = V.parse_pagination()
    glass_part_id = request.args.get("glass_part_id")
    work_order_id = request.args.get("work_order_id")
    items = list(db.part_orders.values())
    if glass_part_id is not None:
        items = [p for p in items if p["glass_part_id"] == glass_part_id]
    if work_order_id is not None:
        items = [p for p in items if p["work_order_id"] == work_order_id]
    items = db.sort_by_created(items)
    total = len(items)
    page = items[offset:offset + limit]
    return response.paginated(H.view_list(page), limit, offset, total)


@bp.route("/part-orders/<pid>/receive", methods=["POST"])
@require_roles("ShopManager")
def receive_part_order(pid):
    po = H.get_part_order(pid)
    if po["status"] != "BACKORDERED":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Part order is not BACKORDERED.")
    # BACKORDERED -> RESERVED: arriving stock lands directly in reservation.
    part = db.glass_parts[po["glass_part_id"]]
    part["reserved_qty"] += po["quantity"]
    db.touch(part)
    po["status"] = "RESERVED"
    db.touch(po)
    # Bump the parent work order version.
    wo = db.work_orders.get(po["work_order_id"])
    if wo is not None:
        db.touch(wo)
    return response.success(H.view(po))
