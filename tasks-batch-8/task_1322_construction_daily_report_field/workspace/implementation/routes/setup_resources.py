"""Projects, work areas, delivery zones, work items, logical clock."""
from decimal import Decimal
from flask import Blueprint, request

from auth import ctx, need, ALL_ROLES
from calc import touch, project_percents
from db import store
from envelope import success
from errors import ApiError
from route_helpers import stamp, list_response
from serializers import (
    ser_project,
    ser_work_area,
    ser_delivery_zone,
    ser_work_item,
)
from util import fmt_dt, parse_dt
from validate import (
    body,
    req_str,
    opt_str,
    opt_int,
    req_int,
    req_num,
    req_enum,
    opt_hhmm,
    req_dt,
    bad,
)
from clock import clock

bp = Blueprint("setup", __name__)

UNITS = ("LF", "SF", "CY", "EA", "TON", "GAL")
PROJECT_STATUSES = ("MOBILIZING", "ACTIVE", "SUSPENDED", "CLOSED")
OPEN_CLOSED = ("OPEN", "CLOSED")
WORK_ITEM_STATUSES = ("NOT_STARTED", "IN_PROGRESS", "COMPLETE")


def get_project(pid):
    p = store.projects.get(pid)
    if p is None:
        raise ApiError("ERR_PROJECT_NOT_FOUND", 404, "Project not found")
    return p


# ---------------------------------------------------------------------------
# logical clock
# ---------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_clock():
    ctx_uid, role = ctx()
    need(role, ["SystemAdmin"])
    b = body()
    to = req_dt(b, "to_iso8601")
    clock.set(to)
    # notification_overdue recomputes on read against the logical clock
    return success({"current_utc": fmt_dt(clock.now())}, 200)


# ---------------------------------------------------------------------------
# projects
# ---------------------------------------------------------------------------

@bp.post("/projects")
def create_project():
    _, role = ctx()
    need(role, ["SystemAdmin"])
    b = body()
    name = req_str(b, "name")
    contract = req_str(b, "contract_number")
    shift_start = opt_hhmm(b, "scheduled_shift_start", "07:00")
    shift_hours = req_num(b, "scheduled_shift_hours", gt=Decimal(0), mx=Decimal(24)) if (
        "scheduled_shift_hours" in b and b["scheduled_shift_hours"] is not None
    ) else Decimal(8)
    retention = opt_int(b, "retention_days", 2555)
    # uniqueness (8.2): contract_number globally unique
    for p in store.projects.values():
        if p["contract_number"] == contract:
            raise ApiError(
                "ERR_DUPLICATE_CONTRACT_NUMBER", 409, "contract_number already exists"
            )
    rec = stamp(
        {
            "name": name,
            "contract_number": contract,
            "scheduled_shift_start": shift_start,
            "scheduled_shift_hours": shift_hours,
            "retention_days": retention,
            "status": "MOBILIZING",
        }
    )
    store.projects[rec["id"]] = rec
    return success(ser_project(rec), 201)


@bp.get("/projects/<pid>")
def get_one_project(pid):
    ctx()
    return success(ser_project(get_project(pid)), 200)


@bp.get("/projects")
def list_projects():
    ctx()
    status = request.args.get("status")
    if status is not None and status not in PROJECT_STATUSES:
        bad("Invalid status filter")
    rows = list(store.projects.values())
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return list_response(rows, ser_project)


def _project_transition(pid, from_states, to_state):
    _, role = ctx()
    need(role, ["SystemAdmin"])
    p = get_project(pid)
    if p["status"] not in from_states:
        raise ApiError(
            "ERR_PROJECT_INVALID_TRANSITION",
            409,
            "Project status does not allow this transition",
        )
    if to_state == "CLOSED":
        for r in store.daily_reports.values():
            if r["project_id"] == p["id"] and r["status"] != "LOCKED":
                raise ApiError(
                    "ERR_PROJECT_HAS_OPEN_REPORTS",
                    409,
                    "All daily reports must be LOCKED before close",
                )
    p["status"] = to_state
    touch(p)
    return success(ser_project(p), 200)


