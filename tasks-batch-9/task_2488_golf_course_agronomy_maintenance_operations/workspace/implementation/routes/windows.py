"""Crew maintenance windows and play events."""

from decimal import Decimal

from flask import Blueprint

import calc
import services
from envelope import created, ok
from errors import ApiError
from serializers import play_event_out, window_out
from store import clock, store
from util import dec, rhu, whole_minutes
from validators import (bad, body, endpoint, field_dt, field_enum, field_int, field_num,
                        field_uuid, pagination, path_uuid, query_enum, query_uuid)

from routes.common import list_response

bp = Blueprint("windows", __name__)

WINDOW_TASK_TYPES = ("FERTILITY", "AERATION", "TOPDRESSING", "PEST_CONTROL", "MOWING",
                     "STORM_CLEANUP")
UNIT_TYPES = ("TRIPLEX_GREENS_MOWER", "FAIRWAY_MOWER", "SPRAYER", "AERATOR",
              "TOPDRESSER")
WINDOW_STATUSES = ("SCHEDULED", "DEFERRED", "IN_PROGRESS", "COMPLETED", "CANCELLED")
PLAY_EVENT_TYPES = ("STANDARD_TEE_TIMES", "SHOTGUN_START", "TOURNAMENT_ROUND")
PLAY_STATUSES = ("SCHEDULED", "DELAYED", "CANCELLED")
READINESS_STATUSES = ("PENDING", "CERTIFIED", "FAILED")


def _crew_hours(crew_size, duration_minutes):
    return rhu(dec(crew_size) * dec(duration_minutes) / Decimal(60), 2)


def _validate_window_interval(start, end):
    duration = whole_minutes(start, end)
    if duration is None:
        bad("'window_end' must be strictly after 'window_start' by a whole number "
            "of minutes.")
    if duration < 1 or duration > 600:
        bad("A crew window must be from 1 through 600 minutes.")
    return duration


# --------------------------------------------------------------------------
# maintenance windows
# --------------------------------------------------------------------------
@bp.post("/maintenance-windows")
@endpoint(("Agronomist",))
def create_window():
    payload = body()
    course_id = field_uuid(payload, "course_id")
    area_id = field_uuid(payload, "turf_area_id")
    task_id = field_uuid(payload, "plan_task_id", required=False)
    task_type = field_enum(payload, "task_type", WINDOW_TASK_TYPES)
    window_start = field_dt(payload, "window_start")
    window_end = field_dt(payload, "window_end")
    duration = _validate_window_interval(window_start, window_end)
    crew_size = field_int(payload, "crew_size", minimum=1, maximum=40)
    required_unit_type = field_enum(payload, "required_unit_type", UNIT_TYPES,
                                    required=False)

    services.require(store.courses, course_id, "ERR_COURSE_NOT_FOUND")
    area = services.require(store.turf_areas, area_id, "ERR_TURF_AREA_NOT_FOUND")
    if task_id is not None:
        services.require(store.plan_tasks, task_id, "ERR_PLAN_TASK_NOT_FOUND")

    if task_type != "STORM_CLEANUP" and area["rei_expires_at"] is not None:
        if window_start < area["rei_expires_at"]:
            raise ApiError("ERR_REI_ACTIVE")
    if area["course_id"] != course_id:
        raise ApiError("ERR_TASK_TURF_AREA_MISMATCH")
    if services.window_overlap_conflict(area_id, window_start, window_end):
        raise ApiError("ERR_WINDOW_OVERLAP")
    if services.window_play_conflict(course_id, area["hole_number"], window_start,
                                     window_end):
        raise ApiError("ERR_WINDOW_CONFLICTS_PLAY")

    record = services.base_record()
    record.update({
        "course_id": course_id,
        "turf_area_id": area_id,
        "plan_task_id": None,
        "task_type": task_type,
        "window_start": window_start,
        "window_end": window_end,
        "crew_size": crew_size,
        "required_unit_type": required_unit_type,
        "crew_hours": _crew_hours(crew_size, duration),
        "status": "SCHEDULED",
        "deferral_count": 0,
    })
    store.windows[record["id"]] = record
    return created(window_out(record))


@bp.get("/maintenance-windows")
@endpoint(("Superintendent", "Agronomist", "EquipmentTechnician"))
def list_windows():
    page = pagination()
    course_id = query_uuid("course_id")
    area_id = query_uuid("turf_area_id")
    task_id = query_uuid("plan_task_id")
    task_type = query_enum("task_type", WINDOW_TASK_TYPES)
    status = query_enum("status", WINDOW_STATUSES)
    records = [
        record for record in store.windows.values()
        if (course_id is None or record["course_id"] == course_id)
        and (area_id is None or record["turf_area_id"] == area_id)
        and (task_id is None or record["plan_task_id"] == task_id)
        and (task_type is None or record["task_type"] == task_type)
        and (status is None or record["status"] == status)
    ]
    return list_response(records, window_out, page=page)


