"""Vendor endpoints."""

from flask import Blueprint

from db import store, clock
from errors import ApiError, ERR_VENDOR_NOT_FOUND
from helpers import body, req_string, req_enum, req_int, new_id, serialize_vendor, touch
from middleware import get_actor, require_role
from response import success_object

bp = Blueprint("vendors", __name__)

TRADES = {"PLUMBING", "HVAC", "ELECTRICAL", "GENERAL", "RESTORATION"}
READ_ROLES = {
    "PropertyAdmin",
    "Dispatcher",
    "OnCallTechnician",
    "MaintenanceSupervisor",
    "Vendor",
}


@bp.route("/v1/vendors", methods=["POST"])
def create_vendor():
    actor = get_actor()
    require_role(actor, {"PropertyAdmin"})
    data = body()
    name = req_string(data, "name")
    trade = req_enum(data, "trade", TRADES)
    limit = req_int(data, "per_incident_limit_cents", minimum=1)
    now = clock.now()
    rec = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 0,
        "name": name,
        "trade": trade,
        "per_incident_limit_cents": limit,
        "status": "ACTIVE",
        "_seq": store.next_seq(),
    }
    store.vendors[rec["id"]] = rec
    return success_object(serialize_vendor(rec), 201)


@bp.route("/v1/vendors/<vendorId>", methods=["GET"])
def get_vendor(vendorId):
    actor = get_actor()
    require_role(actor, READ_ROLES)
    rec = store.vendors.get(vendorId)
    if rec is None:
        raise ApiError(ERR_VENDOR_NOT_FOUND, "Vendor not found", 404)
    return success_object(serialize_vendor(rec))


@bp.route("/v1/vendors/<vendorId>/suspend", methods=["POST"])
def suspend_vendor(vendorId):
    actor = get_actor()
    require_role(actor, {"PropertyAdmin"})
    rec = store.vendors.get(vendorId)
    if rec is None:
        raise ApiError(ERR_VENDOR_NOT_FOUND, "Vendor not found", 404)
    rec["status"] = "SUSPENDED"
    touch(rec)
    return success_object(serialize_vendor(rec))