@bp.post("/projects/<pid>/activate")
def activate_project(pid):
    return _project_transition(pid, ("MOBILIZING",), "ACTIVE")


@bp.post("/projects/<pid>/suspend")
def suspend_project(pid):
    return _project_transition(pid, ("ACTIVE",), "SUSPENDED")


@bp.post("/projects/<pid>/resume")
def resume_project(pid):
    return _project_transition(pid, ("SUSPENDED",), "ACTIVE")


@bp.post("/projects/<pid>/close")
def close_project(pid):
    return _project_transition(pid, ("ACTIVE", "SUSPENDED"), "CLOSED")


@bp.get("/projects/<pid>/progress-summary")
def progress_summary(pid):
    ctx()
    p = get_project(pid)
    units, cost, count = project_percents(p["id"])
    from util import out_num

    return success(
        {
            "project_id": p["id"],
            "units_based_pct": out_num(units),
            "cost_weighted_pct": out_num(cost),
            "work_item_count": count,
        },
        200,
    )


# ---------------------------------------------------------------------------
# work areas
# ---------------------------------------------------------------------------

def get_work_area(aid):
    a = store.work_areas.get(aid)
    if a is None:
        raise ApiError("ERR_WORK_AREA_NOT_FOUND", 404, "WorkArea not found")
    return a


@bp.post("/work-areas")
def create_work_area():
    _, role = ctx()
    need(role, ["SystemAdmin"])
    b = body()
    project_id = req_str(b, "project_id")
    code = req_str(b, "code")
    description = opt_str(b, "description")
    get_project(project_id)  # body FK existence
    for a in store.work_areas.values():
        if a["project_id"] == project_id and a["code"] == code:
            raise ApiError(
                "ERR_DUPLICATE_WORK_AREA_CODE", 409, "code already exists in project"
            )
    rec = stamp(
        {
            "project_id": project_id,
            "code": code,
            "description": description,
            "status": "OPEN",
        }
    )
    store.work_areas[rec["id"]] = rec
    return success(ser_work_area(rec), 201)


@bp.get("/work-areas/<aid>")
def get_one_work_area(aid):
    ctx()
    return success(ser_work_area(get_work_area(aid)), 200)