@bp.get("/maintenance-windows/<window_id>")
@endpoint(("Superintendent", "Agronomist", "EquipmentTechnician"))
def get_window(window_id):
    path_uuid(window_id, "ERR_WINDOW_NOT_FOUND")
    record = services.require(store.windows, window_id, "ERR_WINDOW_NOT_FOUND")
    return ok(window_out(record))


@bp.post("/maintenance-windows/<window_id>/start")
@endpoint(("Agronomist",))
def start_window(window_id):
    path_uuid(window_id, "ERR_WINDOW_NOT_FOUND")
    body()
    window = services.require(store.windows, window_id, "ERR_WINDOW_NOT_FOUND")
    if window["status"] != "SCHEDULED":
        raise ApiError("ERR_WINDOW_STATE_INVALID")
    area = store.turf_areas.get(window["turf_area_id"])
    exempt = window["task_type"] == "STORM_CLEANUP"
    if not exempt and area is not None and area["rei_expires_at"] is not None:
        if clock() < area["rei_expires_at"]:
            raise ApiError("ERR_REI_ACTIVE")
    course = store.courses.get(window["course_id"])
    if not exempt and course is not None and course["play_posture"] == "CLOSED":
        raise ApiError("ERR_COURSE_CLOSED")
    if not exempt and area is not None and area["agronomic_status"] == "OUT_OF_PLAY":
        raise ApiError("ERR_TURF_AREA_OUT_OF_PLAY")

    window["status"] = "IN_PROGRESS"
    services.touch(window)
    if window["task_type"] == "AERATION" and area is not None:
        if area["agronomic_status"] != "UNDER_RENOVATION":
            area["agronomic_status"] = "UNDER_RENOVATION"
            services.touch(area)
    return ok(window_out(window))


@bp.post("/maintenance-windows/<window_id>/complete")
@endpoint(("Agronomist",))
def complete_window(window_id):
    path_uuid(window_id, "ERR_WINDOW_NOT_FOUND")
    body()
    window = services.require(store.windows, window_id, "ERR_WINDOW_NOT_FOUND")
    if window["status"] != "IN_PROGRESS":
        raise ApiError("ERR_WINDOW_STATE_INVALID")

    window["status"] = "COMPLETED"
    services.touch(window)
    area = store.turf_areas.get(window["turf_area_id"])
    if window["task_type"] == "AERATION" and area is not None:
        if area["agronomic_status"] == "UNDER_RENOVATION":
            area["agronomic_status"] = "ACTIVE"
            services.touch(area)
    task_id = window.get("plan_task_id")
    if task_id:
        task = store.plan_tasks.get(task_id)
        if task is not None and task["status"] == "SCHEDULED":
            services.complete_task(task)
    return ok(window_out(window))


@bp.post("/maintenance-windows/<window_id>/reschedule")
@endpoint(("Agronomist",))
def reschedule_window(window_id):
    path_uuid(window_id, "ERR_WINDOW_NOT_FOUND")
    payload = body()
    window_start = field_dt(payload, "window_start")
    window_end = field_dt(payload, "window_end")
    duration = _validate_window_interval(window_start, window_end)
    crew_size = field_int(payload, "crew_size", required=False, minimum=1, maximum=40)

    window = services.require(store.windows, window_id, "ERR_WINDOW_NOT_FOUND")
    if window["status"] not in ("SCHEDULED", "DEFERRED"):
        raise ApiError("ERR_WINDOW_STATE_INVALID")

    area = store.turf_areas.get(window["turf_area_id"])
    exempt = window["task_type"] == "STORM_CLEANUP"
    if not exempt and area is not None and area["rei_expires_at"] is not None:
        if window_start < area["rei_expires_at"]:
            raise ApiError("ERR_REI_ACTIVE")
    course = store.courses.get(window["course_id"])
    if not exempt and course is not None and course["play_posture"] == "CLOSED":
        raise ApiError("ERR_COURSE_CLOSED")
    if not exempt and area is not None and area["agronomic_status"] == "OUT_OF_PLAY":
        raise ApiError("ERR_TURF_AREA_OUT_OF_PLAY")
    if services.window_overlap_conflict(window["turf_area_id"], window_start,
                                        window_end, exclude_id=window_id):
        raise ApiError("ERR_WINDOW_OVERLAP")
    hole_number = area["hole_number"] if area is not None else None
    if services.window_play_conflict(window["course_id"], hole_number, window_start,
                                     window_end):
        raise ApiError("ERR_WINDOW_CONFLICTS_PLAY")
    if window["status"] == "DEFERRED" and int(window["deferral_count"]) >= 2:
        raise ApiError("ERR_DEFERRAL_LIMIT_REACHED")

    task = None
    task_id = window.get("plan_task_id")
    if task_id:
        task = store.plan_tasks.get(task_id)
    if task is not None:
        plan = store.plans.get(task["plan_id"])
        if plan is not None:
            if plan["status"] != "ACTIVE":
                raise ApiError("ERR_PLAN_STATE_INVALID")
            restored = dec(plan["committed_nitrogen_lb"])
            if task["status"] == "PLANNED":
                restored = rhu(restored + dec(task["commitment_lb"]), 2)
            if restored > dec(plan["nitrogen_budget_lb"]):
                raise ApiError("ERR_NITROGEN_BUDGET_EXCEEDED")

    window["window_start"] = window_start
    window["window_end"] = window_end
    if crew_size is not None:
        window["crew_size"] = crew_size
    window["crew_hours"] = _crew_hours(window["crew_size"], duration)
    window["status"] = "SCHEDULED"
    services.touch(window)
    if task is not None and task["status"] == "PLANNED":
        services.advance_task_to_scheduled(task)
    return ok(window_out(window))


