"""Pump stations and irrigation runs."""

from decimal import Decimal

from flask import Blueprint

import calc
import services
from envelope import created, ok
from errors import ApiError
from serializers import irrigation_run_out, pump_station_out
from store import store
from util import ZERO, dec, half_open_overlap, rhu, whole_minutes
from validators import (bad, body, endpoint, field_dt, field_enum, field_int, field_num,
                        field_str, field_uuid, pagination, path_uuid, query_enum,
                        query_uuid)

from routes.common import list_response

bp = Blueprint("irrigation", __name__)

SOURCE_TYPES = ("WELL", "POND", "RECLAIMED")
STATION_STATUSES = ("ONLINE", "RESTRICTED", "OFFLINE")
RUN_STATUSES = ("SCHEDULED", "COMPLETED", "REVERSED", "CANCELLED")


# --------------------------------------------------------------------------
# pump stations
# --------------------------------------------------------------------------
@bp.post("/pump-stations")
@endpoint(("Superintendent",))
def create_pump_station():
    payload = body()
    course_id = field_uuid(payload, "course_id")
    source_type = field_enum(payload, "source_type", SOURCE_TYPES)
    max_flow = field_num(payload, "max_flow_gpm", exclusive_min=0)
    max_zones = field_int(payload, "max_concurrent_zones", minimum=1)
    daily_cap = field_num(payload, "daily_withdrawal_cap_gal", exclusive_min=0)

    course = services.require(store.courses, course_id, "ERR_COURSE_NOT_FOUND")

    record = services.base_record()
    record.update({
        "course_id": course_id,
        "source_type": source_type,
        "max_flow_gpm": max_flow,
        "max_concurrent_zones": max_zones,
        "daily_withdrawal_cap_gal": daily_cap,
        "withdrawn_today_gal": Decimal("0.0"),
        "status": "RESTRICTED" if course["water_posture"] in ("RESTRICTED", "SUSPENDED")
                  else "ONLINE",
    })
    store.pump_stations[record["id"]] = record
    return created(pump_station_out(record))


@bp.get("/pump-stations")
@endpoint(("Superintendent", "Agronomist"))
def list_pump_stations():
    page = pagination()
    course_id = query_uuid("course_id")
    source_type = query_enum("source_type", SOURCE_TYPES)
    status = query_enum("status", STATION_STATUSES)
    records = [
        record for record in store.pump_stations.values()
        if (course_id is None or record["course_id"] == course_id)
        and (source_type is None or record["source_type"] == source_type)
        and (status is None or record["status"] == status)
    ]
    return list_response(records, pump_station_out, page=page)


@bp.get("/pump-stations/<station_id>")
@endpoint(("Superintendent", "Agronomist"))
def get_pump_station(station_id):
    path_uuid(station_id, "ERR_PUMP_STATION_NOT_FOUND")
    record = services.require(store.pump_stations, station_id,
                              "ERR_PUMP_STATION_NOT_FOUND")
    return ok(pump_station_out(record))


@bp.patch("/pump-stations/<station_id>/status")
@endpoint(("Superintendent", "EquipmentTechnician"))
def set_pump_station_status(station_id):
    path_uuid(station_id, "ERR_PUMP_STATION_NOT_FOUND")
    payload = body()
    status = field_enum(payload, "status", STATION_STATUSES)
    station = services.require(store.pump_stations, station_id,
                               "ERR_PUMP_STATION_NOT_FOUND")
    station["status"] = status
    services.touch(station)
    if status == "OFFLINE":
        for run in services.sorted_records(list(store.irrigation_runs.values())):
            if run["pump_station_id"] != station_id:
                continue
            if run["status"] != "SCHEDULED":
                continue
            services.cancel_run(run)
    return ok(pump_station_out(station))


