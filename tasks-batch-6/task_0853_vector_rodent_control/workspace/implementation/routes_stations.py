"""Bait stations and surveillance readings (PRD 3.8)."""

import datetime

from flask import Blueprint

import aggregates
import auth
import calc
import envelope
import flows
import lclock
import lookups
import serialize
import store
import valid
from errors import ApiError

bp = Blueprint("stations", __name__)
P = "/vector-control"

BAIT_TYPES = ("ANTICOAGULANT", "SNAP_TRAP", "GLUE_BOARD", "BAIT_BLOCK")
STATION_CONDITIONS = ("INTACT", "DAMAGED", "MISSING")
CONDITION_TO_STATUS = {"INTACT": "ACTIVE", "DAMAGED": "DAMAGED", "MISSING": "REMOVED"}


@bp.post(P + "/bait-stations")
def create_station():
    auth.guard("Inspector")
    data = valid.body()
    raw_property_id = data.get("property_id")
    prop = None
    if isinstance(raw_property_id, str) and raw_property_id:
        prop = lookups.prop(raw_property_id)
    property_id = valid.req_id(data, "property_id")
    station_code = valid.req_str(data, "station_code", min_len=1)
    bait_type = valid.req_enum(data, "bait_type", BAIT_TYPES)
    if prop is None:
        prop = lookups.prop(property_id)
    if any(
        s["property_id"] == property_id and s["station_code"] == station_code
        for s in store.stations.values()
    ):
        raise ApiError(
            "ERR_DUPLICATE_CODE", "station_code '%s' is already used on this parcel." % station_code
        )
    station = store.stamp_new(
        {
            "property_id": property_id,
            "zone_id": prop["zone_id"],
            "station_code": station_code,
            "bait_type": bait_type,
            "status": "ACTIVE",
            "installed_at": lclock.now(),
            "last_reading_at": None,
            "reading_count": 0,
            "cumulative_take_pct": 0,
        }
    )
    store.stations[station["id"]] = station
    zone = store.zones.get(prop["zone_id"])
    if zone is not None:
        aggregates.zone_counters(zone)
    return envelope.obj(serialize.station(station), 201)


@bp.get(P + "/bait-stations/<station_id>")
def read_station(station_id):
    auth.guard("ProgramAdmin", "Supervisor", "Inspector")
    station = lookups.station(station_id)
    return envelope.obj(serialize.station(station))


@bp.get(P + "/bait-stations")
def list_stations():
    auth.guard("ProgramAdmin", "Supervisor", "Inspector")
    limit, offset = valid.pagination()
    filters = {
        "property_id": valid.query_str("property_id"),
        "zone_id": valid.query_str("zone_id"),
        "status": valid.query_str("status"),
    }

    def keep(s):
        for field, expected in filters.items():
            if expected is not None and s[field] != expected:
                return False
        return True

    rows = store.ordered(store.stations, keep)
    return lookups.page(rows, limit, offset, serialize.station)


@bp.post(P + "/bait-stations/<station_id>/readings")
def create_reading(station_id):
    auth.guard("Inspector")
    station = lookups.station(station_id)
    data = valid.body()
    take_pct = valid.req_int(data, "take_pct", minimum=0, maximum=100)
    activity_sign_count = valid.req_int(data, "activity_sign_count", minimum=0)
    station_condition = valid.req_enum(data, "station_condition", STATION_CONDITIONS)
    rebaited = valid.opt_bool(data, "rebaited", True)
    # step 7: a decommissioned station accepts no further readings
    if station["status"] == "REMOVED":
        raise ApiError("ERR_STATION_DECOMMISSIONED")
    # step 12: minimum servicing interval
    now = lclock.now()
    last = station["last_reading_at"]
    if last is not None and now - last < datetime.timedelta(
        hours=calc.READING_MIN_INTERVAL_HOURS
    ):
        raise ApiError("ERR_READING_TOO_SOON")

    reading = store.stamp_new(
        {
            "bait_station_id": station["id"],
            "reading_at": now,
            "take_pct": take_pct,
            "activity_sign_count": activity_sign_count,
            "station_condition": station_condition,
            "rebaited": rebaited,
        },
        versioned=False,
    )
    store.readings[reading["id"]] = reading
    station["last_reading_at"] = now
    station["reading_count"] = sum(
        1 for r in store.readings.values() if r["bait_station_id"] == station["id"]
    )
    station["cumulative_take_pct"] = sum(
        r["take_pct"] for r in store.readings.values() if r["bait_station_id"] == station["id"]
    )
    station["status"] = CONDITION_TO_STATUS[station_condition]
    store.touch(station)
    flows.zone_recompute(station["zone_id"])
    return envelope.obj(serialize.reading(reading), 201)


@bp.get(P + "/bait-stations/<station_id>/readings")
def list_readings(station_id):
    auth.guard("ProgramAdmin", "Supervisor", "Inspector")
    station = lookups.station(station_id)
    limit, offset = valid.pagination()
    rows = store.ordered(store.readings, lambda r: r["bait_station_id"] == station["id"])
    return lookups.page(rows, limit, offset, serialize.reading)
