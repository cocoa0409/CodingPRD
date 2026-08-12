"""Carriage: the shared Shipment state machine (PRD 3.8)."""

from flask import Blueprint

import calc
import constants as C
import serialize
import services
import shapes
from auth import api, get_shipment
from envelope import ok, paginate
from errors import ApiError
from store import db, now, touch

bp = Blueprint("shipments", __name__)

READ_ROLES = ["AccountHolder", "RegistryOwner", "SupportAgent", "OpsAdmin"]


@api(bp, "GET", "/shipments/<id>", READ_ROLES)
def read_shipment(id):
    return ok(serialize.shipment(get_shipment(id)))


@api(bp, "GET", "/shipments", READ_ROLES)
def list_shipments():
    rows = [r for r in db.shipments.values()
            if shapes.match(r, "account_id", shapes.qs("account_id"))
            and shapes.match(r, "cycle_id", shapes.qs("cycle_id"))
            and shapes.match(r, "gift_order_id", shapes.qs("gift_order_id"))
            and shapes.match(r, "status", shapes.qs("status"))]
    return paginate(rows, serialize.shipment)


@api(bp, "POST", "/shipments/<id>/pick", ["OpsAdmin"])
def pick(id):
    shipment = get_shipment(id)
    if shipment["status"] != "CREATED":
        raise ApiError("ERR_SHIPMENT_STATE_INVALID")
    shipment["status"] = "PICKED"
    touch(shipment)
    return ok(serialize.shipment(shipment))


@api(bp, "POST", "/shipments/<id>/transit", ["OpsAdmin"])
def transit(id):
    shipment = get_shipment(id)
    if shipment["status"] != "PICKED":
        raise ApiError("ERR_SHIPMENT_STATE_INVALID")
    shipment["status"] = "IN_TRANSIT"
    shipment["eta_days"] = calc.shipment_eta_days(shipment["service_level"])
    touch(shipment)
    return ok(serialize.shipment(shipment))


@api(bp, "POST", "/shipments/<id>/exception", ["OpsAdmin"])
def exception(id):
    shipment = get_shipment(id)
    # The from-state is checked first; the cap error is returned only because
    # IN_TRANSIT is itself a perfectly valid from-state.
    if shipment["status"] != "IN_TRANSIT":
        raise ApiError("ERR_SHIPMENT_STATE_INVALID")
    if int(shipment["exception_count"]) >= C.SHIPMENT_EXCEPTION_RETRY_CAP:
        raise ApiError("ERR_SHIPMENT_RETRY_CAP_EXCEEDED")
    shipment["status"] = "EXCEPTION"
    shipment["exception_count"] = int(shipment["exception_count"]) + 1
    touch(shipment)
    return ok(serialize.shipment(shipment))


@api(bp, "POST", "/shipments/<id>/retry", ["OpsAdmin"])
def retry(id):
    shipment = get_shipment(id)
    if shipment["status"] != "EXCEPTION":
        raise ApiError("ERR_SHIPMENT_STATE_INVALID")
    shipment["status"] = "IN_TRANSIT"
    touch(shipment)
    return ok(serialize.shipment(shipment))


@api(bp, "POST", "/shipments/<id>/deliver", ["OpsAdmin"])
def deliver(id):
    shipment = get_shipment(id)
    if shipment["status"] != "IN_TRANSIT":
        raise ApiError("ERR_SHIPMENT_STATE_INVALID")
    shipment["status"] = "DELIVERED"
    shipment["delivered_at"] = now()
    touch(shipment)
    gift = db.gift_orders.get(shipment["gift_order_id"]) \
        if shipment["gift_order_id"] else None
    if gift is not None and gift["status"] == "CLAIMED_ITEM":
        # A gifted item that reaches the doorstep awards exactly ZERO points and
        # writes no ledger entry at all.
        gift["status"] = "FULFILLED"
        touch(gift)
    return ok(serialize.shipment(shipment))


@api(bp, "POST", "/shipments/<id>/return", ["OpsAdmin"])
def return_shipment(id):
    shipment = get_shipment(id)
    if shipment["status"] not in ("EXCEPTION", "DELIVERED"):
        raise ApiError("ERR_SHIPMENT_STATE_INVALID")
    shipment["status"] = "RETURNED"
    touch(shipment)
    return ok(serialize.shipment(shipment))
