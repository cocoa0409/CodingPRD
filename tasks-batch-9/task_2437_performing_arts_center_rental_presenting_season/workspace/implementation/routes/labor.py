"""Union labor calls, call minimums and overtime (PRD section 3.4)."""

from flask import Blueprint

import calc
import derive
from envelope import array_response, object_response
from errors import ApiError
from helpers import auth, body, page, query_filter, req_bool, req_dt, req_int, req_num
from lookup import find_call, find_department, find_engagement
from store import public, stamp, store, touch

bp = Blueprint("labor", __name__)

ACTIVE_ROSTER_STATES = ("ESTIMATED", "WORKED")


@bp.post("/engagements/<engagement_id>/labor-calls")
def create_labor_call(engagement_id):
    auth("TechnicalDirector")
    engagement = find_engagement(engagement_id)
    data = body()

    department = None
    if data.get("union_department_id") is not None:
        department = find_department(data["union_department_id"])

    crew_size = req_int(data, "crew_size", minimum=1)
    start_raw, start_dt = req_dt(data, "call_start_utc")
    end_raw, end_dt = req_dt(data, "call_end_utc")
    if end_dt <= start_dt:
        raise ApiError(
            "ERR_INVALID_REQUEST", "Field 'call_end_utc' must be after 'call_start_utc'."
        )
    if department is None:
        raise ApiError("ERR_INVALID_REQUEST", "Field 'union_department_id' is required.")

    if start_dt < engagement["_load_in_start"] or end_dt > engagement["_load_out_end"]:
        raise ApiError("ERR_CALL_OUTSIDE_ENGAGEMENT_WINDOW")

    committed = 0
    for other in store.calls.values():
        if other["union_department_id"] != department["id"]:
            continue
        if other["status"] not in ACTIVE_ROSTER_STATES:
            continue
        if start_dt < other["_call_end"] and other["_call_start"] < end_dt:
            committed += other["crew_size"]
    if committed + crew_size > department["roster_size"]:
        raise ApiError("ERR_CREW_CAPACITY_EXCEEDED")

    scheduled_hours = calc.scheduled_hours(start_dt, end_dt)
    record = {
        "engagement_id": engagement["id"],
        "union_department_id": department["id"],
        "crew_size": crew_size,
        "call_start_utc": start_raw,
        "call_end_utc": end_raw,
        "scheduled_hours": float(scheduled_hours),
        "estimated_cost_cents": calc.labor_cost(
            department, scheduled_hours, crew_size, "ESTIMATE"
        ),
        "actual_hours": None,
        "meal_break_taken": None,
        "actual_cost_cents": 0,
        "status": "ESTIMATED",
        "_call_start": start_dt,
        "_call_end": end_dt,
    }
    stamp(record)
    store.calls[record["id"]] = record
    derive.recompute_labor_estimate(engagement)
    derive.recompute_deposit(engagement)
    return object_response(public(record), 201)


@bp.get("/engagements/<engagement_id>/labor-calls")
def list_labor_calls(engagement_id):
    auth("TechnicalDirector", "FinanceController", "ProgrammingDirector", "RentalManager")
    engagement = find_engagement(engagement_id)
    items = derive.engagement_calls(engagement["id"])
    status = query_filter("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    window, meta = page(items)
    return array_response([public(c) for c in window], meta)


@bp.post("/labor-calls/<call_id>/report-hours")
def report_hours(call_id):
    auth("TechnicalDirector")
    call = find_call(call_id)
    data = body()
    actual_hours = req_num(data, "actual_hours", minimum=0)
    meal_break_taken = req_bool(data, "meal_break_taken")

    if call["status"] != "ESTIMATED":
        raise ApiError("ERR_LABOR_CALL_INVALID_STATE")
    engagement = store.engagements.get(call["engagement_id"])
    if engagement is None or engagement["lifecycle_status"] not in ("CONFIRMED", "PERFORMED"):
        raise ApiError("ERR_ENGAGEMENT_NOT_CONFIRMED")

    department = store.departments.get(call["union_department_id"])
    call["actual_hours"] = actual_hours
    call["meal_break_taken"] = meal_break_taken
    call["actual_cost_cents"] = calc.labor_cost(
        department, actual_hours, call["crew_size"], "ACTUAL", meal_break_taken
    )
    call["status"] = "WORKED"
    touch(call)
    derive.recompute_labor_estimate(engagement)
    derive.recompute_deposit(engagement)
    return object_response(public(call))