# --------------------------------------------------------------------------
# play events
# --------------------------------------------------------------------------
@bp.post("/play-events")
@endpoint(("TournamentOfficial", "Superintendent"))
def create_play_event():
    payload = body()
    course_id = field_uuid(payload, "course_id")
    event_type = field_enum(payload, "event_type", PLAY_EVENT_TYPES)
    start_at = field_dt(payload, "start_at")
    end_at = field_dt(payload, "end_at")
    if end_at <= start_at:
        bad("'end_at' must be strictly after 'start_at'.")
    holes_in_play = field_int(payload, "holes_in_play")
    if holes_in_play not in (9, 18):
        bad("'holes_in_play' must be exactly 9 or exactly 18.")
    field_size = field_int(payload, "field_size", minimum=1, maximum=288)

    services.require(store.courses, course_id, "ERR_COURSE_NOT_FOUND")

    record = services.base_record()
    record.update({
        "course_id": course_id,
        "event_type": event_type,
        "start_at": start_at,
        "end_at": end_at,
        "holes_in_play": holes_in_play,
        "field_size": field_size,
        "delayed_minutes": 0,
        "effective_start_at": start_at,
        "readiness_index": None,
        "readiness_status": "PENDING",
        "status": "SCHEDULED",
    })
    store.play_events[record["id"]] = record
    return created(play_event_out(record))


@bp.get("/play-events")
@endpoint(("Superintendent", "Agronomist", "TournamentOfficial"))
def list_play_events():
    page = pagination()
    course_id = query_uuid("course_id")
    event_type = query_enum("event_type", PLAY_EVENT_TYPES)
    status = query_enum("status", PLAY_STATUSES)
    readiness_status = query_enum("readiness_status", READINESS_STATUSES)
    records = [
        record for record in store.play_events.values()
        if (course_id is None or record["course_id"] == course_id)
        and (event_type is None or record["event_type"] == event_type)
        and (status is None or record["status"] == status)
        and (readiness_status is None
             or record["readiness_status"] == readiness_status)
    ]
    return list_response(records, play_event_out, page=page)


@bp.get("/play-events/<event_id>")
@endpoint(("Superintendent", "Agronomist", "TournamentOfficial"))
def get_play_event(event_id):
    path_uuid(event_id, "ERR_PLAY_EVENT_NOT_FOUND")
    record = services.require(store.play_events, event_id, "ERR_PLAY_EVENT_NOT_FOUND")
    return ok(play_event_out(record))


@bp.post("/play-events/<event_id>/certify-conditions")
@endpoint(("TournamentOfficial",))
def certify_conditions(event_id):
    path_uuid(event_id, "ERR_PLAY_EVENT_NOT_FOUND")
    body()
    event = services.require(store.play_events, event_id, "ERR_PLAY_EVENT_NOT_FOUND")
    if event["status"] == "CANCELLED":
        raise ApiError("ERR_PLAY_EVENT_STATE_INVALID")
    course = store.courses.get(event["course_id"])
    if course is not None and course["play_posture"] == "CLOSED":
        raise ApiError("ERR_COURSE_CLOSED")

    readiness_index, readiness_status, _ = calc.tournament_readiness_index(event)
    event["readiness_index"] = readiness_index
    event["readiness_status"] = readiness_status
    services.touch(event)
    return ok(play_event_out(event))
