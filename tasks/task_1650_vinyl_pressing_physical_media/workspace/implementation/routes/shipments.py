"""Shipment endpoints."""

from flask import Blueprint, request

import db
import serializers
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_SHIPMENT_NOT_FOUND,
    ERR_RELEASE_NOT_FOUND, ERR_CUSTOMER_NOT_FOUND, ERR_CUSTOMER_SUSPENDED,
    ERR_SHIPMENT_INVALID_STATE,
)
from middleware import get_auth, require_role, get_pagination, apply_pagination
from response import success_object, success_list
from services import allocations
from .releases import valid_date_str

bp = Blueprint("shipments", __name__)


def get_shipment_or_404(sid):
    s = db.shipments.get(sid)
    if not s:
        raise ApiError(ERR_SHIPMENT_NOT_FOUND, "Shipment id does not exist", 404)
    return s


@bp.route("/shipments", methods=["POST"])
def create_shipment():
    _, role = get_auth()
    require_role(role, ["CustomerServiceRep"])
    body = request.get_json(silent=True) or {}

    release_id = body.get("release_id")
    distributor_customer_id = body.get("distributor_customer_id")
    quantity = body.get("quantity")
    requested_ship_date = body.get("requested_ship_date")

    if not isinstance(release_id, str) or not release_id:
        raise ApiError(ERR_INVALID_REQUEST, "release_id is required", 400)
    if not isinstance(distributor_customer_id, str) or not distributor_customer_id:
        raise ApiError(ERR_INVALID_REQUEST, "distributor_customer_id is required", 400)

    release = db.releases.get(release_id)
    if not release:
        raise ApiError(ERR_RELEASE_NOT_FOUND, "release_id does not exist", 404)
    distributor = db.customers.get(distributor_customer_id)
    if not distributor:
        raise ApiError(ERR_CUSTOMER_NOT_FOUND, "distributor_customer_id does not exist", 404)

    if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
        raise ApiError(ERR_INVALID_REQUEST, "quantity must be a positive integer", 400)
    if not valid_date_str(requested_ship_date):
        raise ApiError(ERR_INVALID_REQUEST, "requested_ship_date must be yyyy-mm-dd", 400)

    # linked-entity gate: distributor must be ACTIVE
    if distributor["status"] != "ACTIVE":
        raise ApiError(ERR_CUSTOMER_SUSPENDED, "Distributor customer is SUSPENDED", 409)

    now = db.timestamp_now()
    shipment = {
        "id": db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "release_id": release_id,
        "distributor_customer_id": distributor_customer_id,
        "quantity": quantity,
        "requested_ship_date": requested_ship_date,
        "status": "PLANNED",
        "allocations": [],
    }
    db.shipments[shipment["id"]] = shipment

    # all-or-nothing FIFO allocation at creation
    allocations.try_allocate(shipment)

    return success_object(serializers.shipment(shipment), 201)


@bp.route("/shipments", methods=["GET"])
def list_shipments():
    get_auth()
    limit, offset = get_pagination()
    release_id = request.args.get("release_id")
    distributor_customer_id = request.args.get("distributor_customer_id")
    status = request.args.get("status")
    items = list(db.shipments.values())
    if release_id is not None:
        items = [s for s in items if s["release_id"] == release_id]
    if distributor_customer_id is not None:
        items = [s for s in items if s["distributor_customer_id"] == distributor_customer_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    page, total = apply_pagination(items, limit, offset)
    return success_list([serializers.shipment(s) for s in page], limit, offset, total)


@bp.route("/shipments/<sid>", methods=["GET"])
def get_shipment(sid):
    get_auth()
    return success_object(serializers.shipment(get_shipment_or_404(sid)))


@bp.route("/shipments/<sid>/advance", methods=["POST"])
def advance_shipment(sid):
    _, role = get_auth()
    require_role(role, ["WarehouseManager"])
    shipment = get_shipment_or_404(sid)

    if shipment["status"] == "ALLOCATED":
        shipment["status"] = "PICKED"
    elif shipment["status"] == "PICKED":
        shipment["status"] = "SHIPPED"
        # settle lots
        for alloc in shipment["allocations"]:
            lot = db.inventory_lots[alloc["lot_id"]]
            lot["allocated_units"] -= alloc["quantity"]
            lot["shipped_units_cum"] += alloc["quantity"]
            lot["version"] += 1
            lot["updated_at"] = db.timestamp_now()
    else:
        raise ApiError(
            ERR_SHIPMENT_INVALID_STATE,
            "advance requires ALLOCATED or PICKED",
            409,
        )

    shipment["version"] += 1
    shipment["updated_at"] = db.timestamp_now()
    return success_object(serializers.shipment(shipment))


@bp.route("/shipments/<sid>/cancel", methods=["POST"])
def cancel_shipment(sid):
    _, role = get_auth()
    require_role(role, ["CustomerServiceRep"])
    shipment = get_shipment_or_404(sid)

    if shipment["status"] not in ("PLANNED", "ALLOCATED"):
        raise ApiError(
            ERR_SHIPMENT_INVALID_STATE,
            "cancel requires PLANNED or ALLOCATED",
            409,
        )

    was_allocated = shipment["status"] == "ALLOCATED"
    if was_allocated:
        # deallocate compensation
        for alloc in shipment["allocations"]:
            lot = db.inventory_lots[alloc["lot_id"]]
            lot["on_hand_units"] += alloc["quantity"]
            lot["allocated_units"] -= alloc["quantity"]
            lot["version"] += 1
            lot["updated_at"] = db.timestamp_now()
        shipment["allocations"] = []

    shipment["status"] = "CANCELLED"
    shipment["version"] += 1
    shipment["updated_at"] = db.timestamp_now()

    if was_allocated:
        allocations.backorder_sweep(shipment["release_id"])

    return success_object(serializers.shipment(shipment))
