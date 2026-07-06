"""SupplyKit routes (PRD §3.8)."""
from flask import Blueprint, request

import errors
import helpers
from db import db, stamp_create, touch
from middleware import require
from response import object_response, array_response

bp = Blueprint("supply_kits", __name__)

KIT_TYPES = {"START_OF_CARE", "WEEKLY_RESUPPLY", "FLUSH_ONLY"}
READ_ROLES = ["WarehouseClerk", "Pharmacist", "MedicalDirector"]


@bp.route("/supply-kits", methods=["POST"])
def create_kit():
    require(["WarehouseClerk", "Pharmacist"])
    body = helpers.get_body()
    # existence (3) before other body validity (4) per PRD §2.8
    order_id = helpers.as_str(body, "order_id")
    if order_id not in db.infusion_orders:
        raise errors.not_found("Infusion order not found")
    kit_type = helpers.as_enum(body, "kit_type", KIT_TYPES)
    line_count = helpers.as_int(body, "line_count")
    if line_count < 1:
        raise errors.invalid_request("line_count must be >= 1")

    kit = stamp_create({
        "order_id": order_id,
        "kit_type": kit_type,
        "line_count": line_count,
        "status": "PICKING",
    })
    db.supply_kits[kit["id"]] = kit
    return object_response(kit, 201)


@bp.route("/supply-kits/<id>", methods=["GET"])
def get_kit(id):
    require(READ_ROLES)
    kit = db.supply_kits.get(id)
    if kit is None:
        raise errors.not_found("Supply kit not found")
    return object_response(kit, 200)


@bp.route("/supply-kits", methods=["GET"])
def list_kits():
    require(READ_ROLES)
    limit, offset = helpers.pagination_params()
    items = list(db.supply_kits.values())
    order_id = request.args.get("order_id")
    if order_id is not None:
        items = [k for k in items if k["order_id"] == order_id]
    items = helpers.sort_by_created(items)
    window, total, has_more = helpers.paginate(items, limit, offset)
    return array_response(window, limit, offset, total, has_more, 200)


@bp.route("/supply-kits/<id>/ship", methods=["POST"])
def ship_kit(id):
    require(["WarehouseClerk"])
    kit = db.supply_kits.get(id)
    if kit is None:
        raise errors.not_found("Supply kit not found")
    if kit["status"] != "PICKING":
        raise errors.invalid_state("Kit is not in PICKING state")
    order = db.infusion_orders.get(kit["order_id"])
    if order is None or order["status"] not in ("RELEASED", "ACTIVE"):
        raise errors.invalid_state("Order is not in RELEASED or ACTIVE state")
    kit["status"] = "SHIPPED"
    touch(kit)
    return object_response(kit, 200)
