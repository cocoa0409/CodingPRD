"""Equipment units and weather events."""

from decimal import Decimal

from flask import Blueprint

import calc
import services
from envelope import created, ok
from errors import ApiError
from serializers import equipment_out, weather_event_out
from store import clock, store
from util import dec, rhu
from validators import (bad, body, endpoint, field_dt, field_enum, field_int, field_num,
                        field_str, field_uuid, field_uuid_list, pagination, path_uuid,
                        query_bool, query_enum, query_uuid)

from routes.common import list_response

bp = Blueprint("fleet", __name__)

UNIT_TYPES = ("TRIPLEX_GREENS_MOWER", "FAIRWAY_MOWER", "SPRAYER", "AERATOR",
              "TOPDRESSER")
EQUIPMENT_STATUSES = ("IN_SERVICE", "DOWN_FOR_SERVICE", "RETIRED")
WEATHER_TYPES = ("FROST", "LIGHTNING", "HEAVY_RAIN", "STORM_DAMAGE")


# --------------------------------------------------------------------------
# equipment units
# --------------------------------------------------------------------------
@bp.post("/equipment-units")
@endpoint(("Superintendent", "EquipmentTechnician"))
def create_equipment_unit():
    payload = body()
    course_id = field_uuid(payload, "course_id")
    unit_type = field_enum(payload, "unit_type", UNIT_TYPES)
    model_year = field_int(payload, "model_year", minimum=1990, maximum=2100)
    purchase_cost = field_num(payload, "purchase_cost", exclusive_min=0)
    expected_life = field_num(payload, "expected_life_hours", exclusive_min=0)
    service_interval = field_num(payload, "service_interval_hours", exclusive_min=0)
    avg_daily_hours = field_num(payload, "avg_daily_hours", minimum=0)
    initial_hours = field_num(payload, "initial_engine_hours", required=False,
                              default=Decimal("0"), minimum=0)

    services.require(store.courses, course_id, "ERR_COURSE_NOT_FOUND")

    initial_hours = rhu(initial_hours, 1)
    record = services.base_record()
    record.update({
        "course_id": course_id,
        "replaced_by_unit_id": None,
        "unit_type": unit_type,
        "model_year": model_year,
        "purchase_cost": purchase_cost,
        "expected_life_hours": expected_life,
        "service_interval_hours": service_interval,
        "avg_daily_hours": avg_daily_hours,
        "initial_engine_hours": initial_hours,
        "engine_hours": initial_hours,
        "engine_hours_at_last_service": initial_hours,
        "hours_since_service": Decimal("0.0"),
        "replacement_score": Decimal("0.0"),
        "replacement_score_projected": Decimal("0.0"),
        "replacement_flag": False,
        "status": "IN_SERVICE",
    })
    services.rescore_equipment(record)
    store.equipment[record["id"]] = record
    return created(equipment_out(record))


@bp.get("/equipment-units")
@endpoint(("Superintendent", "Agronomist", "EquipmentTechnician"))
def list_equipment_units():
    page = pagination()
    course_id = query_uuid("course_id")
    unit_type = query_enum("unit_type", UNIT_TYPES)
    status = query_enum("status", EQUIPMENT_STATUSES)
    replaced_by = query_uuid("replaced_by_unit_id")
    replacement_flag = query_bool("replacement_flag")
    records = [
        record for record in store.equipment.values()
        if (course_id is None or record["course_id"] == course_id)
        and (unit_type is None or record["unit_type"] == unit_type)
        and (status is None or record["status"] == status)
        and (replaced_by is None or record["replaced_by_unit_id"] == replaced_by)
        and (replacement_flag is None
             or record["replacement_flag"] == replacement_flag)
    ]
    return list_response(records, equipment_out, page=page)


@bp.get("/equipment-units/<unit_id>")
@endpoint(("Superintendent", "Agronomist", "EquipmentTechnician"))
def get_equipment_unit(unit_id):
    path_uuid(unit_id, "ERR_EQUIPMENT_NOT_FOUND")
    record = services.require(store.equipment, unit_id, "ERR_EQUIPMENT_NOT_FOUND")
    return ok(equipment_out(record))


@bp.post("/equipment-units/<unit_id>/log-hours")
@endpoint(("EquipmentTechnician",))
def log_hours(unit_id):
    path_uuid(unit_id, "ERR_EQUIPMENT_NOT_FOUND")
    payload = body()
    hours_added = field_num(payload, "hours_added", exclusive_min=0)
    unit = services.require(store.equipment, unit_id, "ERR_EQUIPMENT_NOT_FOUND")
    if unit["status"] == "RETIRED":
        raise ApiError("ERR_EQUIPMENT_STATE_INVALID")

    unit["engine_hours"] = rhu(dec(unit["engine_hours"]) + hours_added, 1)
    services.recompute_engine_hours(unit)
    services.rescore_equipment(unit)
    services.touch(unit)

    if unit["status"] == "IN_SERVICE" and \
            dec(unit["hours_since_service"]) >= dec(unit["service_interval_hours"]):
        unit["status"] = "DOWN_FOR_SERVICE"
        services.touch(unit, force=True)
    return ok(equipment_out(unit))


