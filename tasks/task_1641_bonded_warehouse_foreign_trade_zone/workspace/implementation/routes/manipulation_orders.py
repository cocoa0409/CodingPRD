"""ManipulationOrder endpoints (SCAFFOLD 1.5, PRD 3.4)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_ZONE_NOT_FOUND, ERR_LOT_NOT_FOUND,
    ERR_MANIPULATION_ORDER_NOT_FOUND, ERR_ORDER_INVALID_TRANSITION,
    ERR_NOT_RESOURCE_OWNER, ERR_ZONE_NOT_ACTIVE, ERR_ZONE_AUDIT_HOLD,
    ERR_LOT_NOT_IN_ZONE, ERR_MANIPULATION_NOT_PERMITTED, ERR_LOT_BUSY,
    ERR_INSUFFICIENT_QUANTITY, ERR_UNKNOWN_HTS_CODE,
)
from middleware import authorized
from response import success_object, success_list
from serializers import order_view
from services import (
    new_common, touch, recompute_zone_aggregates, create_output_lot,
    HTS_RATE_TABLE,
)
from validate import (
    get_body, reject_unknown_fields, req_str, req_int, require_path,
    require_body_fk, parse_pagination,
)

bp = Blueprint("manipulation_orders", __name__)

ALL_ROLES = ["ZoneOperator", "Importer", "CustomsOfficer", "GateOfficer"]


@bp.route("/zones/manipulation-orders", methods=["POST"])
def create_order():
    caller = authorized(["Importer"])
    body = get_body()
    reject_unknown_fields(body, {"zone_id", "source_lot_id", "input_quantity",
                                 "output_hts_code", "output_quantity",
                                 "value_added_cents", "output_description"})
    zone_id = req_str(body, "zone_id")
    zone = require_body_fk("zones", zone_id, ERR_ZONE_NOT_FOUND, "zone_id")
    source_lot_id = req_str(body, "source_lot_id")
    lot = require_body_fk("lots", source_lot_id, ERR_LOT_NOT_FOUND, "source_lot_id")
    input_quantity = req_int(body, "input_quantity", positive=True)
    output_hts_code = req_str(body, "output_hts_code")  # HTS verified at approval, not creation
    output_quantity = req_int(body, "output_quantity", positive=True)
    value_added = req_int(body, "value_added_cents", non_negative=True)
    output_description = req_str(body, "output_description")

    # Ownership (priority 5): caller must own the source lot.
    if lot["importer_ref"] != caller.user_id:
        raise_error(ERR_NOT_RESOURCE_OWNER, "caller does not own the source lot")

    order = new_common()
    order.update({
        "zone_id": zone["id"],
        "importer_ref": caller.user_id,
        "source_lot_id": lot["id"],
        "input_quantity": input_quantity,
        "output_hts_code": output_hts_code,
        "output_quantity": output_quantity,
        "value_added_cents": value_added,
        "output_description": output_description,
        "output_lot_id": None,
        "status": "REQUESTED",
    })
    db["manipulation_orders"][order["id"]] = order
    return success_object(order_view(order), status=201)


@bp.route("/zones/manipulation-orders", methods=["GET"])
def list_orders():
    authorized(ALL_ROLES)
    limit, offset = parse_pagination()
    zone_id = request.args.get("zone_id")
    source_lot_id = request.args.get("source_lot_id")
    output_lot_id = request.args.get("output_lot_id")
    status = request.args.get("status")
    items = sorted(db["manipulation_orders"].values(), key=lambda o: (o["created_at"], o["id"]))
    if zone_id is not None:
        items = [o for o in items if o["zone_id"] == zone_id]
    if source_lot_id is not None:
        items = [o for o in items if o["source_lot_id"] == source_lot_id]
    if output_lot_id is not None:
        items = [o for o in items if o["output_lot_id"] == output_lot_id]
    if status is not None:
        items = [o for o in items if o["status"] == status]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([order_view(o) for o in page], total, limit, offset)


@bp.route("/zones/manipulation-orders/<orderId>", methods=["GET"])
def get_order(orderId):
    authorized(ALL_ROLES)
    order = require_path("manipulation_orders", orderId, ERR_MANIPULATION_ORDER_NOT_FOUND)
    return success_object(order_view(order))


def _zone_gate_active_and_normal(zone):
    if zone["status"] != "ACTIVE":
        raise_error(ERR_ZONE_NOT_ACTIVE, "operation requires zone.status == ACTIVE")
    if zone["compliance_posture"] != "NORMAL":
        raise_error(ERR_ZONE_AUDIT_HOLD, "operation requires zone.compliance_posture == NORMAL")


@bp.route("/zones/manipulation-orders/<orderId>/approve", methods=["POST"])
def approve_order(orderId):
    caller = authorized(["ZoneOperator"])
    order = require_path("manipulation_orders", orderId, ERR_MANIPULATION_ORDER_NOT_FOUND)
    get_body()
    if order["status"] != "REQUESTED":
        raise_error(ERR_ORDER_INVALID_TRANSITION,
                    f"order cannot be approved from {order['status']}")
    zone = db["zones"][order["zone_id"]]
    _zone_gate_active_and_normal(zone)
    lot = db["lots"].get(order["source_lot_id"])
    if lot is None or lot["status"] != "IN_ZONE":
        raise_error(ERR_LOT_NOT_IN_ZONE, "source lot must exist and be IN_ZONE")
    # Safety prohibition (priority 7).
    if lot["zone_status"] == "ZONE_RESTRICTED":
        raise_error(ERR_MANIPULATION_NOT_PERMITTED,
                    "zone-restricted merchandise may not be manipulated")
    # Resource constraints (priority 9): busy check precedes availability.
    if lot["reserved_quantity"] != 0:
        raise_error(ERR_LOT_BUSY, "source lot is reserved under another APPROVED order")
    if order["input_quantity"] > lot["quantity_on_hand"] - lot["reserved_quantity"]:
        raise_error(ERR_INSUFFICIENT_QUANTITY, "input_quantity exceeds available units")
    # Referential (priority 10): output HTS must exist at approval time.
    if order["output_hts_code"] not in HTS_RATE_TABLE:
        raise_error(ERR_UNKNOWN_HTS_CODE,
                    f"output_hts_code {order['output_hts_code']} not in tariff schedule")

    order["status"] = "APPROVED"
    touch(order)
    lot["reserved_quantity"] += order["input_quantity"]
    touch(lot)
    return success_object(order_view(order))


@bp.route("/zones/manipulation-orders/<orderId>/complete", methods=["POST"])
def complete_order(orderId):
    caller = authorized(["Importer"])
    order = require_path("manipulation_orders", orderId, ERR_MANIPULATION_ORDER_NOT_FOUND)
    get_body()
    if caller.user_id != order["importer_ref"]:
        raise_error(ERR_NOT_RESOURCE_OWNER, "caller does not own this order")
    if order["status"] != "APPROVED":
        raise_error(ERR_ORDER_INVALID_TRANSITION,
                    f"order cannot be completed from {order['status']}")
    zone = db["zones"][order["zone_id"]]
    _zone_gate_active_and_normal(zone)

    lot = db["lots"][order["source_lot_id"]]
    # HOP 1: debit the source lot.
    lot["quantity_on_hand"] -= order["input_quantity"]
    lot["reserved_quantity"] -= order["input_quantity"]
    lot["cumulative_consumed"] += order["input_quantity"]
    if lot["quantity_on_hand"] == 0 and lot["status"] == "IN_ZONE":
        lot["status"] = "DEPLETED"
    touch(lot)
    # HOP 2: create the output lot per manipulation_output_valuation.
    output_lot = create_output_lot(order, lot)
    order["output_lot_id"] = output_lot["id"]
    order["status"] = "COMPLETED"
    touch(order)
    # HOP 3: recompute zone aggregates.
    recompute_zone_aggregates(zone)
    return success_object(order_view(order))


@bp.route("/zones/manipulation-orders/<orderId>/reject", methods=["POST"])
def reject_order(orderId):
    caller = authorized(["ZoneOperator"])
    order = require_path("manipulation_orders", orderId, ERR_MANIPULATION_ORDER_NOT_FOUND)
    get_body()
    if order["status"] != "REQUESTED":
        raise_error(ERR_ORDER_INVALID_TRANSITION,
                    f"order cannot be rejected from {order['status']}")
    order["status"] = "REJECTED"
    touch(order)
    return success_object(order_view(order))


@bp.route("/zones/manipulation-orders/<orderId>/cancel", methods=["POST"])
def cancel_order(orderId):
    caller = authorized(["Importer"])
    order = require_path("manipulation_orders", orderId, ERR_MANIPULATION_ORDER_NOT_FOUND)
    get_body()
    if caller.user_id != order["importer_ref"]:
        raise_error(ERR_NOT_RESOURCE_OWNER, "caller does not own this order")
    if order["status"] not in ("REQUESTED", "APPROVED"):
        raise_error(ERR_ORDER_INVALID_TRANSITION,
                    f"order cannot be cancelled from {order['status']}")
    zone = db["zones"][order["zone_id"]]
    # Cancellation checks only the lifecycle gate; audit hold is not a blocker (PRD 3.4).
    if zone["status"] != "ACTIVE":
        raise_error(ERR_ZONE_NOT_ACTIVE, "operation requires zone.status == ACTIVE")

    was_approved = order["status"] == "APPROVED"
    order["status"] = "CANCELLED"
    touch(order)
    if was_approved:
        lot = db["lots"][order["source_lot_id"]]
        lot["reserved_quantity"] -= order["input_quantity"]
        touch(lot)
    return success_object(order_view(order))
