"""Shipment endpoints (PRD §3.10)."""
from flask import Blueprint, request

from db import db
from common import touch, serialize, must_exist, paginate
from middleware import authenticate, require_roles
from response import success, list_success
from errors import err, ERR_INVALID_STATE

bp = Blueprint("shipments", __name__)


@bp.get("/shipments/<sid>")
def get_shipment(sid):
    authenticate()
    require_roles("CurationAdmin", "Subscriber", "BillingOperator")
    shipment = must_exist(db.shipments, sid, "Shipment")
    return success(serialize(shipment))


@bp.get("/shipments")
def list_shipments():
    authenticate()
    require_roles("CurationAdmin", "Subscriber", "BillingOperator")
    records = list(db.shipments.values())
    alloc_filter = request.args.get("allocation_id")
    if alloc_filter is not None:
        records = [r for r in records if r["allocation_id"] == alloc_filter]
    wave_filter = request.args.get("wave_id")
    if wave_filter is not None:
        records = [r for r in records if r["wave_id"] == wave_filter]
    sub_filter = request.args.get("subscription_id")
    if sub_filter is not None:
        records = [r for r in records if r["subscription_id"] == sub_filter]
    page, limit, offset, total = paginate(records)
    return list_success([serialize(r) for r in page], limit, offset, total)


@bp.post("/shipments/<sid>/dispatch")
def dispatch_shipment(sid):
    authenticate()
    require_roles("CurationAdmin")
    shipment = must_exist(db.shipments, sid, "Shipment")
    if shipment["status"] != "PACKED":
        raise err(ERR_INVALID_STATE, "Dispatch requires a PACKED shipment.")
    shipment["status"] = "DISPATCHED"
    touch(shipment)
    return success(serialize(shipment))


@bp.post("/shipments/<sid>/deliver")
def deliver_shipment(sid):
    authenticate()
    require_roles("CurationAdmin")
    shipment = must_exist(db.shipments, sid, "Shipment")
    if shipment["status"] != "DISPATCHED":
        raise err(ERR_INVALID_STATE, "Deliver requires a DISPATCHED shipment.")
    shipment["status"] = "DELIVERED"
    touch(shipment)
    return success(serialize(shipment))
