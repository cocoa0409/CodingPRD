"""Shipment routes: create, get, list."""

from flask import Blueprint, request

import errors
import validation as V
from db import DB, LOCK, stamp_create
from middleware import require_auth, require_role
from pagination import paginate
from response import object_response, array_response
from services import domain, ownership

bp = Blueprint("shipments", __name__)

CARRIERS = ("UPS", "FEDEX", "DHL")
READ_ROLES = ("Operator", "BureauAdmin", "Customer")


@bp.route("/bureaus/shipments", methods=["POST"])
def create_shipment():
    with LOCK:
        principal = require_auth()
        require_role(principal, ("Operator",))
        body = V.get_body()
        order_id = V.require_id(body, "order_id")
        carrier = V.require_enum(body, "carrier", CARRIERS)
        tracking = V.require_string(body, "tracking_number")

        order = DB.orders.get(order_id)
        if order is None:
            raise errors.reference_not_found()

        shipment = stamp_create({
            "bureau_id": order["bureau_id"],
            "order_id": order_id,
            "carrier": carrier,
            "tracking_number": tracking,
            "status": "CREATED",
        })
        DB.shipments[shipment["id"]] = shipment
        return object_response(shipment, 201)


@bp.route("/bureaus/shipments/<shipment_id>", methods=["GET"])
def get_shipment(shipment_id):
    with LOCK:
        principal = require_auth()
        require_role(principal, READ_ROLES)
        shipment = domain.get_or_404(DB.shipments, shipment_id)
        if principal.role == "Customer" and principal.user_id != ownership.shipment_customer_id(shipment):
            raise errors.forbidden()
        return object_response(shipment, 200)


@bp.route("/bureaus/shipments", methods=["GET"])
def list_shipments():
    with LOCK:
        principal = require_auth()
        require_role(principal, READ_ROLES)
        items = list(DB.shipments.values())
        for key in ("bureau_id", "order_id", "status"):
            val = request.args.get(key)
            if val is not None:
                items = [s for s in items if s.get(key) == val]
        if principal.role == "Customer":
            items = [s for s in items if ownership.shipment_customer_id(s) == principal.user_id]
        page, limit, offset, total = paginate(items)
        return array_response(page, limit, offset, total)
