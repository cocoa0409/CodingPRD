"""Emergency-response drills: 24h quiet gap at scheduling, training quorum at
conduct (PRD 3.5, calculations.drill_gap_check)."""
from flask import Blueprint

import calc
import envelope
from errors import ApiError
from guards import (
    ALL_ROLES,
    apply_filters,
    body_row,
    endpoint,
    paginate,
    pagination,
    path_row,
    req_enum,
    req_instant,
    req_str_list,
)
from serialize import drill_out
from store import db, sorted_rows, touch

bp = Blueprint("drills", __name__)

CREATE_SCHEMA = (
    frozenset(["facility_id", "drill_type", "scheduled_start_at", "scheduled_end_at"]),
    frozenset(["facility_id", "drill_type", "scheduled_start_at", "scheduled_end_at"]),
)
CONDUCT_SCHEMA = (
    frozenset(["attendee_employee_ids"]),
    frozenset(["attendee_employee_ids"]),
)

STATUS_VALUES = ("PLANNED", "CONDUCTED")


@bp.post("/psm/drill-events")
@endpoint(["PsCoordinator"], schema=CREATE_SCHEMA)
def create_drill(ctx):
    drill_type = req_enum(ctx.body, "drill_type")
    start = req_instant(ctx.body, "scheduled_start_at")
    end = req_instant(ctx.body, "scheduled_end_at")
    facility = body_row(ctx.body, "facilities", "facility_id")
    # step 7 -- window sanity: the end must come strictly after the start
    if start >= end:
        raise ApiError("ERR_INVALID_WINDOW")
    # step 8 -- 24h quiet gap against every PLANNED/CONDUCTED drill of the facility
    if calc.drill_gap_conflicts(facility["id"], start, end):
        raise ApiError("ERR_DRILL_GAP_VIOLATION")
    row = db.create(
        "drill_events",
        {
            "facility_id": facility["id"],
            "drill_type": drill_type,
            "scheduled_start_at": start,
            "scheduled_end_at": end,
            "status": "PLANNED",
            "attendee_employee_ids": None,
            "conducted_at": None,
        },
    )
    return envelope.created(drill_out(row))


@bp.get("/psm/drill-events/<drill_id>")
@endpoint(ALL_ROLES)
def get_drill(ctx, drill_id):
    return envelope.ok(drill_out(path_row("drill_events", drill_id)))


@bp.get("/psm/drill-events")
@endpoint(ALL_ROLES)
def list_drills(ctx):
    limit, offset = pagination(ctx)
    rows = sorted_rows(db.drill_events.values())
    rows = apply_filters(
        rows,
        ctx,
        [
            ("facility_id", "facility_id", None),
            ("status", "status", STATUS_VALUES),
        ],
    )
    total = len(rows)
    return envelope.listing(
        [drill_out(r) for r in paginate(rows, limit, offset)], limit, offset, total
    )


@bp.post("/psm/drill-events/<drill_id>/conduct")
@endpoint(["PsCoordinator"], schema=CONDUCT_SCHEMA)
def conduct_drill(ctx, drill_id):
    # step 0 -- payload shape
    attendee_ids = req_str_list(ctx.body, "attendee_employee_ids")
    # step 3 -- the drill and every roster entry resolve to real records
    drill = path_row("drill_events", drill_id)
    attendees = []
    for employee_id in attendee_ids:
        employee = db.employees.get(employee_id)
        if employee is None:
            raise ApiError(
                "ERR_NOT_FOUND", "Field 'attendee_employee_ids' references no existing record."
            )
        attendees.append(employee)
    # step 5 -- PLANNED only
    if drill["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_STATE")
    # step 6 -- training quorum: at least 2 distinct attendees hold
    # non-expired AMMONIA_OPERATOR training at conduct time
    qualified = {
        employee["id"] for employee in attendees if calc.has_current_ammonia_training(employee["id"])
    }
    if len(qualified) < 2:
        raise ApiError("ERR_DRILL_TRAINING_SHORTFALL")
    # step 9 -- every attendee is an ACTIVE employee of the drill's facility
    for employee in attendees:
        if (
            employee["facility_id"] != drill["facility_id"]
            or employee["employment_status"] != "ACTIVE"
        ):
            raise ApiError("ERR_CROSS_FACILITY_REFERENCE")
    drill["status"] = "CONDUCTED"
    drill["attendee_employee_ids"] = list(attendee_ids)
    drill["conducted_at"] = db.now()
    touch(drill)
    return envelope.ok(drill_out(drill))
