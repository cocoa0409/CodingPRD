"""DeliveryZone endpoints."""
from flask import Blueprint, request

import errors
from db import db
from middleware import body_json, f_bool, f_str, require_roles
from response import list_response, ok_object
from services import (base_record, ser_customer, ser_route, ser_zone)

bp = Blueprint("zones", __name__)

ZONE_READ_ROLES = ("OpsAdmin", "Dispatcher", "Driver", "BillingAdmin")


@bp.post("/delivery-zones")
@require_roles("OpsAdmin")
def create_zone():
    d = body_json()
    code = f_str(d, "code")
    name = f_str(d, "name")
    active = f_bool(d, "active", required=False, default=True)
    for z in db.zones.values():
        if z["code"] == code:
            raise errors.invalid_request("zone code must be unique")
    rec = base_record()
    rec.update({"code": code, "name": name, "active": active})
    with db.lock:
        db.zones[rec["id"]] = rec
    return ok_object(ser_zone(rec), 201)


@bp.get("/delivery-zones")
@require_roles(*ZONE_READ_ROLES)
def list_zones():
    return list_response(list(db.zones.values()), ser_zone)


@bp.get("/delivery-zones/<zone_id>")
@require_roles(*ZONE_READ_ROLES)
def get_zone(zone_id):
    rec = db.zones.get(zone_id)
    if rec is None:
        raise errors.not_found("delivery zone not found")
    return ok_object(ser_zone(rec))


@bp.get("/delivery-zones/<zone_id>/customers")
@require_roles("OpsAdmin", "Dispatcher", "BillingAdmin")
def list_zone_customers(zone_id):
    if db.zones.get(zone_id) is None:
        raise errors.not_found("delivery zone not found")
    items = [c for c in db.customers.values() if c["delivery_zone_id"] == zone_id]
    return list_response(items, ser_customer)


@bp.get("/delivery-zones/<zone_id>/routes")
@require_roles("OpsAdmin", "Dispatcher", "Driver")
def list_zone_routes(zone_id):
    if db.zones.get(zone_id) is None:
        raise errors.not_found("delivery zone not found")
    items = [r for r in db.routes.values() if r["zone_id"] == zone_id]
    return list_response(items, ser_route)
