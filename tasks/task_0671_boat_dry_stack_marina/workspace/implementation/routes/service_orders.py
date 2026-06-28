from flask import Blueprint, request

from db import db
from middleware import require_role
from response import object_response, array_response
from errors import err, ERR_INVALID_STATE
from services.common import (
    stamp_create, touch, get_json_body, require_fields, require_string,
    require_enum, require_nonneg_int, require_nonneg_number,
    parse_pagination, paginate,
)
from services.lookups import get_vessel, get_service_order, check_vessel_owner
from services.serialize import service_order_view
from services.calculations import compute_service_total

service_orders_bp = Blueprint("service_orders", __name__)

READ_ROLES = {"DockMaster", "BillingClerk", "BoatOwner"}
SERVICE_KINDS = {"FUEL", "VALET_SPLASH", "WINTERIZATION", "HAUL_OUT"}


@service_orders_bp.route("/marina/service-orders", methods=["POST"])
def create_service_order():
    user_id, role = require_role({"DockMaster", "BoatOwner"})
    body = get_json_body()
    require_fields(body, ["vessel_id", "service_kind"])
    require_string(body["vessel_id"], "vessel_id")
    require_enum(body["service_kind"], SERVICE_KINDS, "service_kind")

    fuel_gallons = body.get("fuel_gallons", 0)
    if fuel_gallons is None:
        fuel_gallons = 0
    require_nonneg_number(fuel_gallons, "fuel_gallons")

    fuel_price = body.get("fuel_price_cents_per_gal", 0)
    if fuel_price is None:
        fuel_price = 0
    require_nonneg_int(fuel_price, "fuel_price_cents_per_gal")

    with db.lock:
        vessel = get_vessel(body["vessel_id"])
        check_vessel_owner(vessel, user_id, role)
        total = compute_service_total(body["service_kind"], fuel_gallons, fuel_price)
        rec = {
            "vessel_id": body["vessel_id"],
            "service_kind": body["service_kind"],
            "fuel_gallons": fuel_gallons,
            "fuel_price_cents_per_gal": fuel_price,
            "total_cents": total,
            "status": "ORDERED",
        }
        stamp_create(rec)
        db.service_orders[rec["id"]] = rec
    return object_response(service_order_view(rec), 201)


@service_orders_bp.route("/marina/service-orders/<order_id>", methods=["GET"])
def fetch_service_order(order_id):
    require_role(READ_ROLES)
    rec = get_service_order(order_id)
    return object_response(service_order_view(rec), 200)


@service_orders_bp.route("/marina/service-orders", methods=["GET"])
def list_service_orders():
    require_role(READ_ROLES)
    limit, offset = parse_pagination()
    records = list(db.service_orders.values())
    vessel_id = request.args.get("vessel_id")
    service_kind = request.args.get("service_kind")
    status = request.args.get("status")
    if vessel_id is not None:
        records = [r for r in records if r["vessel_id"] == vessel_id]
    if service_kind is not None:
        records = [r for r in records if r["service_kind"] == service_kind]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, total = paginate(records, limit, offset)
    return array_response([service_order_view(r) for r in page], limit, offset, total)


@service_orders_bp.route("/marina/service-orders/<order_id>/fulfill", methods=["POST"])
def fulfill_service_order(order_id):
    require_role({"DockMaster"})
    with db.lock:
        rec = get_service_order(order_id)
        if rec["status"] != "ORDERED":
            raise err(ERR_INVALID_STATE, "Service order must be ORDERED to fulfill.")
        rec["status"] = "FULFILLED"
        touch(rec)
    return object_response(service_order_view(rec), 200)


@service_orders_bp.route("/marina/service-orders/<order_id>/cancel", methods=["POST"])
def cancel_service_order(order_id):
    user_id, role = require_role({"BoatOwner"})
    with db.lock:
        rec = get_service_order(order_id)
        vessel = get_vessel(rec["vessel_id"])
        check_vessel_owner(vessel, user_id, role)
        if rec["status"] != "ORDERED":
            raise err(ERR_INVALID_STATE, "Service order must be ORDERED to cancel.")
        rec["status"] = "CANCELLED"
        touch(rec)
    return object_response(service_order_view(rec), 200)
