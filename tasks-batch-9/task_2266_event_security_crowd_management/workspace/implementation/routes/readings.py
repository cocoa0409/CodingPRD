"""DensityReading endpoints (PRD 3.8)."""

from datetime import timedelta

from flask import Blueprint

import calc
import engine
import serial
import valid
from auth import authenticate
from calc import D, num, round_half_up
from db import db, make_record, parse_iso
from errors import ApiError
from response import object_response
from routes._common import get_event, get_reading, match_filters, paginated

bp = Blueprint("readings", __name__)

DENSITY_LEVELS = ("GREEN", "AMBER", "RED", "CRITICAL")
WRITE_ROLES = {"PostSupervisor", "IncidentCommander", "SecurityDirector"}
READ_ROLES = {"SecurityDirector", "StaffingCoordinator", "IncidentCommander", "PostSupervisor"}
WINDOW_MARGIN = timedelta(hours=2)
ROLLING_WINDOW = 3


def _pair_readings(event_id, zone_id):
    return [
        r
        for r in db.readings.values()
        if r.get("event_id") == event_id and r.get("zone_id") == zone_id
    ]


def _observation_key(record):
    return (record.get("observed_at") or "", record.get("created_at") or "", record.get("_seq") or 0)


@bp.post("/security-events/<event_id>/density-readings")
def create_reading(event_id):
    actor = authenticate(WRITE_ROLES)
    payload = valid.body()
    zone_id = valid.req_string(payload, "zone_id")
    observed_at = valid.req_datetime(payload, "observed_at")
    observed_occupancy = valid.req_int(payload, "observed_occupancy", minimum=0)

    event = get_event(event_id)
    zone = db.zones.get(zone_id)
    if zone is None:
        raise ApiError("ERR_ZONE_NOT_FOUND")
    if zone.get("venue_id") != event.get("venue_id"):
        raise ApiError(
            "ERR_ZONE_VENUE_MISMATCH", "The referenced zone does not belong to the event's venue."
        )

    doors_open = parse_iso(event.get("doors_open_at"))
    event_end = parse_iso(event.get("event_end_at"))
    if observed_at[1] < doors_open - WINDOW_MARGIN or observed_at[1] > event_end + WINDOW_MARGIN:
        raise ApiError("ERR_READING_TIMESTAMP_OUT_OF_RANGE")

    area = D(zone.get("floor_area_sqm") or 0)
    if area > 0:
        density = round_half_up(D(observed_occupancy) / area, 3)
    else:
        density = D("0.000")
    max_safe = D(zone.get("max_safe_occupancy") or 0)
    if max_safe > 0:
        occupancy_ratio = round_half_up(D(observed_occupancy) / max_safe, 3)
    else:
        occupancy_ratio = D("0.000")

    record = make_record(
        {
            "event_id": event["id"],
            "zone_id": zone["id"],
            "observed_at": observed_at[0],
            "observed_occupancy": observed_occupancy,
            "reported_by_user_id": actor.user_id,
            "density_persons_per_sqm": num(density),
            "occupancy_ratio": num(occupancy_ratio),
        },
        versioned=False,
    )

    window = _pair_readings(event["id"], zone["id"]) + [record]
    pair_count = len(window)
    window.sort(key=_observation_key)
    latest = window[-ROLLING_WINDOW:]
    total = D(0)
    for row in latest:
        total += D(str(row.get("density_persons_per_sqm") or 0))
    rolling_mean = round_half_up(total / D(len(latest)), 3)

    instantaneous_level = calc.classify_density(density)
    rolling_level = calc.classify_density(rolling_mean)
    effective_level = rolling_level if pair_count >= ROLLING_WINDOW else instantaneous_level

    record["rolling_mean_persons_per_sqm"] = num(rolling_mean)
    record["instantaneous_level"] = instantaneous_level
    record["rolling_level"] = rolling_level
    record["effective_level"] = effective_level

    db.readings[record["id"]] = record
    engine.cascade_event_only(event)
    return object_response(serial.reading(record), 201)


@bp.get("/density-readings/<reading_id>")
def read_reading(reading_id):
    authenticate(READ_ROLES)
    reading = get_reading(reading_id)
    return object_response(serial.reading(reading))


@bp.get("/density-readings")
def list_readings():
    authenticate(READ_ROLES)
    filters = {
        "event_id": valid.query_string("event_id"),
        "zone_id": valid.query_string("zone_id"),
        "effective_level": valid.query_enum("effective_level", DENSITY_LEVELS),
    }
    records = [r for r in db.readings.values() if match_filters(r, filters)]
    return paginated(records, serial.reading)
