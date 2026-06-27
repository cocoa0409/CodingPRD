"""Shipment routes: create, list, get, update (PENDING), dispatch/deliver/void."""
from flask import Blueprint, request

import db
import store
from common import (
    get_body,
    paginate,
    parse_pagination,
    require_enum,
    require_fields,
    require_str,
    sort_by_creation,
)
from errors import err
from middleware import get_user_context, require_role
from response import array_response, object_response

bp = Blueprint("shipments", __name__)

ALL_SHIP_READERS = ["SchoolCoordinator", "FulfillmentClerk"]


@bp.route("/api/shipments", methods=["POST"])
def create_shipment():
    _uid, role = get_user_context()
    require_role(role, ["FulfillmentClerk"])
    body = get_body()
    require_fields(body, ["photo_order_id", "carrier", "distribution_method"])
    order_id = require_str(body, "photo_order_id")
    carrier = require_str(body, "carrier")
    method = require_enum(body, "distribution_method", {"SCHOOL_PICKUP", "HOME_DELIVERY"})
    tracking_code = body.get("tracking_code")
    if tracking_code is not None and not isinstance(tracking_code, str):
        raise err("ERR_INVALID_REQUEST", "tracking_code must be a string")

    with db.LOCK:
        store.get_order(order_id)
        row = store.new_row("shipment", {
            "photo_order_id": order_id,
            "carrier": carrier,
            "distribution_method": method,
            "tracking_code": tracking_code,
            "status": "PENDING",
        })
        db.shipments[row["id"]] = row
    return object_response(store.serialize(row), 201)


@bp.route("/api/shipments", methods=["GET"])
def list_shipments():
    _uid, role = get_user_context()
    require_role(role, ALL_SHIP_READERS)
    limit, offset = parse_pagination()
    order_id = request.args.get("photo_order_id")
    status = request.args.get("status")
    rows = list(db.shipments.values())
    if order_id is not None:
        rows = [r for r in rows if r["photo_order_id"] == order_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = sort_by_creation(rows)
    page, total = paginate(rows, limit, offset)
    return array_response([store.serialize(r) for r in page], limit, offset, total)


@bp.route("/api/shipments/<rid>", methods=["GET"])
def get_shipment(rid):
    _uid, role = get_user_context()
    require_role(role, ALL_SHIP_READERS)
    return object_response(store.serialize(store.get_shipment(rid)))


@bp.route("/api/shipments/<rid>", methods=["PUT"])
def update_shipment(rid):
    _uid, role = get_user_context()
    require_role(role, ["FulfillmentClerk"])
    body = get_body()
    with db.LOCK:
        shipment = store.get_shipment(rid)
        if shipment["status"] != "PENDING":
            raise err("ERR_SHIPMENT_NOT_VOIDABLE", "Shipment is not PENDING; cannot edit")
        if "carrier" in body and body["carrier"] is not None:
            shipment["carrier"] = require_str(body, "carrier")
        if "distribution_method" in body and body["distribution_method"] is not None:
            shipment["distribution_method"] = require_enum(
                body, "distribution_method", {"SCHOOL_PICKUP", "HOME_DELIVERY"}
            )
        if "tracking_code" in body:
            tc = body["tracking_code"]
            if tc is not None and not isinstance(tc, str):
                raise err("ERR_INVALID_REQUEST", "tracking_code must be a string")
            shipment["tracking_code"] = tc
        store.touch(shipment)
    return object_response(store.serialize(shipment))


@bp.route("/api/shipments/<rid>/dispatch", methods=["POST"])
def dispatch_shipment(rid):
    _uid, role = get_user_context()
    require_role(role, ["FulfillmentClerk"])
    with db.LOCK:
        shipment = store.get_shipment(rid)
        order = store.get_order(shipment["photo_order_id"])
        if order["status"] != "PAID":
            raise err("ERR_ORDER_NOT_PAID", "Linked order is not PAID")
        if not shipment.get("tracking_code"):
            raise err("ERR_TRACKING_REQUIRED", "tracking_code is required to dispatch")
        shipment["status"] = "DISPATCHED"
        store.touch(shipment)
        # Cross-entity side effect: order PAID -> FULFILLED.
        order["status"] = "FULFILLED"
        store.touch(order)
    return object_response(store.serialize(shipment))


@bp.route("/api/shipments/<rid>/deliver", methods=["POST"])
def deliver_shipment(rid):
    _uid, role = get_user_context()
    require_role(role, ["FulfillmentClerk"])
    with db.LOCK:
        shipment = store.get_shipment(rid)
        if shipment["status"] != "DISPATCHED":
            raise err("ERR_SHIPMENT_NOT_DISPATCHED", "Shipment is not DISPATCHED")
        shipment["status"] = "DELIVERED"
        store.touch(shipment)
    return object_response(store.serialize(shipment))


@bp.route("/api/shipments/<rid>/void", methods=["POST"])
def void_shipment(rid):
    _uid, role = get_user_context()
    require_role(role, ["FulfillmentClerk"])
    with db.LOCK:
        shipment = store.get_shipment(rid)
        if shipment["status"] != "PENDING":
            raise err("ERR_SHIPMENT_NOT_VOIDABLE", "Shipment is not PENDING")
        shipment["status"] = "VOIDED"
        store.touch(shipment)
    return object_response(store.serialize(shipment))
