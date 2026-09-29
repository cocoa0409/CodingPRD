"""Agronomic plans and plan tasks."""

from decimal import Decimal

from flask import Blueprint, g

import calc
import services
from envelope import created, ok
from errors import ApiError
from serializers import plan_out, plan_task_out
from store import store
from util import dec, rhu
from validators import (bad, body, endpoint, field_dt, field_enum, field_int, field_num,
                        field_str, field_uuid, pagination, path_uuid, query_enum,
                        query_int, query_uuid)

from routes.common import list_response

bp = Blueprint("plans", __name__)

PLAN_STATUSES = ("DRAFT", "SUBMITTED", "ACTIVE", "CLOSED")
TASK_TYPES = ("FERTILITY", "AERATION", "TOPDRESSING", "PEST_CONTROL")
TASK_STATUSES = ("PLANNED", "SCHEDULED", "COMPLETED", "CANCELLED")


# --------------------------------------------------------------------------
# agronomic plans
# --------------------------------------------------------------------------
@bp.post("/agronomic-plans")
@endpoint(("Agronomist",))
def create_plan():
    payload = body()
    course_id = field_uuid(payload, "course_id")
    plan_year = field_int(payload, "plan_year", minimum=2020, maximum=2100)
    budget = field_num(payload, "nitrogen_budget_lb", exclusive_min=0)

    services.require(store.courses, course_id, "ERR_COURSE_NOT_FOUND")
    for existing in store.plans.values():
        if existing["course_id"] == course_id and existing["plan_year"] == plan_year:
            bad("That course already carries a plan for %d." % plan_year)

    record = services.base_record()
    record.update({
        "course_id": course_id,
        "plan_year": plan_year,
        "nitrogen_budget_lb": budget,
        "committed_nitrogen_lb": Decimal("0.00"),
        "status": "DRAFT",
        "return_count": 0,
        "submitted_by_user_id": None,
    })
    store.plans[record["id"]] = record
    return created(plan_out(record))


@bp.get("/agronomic-plans")
@endpoint(("Superintendent", "Agronomist"))
def list_plans():
    page = pagination()
    course_id = query_uuid("course_id")
    plan_year = query_int("plan_year")
    status = query_enum("status", PLAN_STATUSES)
    records = [
        record for record in store.plans.values()
        if (course_id is None or record["course_id"] == course_id)
        and (plan_year is None or record["plan_year"] == plan_year)
        and (status is None or record["status"] == status)
    ]
    return list_response(records, plan_out, page=page)


@bp.get("/agronomic-plans/<plan_id>")
@endpoint(("Superintendent", "Agronomist"))
def get_plan(plan_id):
    path_uuid(plan_id, "ERR_PLAN_NOT_FOUND")
    record = services.require(store.plans, plan_id, "ERR_PLAN_NOT_FOUND")
    return ok(plan_out(record))


@bp.post("/agronomic-plans/<plan_id>/submit")
@endpoint(("Agronomist",), need_user_id=True)
def submit_plan(plan_id):
    path_uuid(plan_id, "ERR_PLAN_NOT_FOUND")
    body()
    plan = services.require(store.plans, plan_id, "ERR_PLAN_NOT_FOUND")
    if plan["status"] != "DRAFT":
        raise ApiError("ERR_PLAN_STATE_INVALID")
    if not any(task["status"] == "PLANNED"
               for task in services.plan_tasks_of(plan_id)):
        raise ApiError("ERR_PLAN_STATE_INVALID",
                       "The plan carries no task in PLANNED and may not be submitted.")
    plan["status"] = "SUBMITTED"
    plan["submitted_by_user_id"] = g.user_id
    services.touch(plan)
    return ok(plan_out(plan))


@bp.post("/agronomic-plans/<plan_id>/return")
@endpoint(("Superintendent",))
def return_plan(plan_id):
    path_uuid(plan_id, "ERR_PLAN_NOT_FOUND")
    payload = body()
    field_str(payload, "return_note", required=False, max_len=2000, allow_empty=True)
    plan = services.require(store.plans, plan_id, "ERR_PLAN_NOT_FOUND")
    if plan["status"] != "SUBMITTED":
        raise ApiError("ERR_PLAN_STATE_INVALID")
    if int(plan["return_count"]) >= 2:
        raise ApiError("ERR_REVISION_LIMIT_REACHED")
    plan["status"] = "DRAFT"
    plan["return_count"] = int(plan["return_count"]) + 1
    plan["submitted_by_user_id"] = None
    services.touch(plan)
    return ok(plan_out(plan))


@bp.post("/agronomic-plans/<plan_id>/approve")
@endpoint(("Superintendent",), need_user_id=True)
def approve_plan(plan_id):
    path_uuid(plan_id, "ERR_PLAN_NOT_FOUND")
    payload = body()
    expected_version = field_int(payload, "expected_plan_version", minimum=0)
    plan = services.require(store.plans, plan_id, "ERR_PLAN_NOT_FOUND")
    if plan["status"] != "SUBMITTED":
        raise ApiError("ERR_PLAN_STATE_INVALID")
    if expected_version != int(plan["version"]):
        raise ApiError("ERR_STALE_PLAN_VERSION")
    if plan["submitted_by_user_id"] is not None and \
            plan["submitted_by_user_id"] == g.user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    plan["status"] = "ACTIVE"
    services.touch(plan)
    return ok(plan_out(plan))