@bp.get("/work-areas")
def list_work_areas():
    ctx()
    project_id = request.args.get("project_id")
    status = request.args.get("status")
    if status is not None and status not in OPEN_CLOSED:
        bad("Invalid status filter")
    rows = list(store.work_areas.values())
    if project_id is not None:
        rows = [r for r in rows if r["project_id"] == project_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return list_response(rows, ser_work_area)


def _area_transition(aid, from_state, to_state):
    _, role = ctx()
    need(role, ["SystemAdmin"])
    a = get_work_area(aid)
    if a["status"] != from_state:
        raise ApiError(
            "ERR_WORK_AREA_INVALID_TRANSITION", 409, "WorkArea transition not allowed"
        )
    a["status"] = to_state
    touch(a)
    return success(ser_work_area(a), 200)


@bp.post("/work-areas/<aid>/close")
def close_work_area(aid):
    return _area_transition(aid, "OPEN", "CLOSED")


@bp.post("/work-areas/<aid>/reopen")
def reopen_work_area(aid):
    return _area_transition(aid, "CLOSED", "OPEN")


# ---------------------------------------------------------------------------
# delivery zones
# ---------------------------------------------------------------------------

def get_zone(zid):
    z = store.delivery_zones.get(zid)
    if z is None:
        raise ApiError("ERR_DELIVERY_ZONE_NOT_FOUND", 404, "DeliveryZone not found")
    return z


@bp.post("/delivery-zones")
def create_zone():
    _, role = ctx()
    need(role, ["SystemAdmin"])
    b = body()
    project_id = req_str(b, "project_id")
    zone_code = req_str(b, "zone_code")
    buffer_minutes = opt_int(b, "buffer_minutes", 30, mn=0)
    get_project(project_id)
    for z in store.delivery_zones.values():
        if z["project_id"] == project_id and z["zone_code"] == zone_code:
            raise ApiError(
                "ERR_DUPLICATE_ZONE_CODE", 409, "zone_code already exists in project"
            )
    rec = stamp(
        {
            "project_id": project_id,
            "zone_code": zone_code,
            "buffer_minutes": buffer_minutes,
            "status": "OPEN",
        }
    )
    store.delivery_zones[rec["id"]] = rec
    return success(ser_delivery_zone(rec), 201)


@bp.get("/delivery-zones/<zid>")
def get_one_zone(zid):
    ctx()
    return success(ser_delivery_zone(get_zone(zid)), 200)


@bp.get("/delivery-zones")
def list_zones():
    ctx()
    project_id = request.args.get("project_id")
    status = request.args.get("status")
    if status is not None and status not in OPEN_CLOSED:
        bad("Invalid status filter")
    rows = list(store.delivery_zones.values())
    if project_id is not None:
        rows = [r for r in rows if r["project_id"] == project_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return list_response(rows, ser_delivery_zone)


def _zone_transition(zid, from_state, to_state):
    _, role = ctx()
    need(role, ["SystemAdmin"])
    z = get_zone(zid)
    if z["status"] != from_state:
        raise ApiError(
            "ERR_ZONE_INVALID_TRANSITION", 409, "DeliveryZone transition not allowed"
        )
    z["status"] = to_state
    touch(z)
    return success(ser_delivery_zone(z), 200)


@bp.post("/delivery-zones/<zid>/close")
def close_zone(zid):
    return _zone_transition(zid, "OPEN", "CLOSED")


@bp.post("/delivery-zones/<zid>/reopen")
def reopen_zone(zid):
    return _zone_transition(zid, "CLOSED", "OPEN")


# ---------------------------------------------------------------------------
# work items
# ---------------------------------------------------------------------------

def get_work_item(wid):
    w = store.work_items.get(wid)
    if w is None:
        raise ApiError("ERR_WORK_ITEM_NOT_FOUND", 404, "WorkItem not found")
    return w


@bp.post("/work-items")
def create_work_item():
    _, role = ctx()
    need(role, ["SystemAdmin"])
    b = body()
    project_id = req_str(b, "project_id")
    cost_code = req_str(b, "cost_code")
    description = req_str(b, "description")
    budgeted = req_num(b, "budgeted_quantity", gt=Decimal(0))
    unit = req_enum(b, "unit", UNITS)
    unit_cost = req_int(b, "unit_cost_cents", mn=0)
    get_project(project_id)
    for w in store.work_items.values():
        if w["project_id"] == project_id and w["cost_code"] == cost_code:
            raise ApiError(
                "ERR_DUPLICATE_COST_CODE", 409, "cost_code already exists in project"
            )
    rec = stamp(
        {
            "project_id": project_id,
            "cost_code": cost_code,
            "description": description,
            "budgeted_quantity": budgeted,
            "unit": unit,
            "unit_cost_cents": unit_cost,
        }
    )
    store.work_items[rec["id"]] = rec
    return success(ser_work_item(rec), 201)


@bp.get("/work-items/<wid>")
def get_one_work_item(wid):
    ctx()
    return success(ser_work_item(get_work_item(wid)), 200)


@bp.get("/work-items")
def list_work_items():
    ctx()
    project_id = request.args.get("project_id")
    status = request.args.get("status")
    if status is not None and status not in WORK_ITEM_STATUSES:
        bad("Invalid status filter")
    rows = list(store.work_items.values())
    if project_id is not None:
        rows = [r for r in rows if r["project_id"] == project_id]
    if status is not None:
        rows = [r for r in rows if calc.work_item_status(r, calc.installed_to_date(r["id"])) == status]
    return list_response(rows, ser_work_item)
