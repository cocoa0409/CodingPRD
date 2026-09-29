"""Service zones and the logical-clock capability."""
from flask import Blueprint

import clock
import db
import listing
import response
import serializers
import validation
from errors import ApiError
from middleware import ALL_ROLES, endpoint
from services import cascades, metrics

bp = Blueprint("zones", __name__)

ZONE_STATUSES = ("DRAFT", "ACTIVE", "SUSPENDED")


def get_zone(zone_id):
    zone = db.service_zones.get(zone_id)
    if zone is None:
        raise ApiError("ERR_SERVICE_ZONE_NOT_FOUND")
    return zone


@bp.post("/service-zones")
@endpoint(["ZoneAdmin"])
def create_zone():
    body = validation.get_body()
    name = validation.req_str(body, "name", 1, 120)
    zone_code = validation.req_str(body, "zone_code", 2, 12)
    max_walk_meters = validation.req_int(body, "max_walk_meters", 100, 1200)
    detour_pct = validation.req_number(body, "detour_tolerance_pct", 0, 1.0, max_dp=2)
    detour_floor = validation.req_int(body, "detour_tolerance_floor_minutes", 0, 60)
    base_fare_cents = validation.req_int(body, "base_fare_cents", 0)
    cap_daily = validation.req_int(body, "fare_cap_cents_daily", 0)
    cap_weekly = validation.req_int(body, "fare_cap_cents_weekly", 0)
    on_time = validation.opt_int(body, "on_time_window_minutes", 5, 0, 30)
    curb = validation.opt_int(body, "curb_capacity_per_bucket", 2, 1, None)

    for existing in db.service_zones.values():
        if existing["zone_code"] == zone_code:
            raise ApiError("ERR_DUPLICATE_ZONE_CODE")

    zone = db.base_record()
    zone.update({
        "name": name,
        "zone_code": zone_code,
        "status": "DRAFT",
        "max_walk_meters": max_walk_meters,
        "detour_tolerance_pct": detour_pct,
        "detour_tolerance_floor_minutes": detour_floor,
        "base_fare_cents": base_fare_cents,
        "fare_cap_cents_daily": cap_daily,
        "fare_cap_cents_weekly": cap_weekly,
        "on_time_window_minutes": on_time,
        "curb_capacity_per_bucket": curb,
        "completed_trip_count": 0,
        "unserved_trip_count": 0,
        "avg_wait_minutes": 0.00,
        "avg_ride_minutes": 0.00,
        "boardings_per_revenue_hour": 0.00,
        "wav_avg_wait_minutes": 0.00,
        "nonwav_avg_wait_minutes": 0.00,
        "wav_equivalence_ratio": 0.000,
        "equivalence_verdict": "COMPLIANT",
    })
    db.service_zones.add(zone)
    return response.created(serializers.pick(zone, serializers.SERVICE_ZONE))


@bp.post("/service-zones/<zone_id>/activate")
@endpoint(["ZoneAdmin"])
def activate_zone(zone_id):
    zone = get_zone(zone_id)
    if zone["status"] not in ("DRAFT", "SUSPENDED"):
        raise ApiError("ERR_INVALID_ZONE_STATE")
    zone["status"] = "ACTIVE"
    db.touch(zone)
    return response.object_response(
        serializers.pick(zone, serializers.SERVICE_ZONE))


@bp.post("/service-zones/<zone_id>/suspend")
@endpoint(["ZoneAdmin"])
def suspend_zone(zone_id):
    zone = get_zone(zone_id)
    body = validation.get_body()
    validation.opt_str(body, "note", min_len=0)
    if zone["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_ZONE_STATE")
    zone["status"] = "SUSPENDED"
    cascades.sweep_zone_suspension(zone)
    metrics.recompute_zone(zone)
    db.touch(zone)
    return response.object_response(
        serializers.pick(zone, serializers.SERVICE_ZONE))


@bp.get("/service-zones/<zone_id>")
@endpoint(ALL_ROLES)
def read_zone(zone_id):
    zone = get_zone(zone_id)
    return response.object_response(
        serializers.pick(zone, serializers.SERVICE_ZONE))


@bp.get("/service-zones")
@endpoint(ALL_ROLES)
def list_zones():
    return listing.list_endpoint(db.service_zones.ordered(),
                                 serializers.SERVICE_ZONE,
                                 {"status": "status"})


# --------------------------------------------------------------------------
# logical clock
# --------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
@endpoint(["ZoneAdmin", "Dispatcher"])
def set_clock():
    body = validation.get_body()
    raw, _dt = validation.req_datetime(body, "to_iso8601")
    clock.set_now(raw)
    return response.object_response({"current_utc": clock.now_raw()})
