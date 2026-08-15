"""MeterReading endpoints."""
from flask import Blueprint, request

from middleware import get_context, require_roles, get_json_body
from response import ok, created, paginate
from errors import ApiError
from db import store, new_append_only

bp = Blueprint("meter_readings", __name__)


@bp.route("/coop/meter-readings", methods=["POST"])
def create_meter_reading():
    uid, role = get_context()
    require_roles(["BillingClerk", "FieldOpsCoordinator"])
    body = get_json_body()
    required = ["service_location_id", "reading_at", "kwh_register", "demand_kw", "source"]
    for field in required:
        if field not in body:
            raise ApiError("ERR_INVALID_REQUEST", 400, f"Missing required field: {field}")
    loc = store.service_locations.get(body["service_location_id"])
    if not loc:
        raise ApiError("ERR_NOT_FOUND", 404, "ServiceLocation not found")
    if body["source"] not in ("AMR", "MANUAL", "ESTIMATED"):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Invalid source")

    reading = new_append_only({
        "service_location_id": body["service_location_id"],
        "reading_at": body["reading_at"],
        "kwh_register": body["kwh_register"],
        "demand_kw": body["demand_kw"],
        "source": body["source"],
    })
    store.meter_readings[reading["id"]] = reading
    return created(reading)


@bp.route("/coop/meter-readings/<reading_id>", methods=["GET"])
def get_meter_reading(reading_id):
    uid, role = get_context()
    require_roles(["BillingClerk", "FieldOpsCoordinator", "MemberServicesRep"])
    r = store.meter_readings.get(reading_id)
    if not r:
        raise ApiError("ERR_NOT_FOUND", 404, "MeterReading not found")
    return ok(r)


@bp.route("/coop/meter-readings", methods=["GET"])
def list_meter_readings():
    uid, role = get_context()
    require_roles(["BillingClerk", "FieldOpsCoordinator", "MemberServicesRep"])
    service_location_id = request.args.get("service_location_id")
    rows = list(store.meter_readings.values())
    if service_location_id is not None:
        rows = [r for r in rows if r.get("service_location_id") == service_location_id]
    p = paginate()
    page = p(rows)
    return ok(page, rtype="array", pagination=p)