# --------------------------------------------------------------------------
# irrigation runs
# --------------------------------------------------------------------------
@bp.post("/irrigation-runs")
@endpoint(("Agronomist",))
def create_irrigation_run():
    payload = body()
    station_id = field_uuid(payload, "pump_station_id")
    area_id = field_uuid(payload, "turf_area_id")
    window_start = field_dt(payload, "window_start")
    window_end = field_dt(payload, "window_end")
    duration = whole_minutes(window_start, window_end)
    if duration is None:
        bad("'window_end' must be strictly after 'window_start' by a whole number "
            "of minutes.")
    if duration < 1 or duration > 720:
        bad("An irrigation window must be from 1 through 720 minutes.")
    deficit = field_num(payload, "target_moisture_deficit_pct", minimum=0, maximum=60)
    expected_version = field_int(payload, "expected_pump_station_version", minimum=0)

    area = services.require(store.turf_areas, area_id, "ERR_TURF_AREA_NOT_FOUND")
    station = services.require(store.pump_stations, station_id,
                               "ERR_PUMP_STATION_NOT_FOUND")
    if expected_version != int(station["version"]):
        raise ApiError("ERR_STALE_PUMP_VERSION")

    course = services.require(store.courses, station["course_id"],
                              "ERR_COURSE_NOT_FOUND")
    if course["play_posture"] == "CLOSED":
        raise ApiError("ERR_COURSE_CLOSED")
    if area["agronomic_status"] == "OUT_OF_PLAY":
        raise ApiError("ERR_TURF_AREA_OUT_OF_PLAY")
    if area["course_id"] != station["course_id"]:
        raise ApiError("ERR_TASK_TURF_AREA_MISMATCH")
    if station["status"] == "OFFLINE":
        raise ApiError("ERR_PUMP_OFFLINE")

    _, allotted_gal, flow_gpm = calc.irrigation_allotment(
        area, station, course, window_start, window_end, deficit)

    intersecting = [
        run for run in store.irrigation_runs.values()
        if run["pump_station_id"] == station_id
        and run["status"] == "SCHEDULED"
        and half_open_overlap(window_start, window_end,
                              run["window_start"], run["window_end"])
    ]
    if len(intersecting) + 1 > int(station["max_concurrent_zones"]):
        raise ApiError("ERR_PUMP_ZONE_CAPACITY")

    total_flow = flow_gpm
    for run in intersecting:
        total_flow += dec(run["flow_gpm"])
    if total_flow > dec(station["max_flow_gpm"]):
        raise ApiError("ERR_PUMP_FLOW_CAPACITY")

    if allotted_gal <= ZERO:
        raise ApiError("ERR_ZERO_ALLOTMENT")

    if station["source_type"] != "RECLAIMED":
        if dec(course["water_used_gal"]) + allotted_gal > \
                dec(course["annual_water_allocation_gal"]):
            raise ApiError("ERR_WATER_ALLOCATION_EXCEEDED")

    record = services.base_record()
    record.update({
        "pump_station_id": station_id,
        "turf_area_id": area_id,
        "window_start": window_start,
        "window_end": window_end,
        "target_moisture_deficit_pct": deficit,
        "allotted_gal": allotted_gal,
        "flow_gpm": flow_gpm,
        "volume_gal": Decimal("0.0"),
        "status": "SCHEDULED",
    })
    store.irrigation_runs[record["id"]] = record
    return created(irrigation_run_out(record))


@bp.get("/irrigation-runs")
@endpoint(("Superintendent", "Agronomist"))
def list_irrigation_runs():
    page = pagination()
    station_id = query_uuid("pump_station_id")
    area_id = query_uuid("turf_area_id")
    status = query_enum("status", RUN_STATUSES)
    records = [
        record for record in store.irrigation_runs.values()
        if (station_id is None or record["pump_station_id"] == station_id)
        and (area_id is None or record["turf_area_id"] == area_id)
        and (status is None or record["status"] == status)
    ]
    return list_response(records, irrigation_run_out, page=page)


@bp.get("/irrigation-runs/<run_id>")
@endpoint(("Superintendent", "Agronomist"))
def get_irrigation_run(run_id):
    path_uuid(run_id, "ERR_IRRIGATION_RUN_NOT_FOUND")
    record = services.require(store.irrigation_runs, run_id,
                              "ERR_IRRIGATION_RUN_NOT_FOUND")
    return ok(irrigation_run_out(record))


@bp.post("/irrigation-runs/<run_id>/complete")
@endpoint(("Agronomist",))
def complete_irrigation_run(run_id):
    path_uuid(run_id, "ERR_IRRIGATION_RUN_NOT_FOUND")
    payload = body()
    actual_minutes = field_int(payload, "actual_minutes", required=False, minimum=0)
    run = services.require(store.irrigation_runs, run_id,
                           "ERR_IRRIGATION_RUN_NOT_FOUND")
    if run["status"] != "SCHEDULED":
        raise ApiError("ERR_RUN_STATE_INVALID")
    area = store.turf_areas.get(run["turf_area_id"])
    if area is not None and area["agronomic_status"] == "OUT_OF_PLAY":
        raise ApiError("ERR_TURF_AREA_OUT_OF_PLAY")
    station = store.pump_stations.get(run["pump_station_id"])
    if station is not None and station["status"] == "OFFLINE":
        raise ApiError("ERR_PUMP_OFFLINE")

    run["volume_gal"] = calc.irrigation_volume(run, actual_minutes)
    run["status"] = "COMPLETED"
    services.touch(run)
    if station is not None:
        services.recompute_station_withdrawn(station)
        course = store.courses.get(station["course_id"])
        if course is not None:
            services.recompute_course_water(course)
    return ok(irrigation_run_out(run))


@bp.post("/irrigation-runs/<run_id>/reverse")
@endpoint(("Superintendent",))
def reverse_irrigation_run(run_id):
    path_uuid(run_id, "ERR_IRRIGATION_RUN_NOT_FOUND")
    payload = body()
    field_str(payload, "reversal_note", required=False, max_len=2000, allow_empty=True)
    run = services.require(store.irrigation_runs, run_id,
                           "ERR_IRRIGATION_RUN_NOT_FOUND")
    if run["status"] != "COMPLETED":
        raise ApiError("ERR_RUN_STATE_INVALID")

    run["volume_gal"] = Decimal("0.0")
    run["status"] = "REVERSED"
    services.touch(run)
    station = store.pump_stations.get(run["pump_station_id"])
    if station is not None:
        services.recompute_station_withdrawn(station)
        course = store.courses.get(station["course_id"])
        if course is not None:
            services.recompute_course_water(course)
    return ok(irrigation_run_out(run))