# --------------------------------------------------------------------------
# plan tasks
# --------------------------------------------------------------------------
@bp.post("/plan-tasks")
@endpoint(("Agronomist",))
def create_plan_task():
    payload = body()
    plan_id = field_uuid(payload, "plan_id")
    area_id = field_uuid(payload, "turf_area_id")
    task_type = field_enum(payload, "task_type", TASK_TYPES)
    nitrogen_rate = field_num(payload, "nitrogen_lb_per_1000", required=False,
                              exclusive_min=0, maximum=6)
    if task_type == "FERTILITY":
        if nitrogen_rate is None:
            bad("'nitrogen_lb_per_1000' is required for a FERTILITY task.")
    elif nitrogen_rate is not None:
        bad("'nitrogen_lb_per_1000' must be null unless the task is FERTILITY.")
    window_start = field_dt(payload, "planned_window_start")
    window_end = field_dt(payload, "planned_window_end")
    if window_end <= window_start:
        bad("'planned_window_end' must be strictly after 'planned_window_start'.")

    area = services.require(store.turf_areas, area_id, "ERR_TURF_AREA_NOT_FOUND")
    plan = services.require(store.plans, plan_id, "ERR_PLAN_NOT_FOUND")
    if plan["status"] != "DRAFT":
        raise ApiError("ERR_PLAN_STATE_INVALID")
    if task_type == "FERTILITY":
        prospective = rhu(
            calc.turf_nitrogen_applied(area)
            + calc.turf_nitrogen_planned(area)
            + nitrogen_rate, 3)
        if prospective > calc.turf_nitrogen_ceiling(area):
            raise ApiError("ERR_NITROGEN_LOAD_LIMIT")
    if area["agronomic_status"] == "OUT_OF_PLAY":
        raise ApiError("ERR_TURF_AREA_OUT_OF_PLAY")
    if area["course_id"] != plan["course_id"]:
        raise ApiError("ERR_TASK_TURF_AREA_MISMATCH")

    record = services.base_record()
    record.update({
        "plan_id": plan_id,
        "turf_area_id": area_id,
        "task_type": task_type,
        "nitrogen_lb_per_1000": nitrogen_rate,
        "commitment_lb": calc.task_commitment_lb(task_type, nitrogen_rate,
                                                area["area_sq_ft"]),
        "planned_window_start": window_start,
        "planned_window_end": window_end,
        "status": "PLANNED",
    })
    store.plan_tasks[record["id"]] = record

    services.sync_turf_ledgers(area)
    return created(plan_task_out(record))


@bp.get("/plan-tasks")
@endpoint(("Superintendent", "Agronomist"))
def list_plan_tasks():
    page = pagination()
    plan_id = query_uuid("plan_id")
    area_id = query_uuid("turf_area_id")
    task_type = query_enum("task_type", TASK_TYPES)
    status = query_enum("status", TASK_STATUSES)
    records = [
        record for record in store.plan_tasks.values()
        if (plan_id is None or record["plan_id"] == plan_id)
        and (area_id is None or record["turf_area_id"] == area_id)
        and (task_type is None or record["task_type"] == task_type)
        and (status is None or record["status"] == status)
    ]
    return list_response(records, plan_task_out, page=page)


@bp.get("/plan-tasks/<task_id>")
@endpoint(("Superintendent", "Agronomist"))
def get_plan_task(task_id):
    path_uuid(task_id, "ERR_PLAN_TASK_NOT_FOUND")
    record = services.require(store.plan_tasks, task_id, "ERR_PLAN_TASK_NOT_FOUND")
    return ok(plan_task_out(record))


@bp.post("/plan-tasks/<task_id>/schedule")
@endpoint(("Agronomist",))
def schedule_plan_task(task_id):
    path_uuid(task_id, "ERR_PLAN_TASK_NOT_FOUND")
    payload = body()
    window_id = field_uuid(payload, "maintenance_window_id")
    expected_version = field_int(payload, "expected_plan_version", minimum=0)

    task = services.require(store.plan_tasks, task_id, "ERR_PLAN_TASK_NOT_FOUND")
    window = services.require(store.windows, window_id, "ERR_WINDOW_NOT_FOUND")
    plan = services.require(store.plans, task["plan_id"], "ERR_PLAN_NOT_FOUND")
    if plan["status"] != "ACTIVE":
        raise ApiError("ERR_PLAN_STATE_INVALID")
    if task["status"] != "PLANNED":
        raise ApiError("ERR_TASK_STATE_INVALID")
    if window["status"] != "SCHEDULED" or window["plan_task_id"] is not None:
        raise ApiError("ERR_WINDOW_STATE_INVALID")
    if expected_version != int(plan["version"]):
        raise ApiError("ERR_STALE_PLAN_VERSION")
    if window["turf_area_id"] != task["turf_area_id"]:
        raise ApiError("ERR_TASK_TURF_AREA_MISMATCH")
    if window["window_start"] < task["planned_window_start"] or \
            window["window_end"] > task["planned_window_end"]:
        raise ApiError("ERR_APPLICATION_OUTSIDE_PLAN_WINDOW")
    prospective = rhu(dec(plan["committed_nitrogen_lb"]) + dec(task["commitment_lb"]), 2)
    if prospective > dec(plan["nitrogen_budget_lb"]):
        raise ApiError("ERR_NITROGEN_BUDGET_EXCEEDED")

    window["plan_task_id"] = task["id"]
    services.touch(window)
    task["status"] = "SCHEDULED"
    services.touch(task)
    services.recompute_plan_ledger(plan)
    area = store.turf_areas.get(task["turf_area_id"])
    if area is not None:
        services.recompute_turf_nitrogen(area)
        services.touch(area)
    return ok(plan_task_out(task))
