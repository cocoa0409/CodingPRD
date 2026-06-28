"""ServiceVisit endpoints (PRD 3.10).

A REQUESTED unrouted visit lazily transitions to MISSED when the clock's date
moves past its visit_date; this is evaluated on read.
"""

from flask import Blueprint

from clock import clock
from common import (
    get_json_body,
    paginate,
    require_fields,
    require_int,
    require_string,
    stamp_new,
    touch,
)
from db import db
from errors import err
from lookups import get_project, get_service_plan, get_service_visit
from middleware import get_auth, require_role
from response import success
from services.serialize import ser_service_visit

bp = Blueprint("service_visits", __name__)

READ_ROLES = {"Customer", "InstallTech", "OperationsAdmin"}


def _validate_window(start, end):
    if not (0 <= start <= 1439):
        raise err("ERR_INVALID_WINDOW", "window_start_min out of range.")
    if not (1 <= end <= 1440):
        raise err("ERR_INVALID_WINDOW", "window_end_min out of range.")
    if not (end > start):
        raise err("ERR_INVALID_WINDOW", "window_end_min must exceed window_start_min.")


def lazy_miss(visit):
    """REQUESTED + unrouted + clock date > visit_date -> MISSED (terminal)."""
    if visit["status"] == "REQUESTED" and visit.get("route_id") is None:
        clock_date = clock.now().strftime("%Y-%m-%d")
        if clock_date > visit["visit_date"]:
            visit["status"] = "MISSED"
            touch(visit)


@bp.post("/service-visits")
def create_service_visit():
    _, role = get_auth()
    require_role(role, {"Customer", "InstallTech"})
    body = get_json_body()
    require_fields(
        body,
        [
            "service_plan_id",
            "project_id",
            "visit_date",
            "window_start_min",
            "window_end_min",
        ],
    )
    service_plan_id = require_string(body, "service_plan_id")
    project_id = require_string(body, "project_id")
    visit_date = require_string(body, "visit_date")
    start = require_int(body, "window_start_min")
    end = require_int(body, "window_end_min")
    # Existence of body FKs (priority 3).
    get_service_plan(service_plan_id)
    get_project(project_id)
    _validate_window(start, end)

    record = stamp_new(
        {
            "service_plan_id": service_plan_id,
            "project_id": project_id,
            "visit_date": visit_date,
            "window_start_min": start,
            "window_end_min": end,
            "route_id": None,
            "status": "REQUESTED",
        }
    )
    db.service_visits[record["id"]] = record
    return success(ser_service_visit(record), status=201)


@bp.get("/service-visits/<vid>")
def read_service_visit(vid):
    _, role = get_auth()
    require_role(role, READ_ROLES)
    v = get_service_visit(vid)
    lazy_miss(v)
    return success(ser_service_visit(v), status=200)


@bp.get("/service-plans/<sid>/service-visits")
def list_plan_visits(sid):
    _, role = get_auth()
    require_role(role, READ_ROLES)
    get_service_plan(sid)
    items = [v for v in db.service_visits.values() if v["service_plan_id"] == sid]
    data, pagination = paginate(items, ser_service_visit)
    return success(data, status=200, pagination=pagination)


@bp.get("/projects/<pid>/service-visits")
def list_project_visits(pid):
    _, role = get_auth()
    require_role(role, READ_ROLES)
    get_project(pid)
    items = [v for v in db.service_visits.values() if v["project_id"] == pid]
    data, pagination = paginate(items, ser_service_visit)
    return success(data, status=200, pagination=pagination)
