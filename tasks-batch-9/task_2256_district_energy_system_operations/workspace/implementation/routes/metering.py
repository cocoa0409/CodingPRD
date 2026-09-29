"""MeteringPoint and MeterReading endpoints (PRD 3.6)."""

from flask import Blueprint

import enums
import services as svc
from calc import D, f, r3
from db import base_record, store, touch
from errors import fail
from middleware import Page, endpoint, paginate, pagination_args
from validators import (get_dt, get_enum, get_num, get_str, json_body, present,
                        query_enum, query_str)

bp = Blueprint("metering", __name__, url_prefix="/district-energy")

POINT_READERS = ("SystemController", "NetworkEngineer", "FieldTechnician",
                 "BillingAnalyst")
POINT_GET_READERS = POINT_READERS + ("CustomerAccount",)


@endpoint(bp, "/metering-points", ["POST"], ["FieldTechnician"], status=201)
def create_point():
    body = json_body()
    agreement_id = get_str(body, "agreement_id")
    segment_id = get_str(body, "segment_id")
    code = get_str(body, "code")
    multiplier = get_num(body, "multiplier", required=False, default=1.0, gt=0)

    agreement = svc.fk_get("agreements", agreement_id)
    segment = svc.fk_get("segments", segment_id)

    svc.require_unique_code("points", "code", code)

    if segment["loop_id"] != agreement["loop_id"]:
        fail("ERR_SEGMENT_LOOP_MISMATCH",
             "the segment and the agreement sit on different loops")

    point = base_record()
    point.update({
        "agreement_id": agreement["id"],
        "segment_id": segment["id"],
        "code": code,
        "multiplier": multiplier,
        "last_reading_energy_mwh": 0.0,
        "reading_count": 0,
        "meter_state": "INSTALLED",
    })
    store.points[point["id"]] = point
    return point


@endpoint(bp, "/metering-points", ["GET"], POINT_READERS)
def list_points():
    filters = {}
    agreement_id = query_str("agreement_id")
    segment_id = query_str("segment_id")
    meter_state = query_enum("meter_state", enums.METER_STATE)
    if agreement_id is not None:
        filters["agreement_id"] = agreement_id
    if segment_id is not None:
        filters["segment_id"] = segment_id
    if meter_state is not None:
        filters["meter_state"] = meter_state
    return paginate(svc.where("points", **filters))


@endpoint(bp, "/metering-points/<point_id>", ["GET"], POINT_GET_READERS)
def get_point(point_id):
    return svc.path_get("points", point_id)


@endpoint(bp, "/metering-points/<point_id>/commission", ["POST"], ["FieldTechnician"])
def commission_point(point_id):
    point = svc.path_get("points", point_id)
    if point["meter_state"] != "INSTALLED":
        fail("ERR_METER_STATE_INVALID",
             "only an INSTALLED meter can be commissioned")
    segment = store.segments.get(point["segment_id"])
    if segment is not None and segment["condition"] == "UNDER_REPAIR":
        fail("ERR_METER_STATE_INVALID",
             "the meter's segment is UNDER_REPAIR")
    point["meter_state"] = "COMMISSIONED"
    touch(point)
    return point


@endpoint(bp, "/metering-points/<point_id>/remove", ["POST"], ["FieldTechnician"])
def remove_point(point_id):
    body = json_body()
    if present(body, "reason"):
        get_str(body, "reason", min_len=0)

    point = svc.path_get("points", point_id)
    if point["meter_state"] not in ("INSTALLED", "COMMISSIONED"):
        fail("ERR_METER_STATE_INVALID",
             "a REMOVED meter cannot be removed again")
    point["meter_state"] = "REMOVED"
    touch(point)
    return point


def point_readings(point_id):
    items = [r for r in store.readings.values() if r["point_id"] == point_id]
    items.sort(key=lambda r: (r["_read_at"], r["created_at"], r["_seq"]))
    return items


@endpoint(bp, "/metering-points/<point_id>/readings", ["POST"], ["FieldTechnician"],
          status=201)
def create_reading(point_id):
    body = json_body()
    read_raw, read_dt = get_dt(body, "read_at")
    cumulative = get_num(body, "cumulative_energy_mwh", ge=0)
    peak_demand_kw = get_num(body, "peak_demand_kw", ge=0)
    read_type = get_enum(body, "read_type", enums.READ_TYPE)

    point = svc.path_get("points", point_id)
    if point["meter_state"] != "COMMISSIONED":
        fail("ERR_METER_STATE_INVALID",
             "only a COMMISSIONED meter can record readings")

    if D(cumulative) < D(point["last_reading_energy_mwh"]):
        fail("ERR_READING_NOT_MONOTONIC",
             "cumulative_energy_mwh goes backwards for this meter")
    existing = point_readings(point["id"])
    if existing and read_dt <= existing[-1]["_read_at"]:
        fail("ERR_READING_NOT_MONOTONIC",
             "read_at must be strictly after the newest reading for this meter")

    reading = base_record(versioned=False)
    reading.update({
        "point_id": point["id"],
        "read_at": read_raw,
        "_read_at": read_dt,
        "cumulative_energy_mwh": cumulative,
        "peak_demand_kw": peak_demand_kw,
        "read_type": read_type,
        "multiplied_energy_mwh": f(r3(D(cumulative) * D(point["multiplier"]))),
    })
    store.readings[reading["id"]] = reading

    point["last_reading_energy_mwh"] = cumulative
    point["reading_count"] = point["reading_count"] + 1
    touch(point)
    return reading


@endpoint(bp, "/metering-points/<point_id>/readings", ["GET"], POINT_GET_READERS)
def list_point_readings(point_id):
    # Query validation (ladder step 3) precedes the path lookup (step 4).
    limit, offset = pagination_args()
    read_type = query_enum("read_type", enums.READ_TYPE)

    point = svc.path_get("points", point_id)
    items = point_readings(point["id"])
    if read_type is not None:
        items = [r for r in items if r["read_type"] == read_type]
    total = len(items)
    window = items[offset:offset + limit]
    return Page(window, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(window) < total,
    })


@endpoint(bp, "/meter-readings", ["GET"], POINT_READERS)
def list_readings():
    filters = {}
    point_id = query_str("point_id")
    read_type = query_enum("read_type", enums.READ_TYPE)
    if point_id is not None:
        filters["point_id"] = point_id
    if read_type is not None:
        filters["read_type"] = read_type
    return paginate(svc.where("readings", **filters))


@endpoint(bp, "/meter-readings/<reading_id>", ["GET"], POINT_READERS)
def get_reading(reading_id):
    return svc.path_get("readings", reading_id)