@bp.post("/equipment-units/<unit_id>/service")
@endpoint(("EquipmentTechnician",))
def service_unit(unit_id):
    path_uuid(unit_id, "ERR_EQUIPMENT_NOT_FOUND")
    payload = body()
    field_str(payload, "service_note", required=False, max_len=2000, allow_empty=True)
    unit = services.require(store.equipment, unit_id, "ERR_EQUIPMENT_NOT_FOUND")
    if unit["status"] != "DOWN_FOR_SERVICE":
        raise ApiError("ERR_EQUIPMENT_STATE_INVALID")

    unit["engine_hours_at_last_service"] = rhu(dec(unit["engine_hours"]), 1)
    unit["hours_since_service"] = Decimal("0.0")
    services.rescore_equipment(unit)
    unit["status"] = "IN_SERVICE"
    services.touch(unit)
    return ok(equipment_out(unit))


@bp.post("/equipment-units/<unit_id>/retire")
@endpoint(("Superintendent",))
def retire_unit(unit_id):
    path_uuid(unit_id, "ERR_EQUIPMENT_NOT_FOUND")
    payload = body()
    replacement_id = field_uuid(payload, "replacement_unit_id", required=False)
    unit = services.require(store.equipment, unit_id, "ERR_EQUIPMENT_NOT_FOUND")
    replacement = None
    if replacement_id is not None:
        replacement = services.require(store.equipment, replacement_id,
                                       "ERR_EQUIPMENT_NOT_FOUND")
    if unit["status"] == "RETIRED":
        raise ApiError("ERR_EQUIPMENT_STATE_INVALID")
    if replacement is not None and replacement["status"] != "IN_SERVICE":
        raise ApiError("ERR_EQUIPMENT_STATE_INVALID")
    if replacement is not None:
        if replacement["course_id"] != unit["course_id"] or \
                replacement["unit_type"] != unit["unit_type"]:
            raise ApiError("ERR_REPLACEMENT_UNIT_TYPE_MISMATCH")

    unit["status"] = "RETIRED"
    unit["replaced_by_unit_id"] = replacement_id
    services.touch(unit)
    services.equipment_retirement_cascade(unit)
    return ok(equipment_out(unit))


# --------------------------------------------------------------------------
# weather events
# --------------------------------------------------------------------------
@bp.post("/weather-events")
@endpoint(("Superintendent",))
def declare_weather_event():
    payload = body()
    course_id = field_uuid(payload, "course_id")
    event_type = field_enum(payload, "event_type", WEATHER_TYPES)
    delay_minutes = field_int(payload, "delay_minutes", required=False, default=0,
                              minimum=0, maximum=600)
    expected_clear_at = field_dt(payload, "expected_clear_at")
    affected = field_uuid_list(payload, "affected_turf_area_ids", required=False,
                               default=[])
    expected_course_version = field_int(payload, "expected_course_version", minimum=0)

    if event_type == "FROST":
        if delay_minutes <= 0:
            bad("'delay_minutes' must be strictly greater than 0 for a FROST event.")
    elif delay_minutes != 0:
        bad("'delay_minutes' must be 0 unless the event is a FROST event.")

    if event_type == "STORM_DAMAGE":
        if not affected:
            bad("'affected_turf_area_ids' must be non-empty for a STORM_DAMAGE event.")
    elif affected:
        bad("'affected_turf_area_ids' must be empty unless the event is a "
            "STORM_DAMAGE event.")

    declared_at = clock()
    if expected_clear_at <= declared_at:
        bad("'expected_clear_at' must be strictly after the current clock reading.")

    course = services.require(store.courses, course_id, "ERR_COURSE_NOT_FOUND")
    areas = [services.require(store.turf_areas, area_id, "ERR_TURF_AREA_NOT_FOUND")
             for area_id in affected]
    if expected_course_version != int(course["version"]):
        raise ApiError("ERR_STALE_COURSE_VERSION")
    for area in areas:
        if area["course_id"] != course_id:
            raise ApiError("ERR_TASK_TURF_AREA_MISMATCH")

    record = services.base_record()
    record.update({
        "course_id": course_id,
        "event_type": event_type,
        "delay_minutes": delay_minutes,
        "expected_clear_at": expected_clear_at,
        "affected_turf_area_ids": list(affected),
        "declared_at": declared_at,
        "cleared_at": None,
        "deferred_window_count": 0,
        "status": "ACTIVE",
    })
    store.weather_events[record["id"]] = record

    services.weather_declaration_cascade(course, record)
    return created(weather_event_out(record))


@bp.post("/weather-events/<event_id>/clear")
@endpoint(("Superintendent",))
def clear_weather_event(event_id):
    path_uuid(event_id, "ERR_WEATHER_EVENT_NOT_FOUND")
    body()
    event = services.require(store.weather_events, event_id,
                             "ERR_WEATHER_EVENT_NOT_FOUND")
    if event["status"] != "ACTIVE":
        raise ApiError("ERR_WEATHER_STATE_INVALID")

    event["status"] = "CLEARED"
    event["cleared_at"] = clock()
    services.touch(event)
    course = store.courses.get(event["course_id"])
    if course is not None:
        services.weather_clear_cascade(course, event)
    return ok(weather_event_out(event))
