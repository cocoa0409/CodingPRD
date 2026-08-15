"""TemperatureReading endpoints: append (PLANNED/DEPARTED only, strictly
increasing recorded_at, not after the clock) and list."""

from flask import Blueprint, request

from clock import now, parse_iso, format_iso_ms
from db import DB
from middleware import require_role, require_any
from util import (
    get_json_body, check_unknown_fields, require_fields, opt_int, opt_enum,
    opt_iso_dt, event_fields, paginate, err,
)
from response import success_object, success_list
from errors import (
    ERR_TRIP_NOT_FOUND, ERR_OWNERSHIP_MISMATCH, ERR_READINGS_NOT_ACCEPTED,
    ERR_READING_OUT_OF_ORDER,
)
from serializers import serialize_reading
from services import recompute_cold_chain

bp = Blueprint("temperature_readings", __name__)


@bp.post("/dairy/trips/<tripId>/temperature-readings")
def create_reading(tripId):
    user_id, _role = require_role("RouteDriver")
    trip = DB.trips.get(tripId)
    if trip is None:
        raise err(ERR_TRIP_NOT_FOUND, "TruckTrip id not found")
    if trip["driver_id"] != user_id:
        raise err(ERR_OWNERSHIP_MISMATCH, "Caller is not the trip's driver")
    body = get_json_body()
    check_unknown_fields(body, {"recorded_at", "temp_tenths_f", "zone"})
    require_fields(body, ["recorded_at", "temp_tenths_f", "zone"])
    recorded_raw = opt_iso_dt(body, "recorded_at")
    temp = opt_int(body, "temp_tenths_f")
    zone = opt_enum(body, "zone", {"CAB", "BOX"})
    if trip["status"] not in ("PLANNED", "DEPARTED"):
        raise err(ERR_READINGS_NOT_ACCEPTED,
                  "Readings are accepted only while the trip is PLANNED or DEPARTED")
    recorded_dt = parse_iso(recorded_raw)
    prev = [r for r in DB.temperature_readings.values() if r["trip_id"] == tripId]
    if prev:
        latest = max(prev, key=lambda r: (r["recorded_at"], r["_seq"]))
        if not (recorded_dt > parse_iso(latest["recorded_at"])):
            raise err(ERR_READING_OUT_OF_ORDER,
                      "recorded_at must be strictly greater than the previous reading")
    if recorded_dt > now():
        raise err(ERR_READING_OUT_OF_ORDER,
                  "recorded_at must not be later than the current clock")
    r = event_fields()
    r.update({
        "trip_id": tripId,
        "recorded_at": format_iso_ms(recorded_dt),
        "temp_tenths_f": temp,
        "zone": zone,
        "_trip_status": trip["status"],  # internal: pre-cool evidence check
    })
    DB.temperature_readings[r["id"]] = r
    recompute_cold_chain(trip)
    return success_object(serialize_reading(r), status=201)


@bp.get("/dairy/trips/<tripId>/temperature-readings")
def list_readings(tripId):
    require_any()
    trip = DB.trips.get(tripId)
    if trip is None:
        raise err(ERR_TRIP_NOT_FOUND, "TruckTrip id not found")
    items = [r for r in DB.temperature_readings.values() if r["trip_id"] == tripId]
    zone = request.args.get("zone")
    if zone is not None:
        items = [r for r in items if r["zone"] == zone]
    items.sort(key=lambda r: (r["recorded_at"], r["_seq"]))
    page, limit, offset, total = paginate(items)
    return success_list([serialize_reading(r) for r in page], limit, offset, total)
