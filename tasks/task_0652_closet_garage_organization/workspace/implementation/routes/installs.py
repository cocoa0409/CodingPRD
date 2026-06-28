"""Crew and InstallJob routes, including capacity checks."""
from flask import Blueprint, request

import db
import serialize
from errors import err
from response import object_response, array_response
from middleware import get_identity, require_roles
from validate import (get_body, require_str, require_int, require_datetime,
                      parse_pagination, paginate)
from services import clock, domain

bp = Blueprint("installs", __name__)

REGIONS = {"NORTH", "SOUTH", "EAST", "WEST"}


# ---------------- Crews ----------------
@bp.post("/crews")
def create_crew():
    _, role = get_identity()
    require_roles(role, {"Scheduler", "PlatformAdmin"})
    body = get_body()
    crew_name = require_str(body, "crew_name")
    region = require_str(body, "region")
    if region not in REGIONS:
        raise err("ERR_VALIDATION", "region must be one of NORTH/SOUTH/EAST/WEST.")
    daily_capacity_units = require_int(body, "daily_capacity_units", minimum=1)
    active = body.get("active", True)
    if not isinstance(active, bool):
        raise err("ERR_VALIDATION", "active must be a boolean.")
    rec = db.stamp_new({
        "crew_name": crew_name,
        "region": region,
        "daily_capacity_units": daily_capacity_units,
        "active": active,
    })
    db.crews[rec["id"]] = rec
    return object_response(serialize.crew(rec), 201)


@bp.get("/crews/<cid>")
def get_crew(cid):
    _, role = get_identity()
    require_roles(role, {"Scheduler", "PlatformAdmin"})
    rec = db.crews.get(cid)
    if rec is None:
        raise err("ERR_RESOURCE_NOT_FOUND")
    return object_response(serialize.crew(rec))


@bp.get("/crews/<cid>/install-jobs")
def list_crew_jobs(cid):
    _, role = get_identity()
    require_roles(role, {"Scheduler", "PlatformAdmin"})
    if cid not in db.crews:
        raise err("ERR_RESOURCE_NOT_FOUND")
    limit, offset = parse_pagination()
    sched_status = request.args.get("sched_status")
    items = [j for j in db.install_jobs.values()
             if j["crew_id"] == cid and (sched_status is None or j["sched_status"] == sched_status)]
    page, total = paginate(items, limit, offset)
    return array_response([serialize.install_job(j) for j in page],
                          limit, offset, total)


# ---------------- Install jobs ----------------
def _validate_window(start, end):
    """window_end strictly after window_start, same UTC calendar day."""
    if not (end > start):
        raise err("ERR_INVALID_WINDOW")
    if start.date() != end.date():
        raise err("ERR_INVALID_WINDOW")


def _crew_day_booked_units(crew_id, day, exclude_job_id=None):
    """Sum units_booked of BOOKED jobs on this crew on the given UTC date."""
    total = 0
    for j in db.install_jobs.values():
        if j["id"] == exclude_job_id:
            continue
        if j["crew_id"] != crew_id:
            continue
        if j["sched_status"] != "BOOKED":
            continue
        if j["window_start"].date() != day:
            continue
        total += j["units_booked"]
    return total


def _accepted_config_total_units(project):
    """total_units of the config behind the project's accepted quote."""
    aq_id = project.get("accepted_quote_id")
    if not aq_id or aq_id not in db.quotes:
        return 0
    quote = db.quotes[aq_id]
    config = db.component_configs.get(quote["component_config_id"])
    return config["total_units"] if config else 0


@bp.post("/install-jobs")
def create_job():
    _, role = get_identity()
    require_roles(role, {"Scheduler"})
    body = get_body()
    project_id = require_str(body, "project_id")
    manufacture_order_id = require_str(body, "manufacture_order_id")
    crew_id = require_str(body, "crew_id")
    window_start = require_datetime(body, "window_start")
    window_end = require_datetime(body, "window_end")
    project = db.projects.get(project_id)
    if project is None:
        raise err("ERR_RESOURCE_NOT_FOUND")
    mo = db.manufacture_orders.get(manufacture_order_id)
    if mo is None:
        raise err("ERR_RESOURCE_NOT_FOUND")
    crew = db.crews.get(crew_id)
    if crew is None:
        raise err("ERR_RESOURCE_NOT_FOUND")

    # window_start must be >= promised_ready_date (priority 11) before window
    # validity (priority 12).
    if mo["promised_ready_date"] is not None and window_start < mo["promised_ready_date"]:
        raise err("ERR_WINDOW_BEFORE_READY")
    _validate_window(window_start, window_end)

    rec = db.stamp_new({
        "project_id": project_id,
        "manufacture_order_id": manufacture_order_id,
        "crew_id": crew_id,
        "window_start": window_start,
        "window_end": window_end,
        "sched_status": "PROPOSED",
        "completion_status": "NOT_STARTED",
        "units_booked": 0,
    })
    db.install_jobs[rec["id"]] = rec
    return object_response(serialize.install_job(rec), 201)


@bp.get("/install-jobs/<jid>")
def get_job(jid):
    _, role = get_identity()
    require_roles(role, {"Customer", "Scheduler", "PlatformAdmin"})
    rec = db.install_jobs.get(jid)
    if rec is None:
        raise err("ERR_RESOURCE_NOT_FOUND")
    return object_response(serialize.install_job(rec))


@bp.get("/install-jobs")
def list_jobs():
    _, role = get_identity()
    require_roles(role, {"Customer", "Scheduler", "PlatformAdmin"})
    limit, offset = parse_pagination()
    project_id = request.args.get("project_id")
    manufacture_order_id = request.args.get("manufacture_order_id")
    crew_id = request.args.get("crew_id")
    items = []
    for j in db.install_jobs.values():
        if project_id is not None and j["project_id"] != project_id:
            continue
        if manufacture_order_id is not None and j["manufacture_order_id"] != manufacture_order_id:
            continue
        if crew_id is not None and j["crew_id"] != crew_id:
            continue
        items.append(j)
    page, total = paginate(items, limit, offset)
    return array_response([serialize.install_job(j) for j in page],
                          limit, offset, total)


@bp.post("/install-jobs/<jid>/book")
def book_job(jid):
    _, role = get_identity()
    require_roles(role, {"Scheduler"})
    rec = db.install_jobs.get(jid)
    if rec is None:
        raise err("ERR_RESOURCE_NOT_FOUND")
    mo = db.manufacture_orders.get(rec["manufacture_order_id"])
    crew = db.crews.get(rec["crew_id"])
    project = db.projects.get(rec["project_id"])
    if mo is None or crew is None or project is None:
        raise err("ERR_RESOURCE_NOT_FOUND")

    # State check (priority 5).
    if rec["sched_status"] != "PROPOSED":
        raise err("ERR_INVALID_STATE")
    # MO must be READY (state precondition).
    if mo["status"] != "READY":
        raise err("ERR_INVALID_STATE")
    # Crew must be active (state precondition).
    if not crew["active"]:
        raise err("ERR_INVALID_STATE")

    # Region match (priority 8).
    if crew["region"] != project["install_region"]:
        raise err("ERR_CREW_REGION_MISMATCH")
    # window_start >= promised_ready_date (priority 11).
    if mo["promised_ready_date"] is not None and rec["window_start"] < mo["promised_ready_date"]:
        raise err("ERR_WINDOW_BEFORE_READY")

    units = _accepted_config_total_units(project)
    # Capacity check (priority 14): booked + this <= daily_capacity (inclusive).
    day = rec["window_start"].date()
    booked = _crew_day_booked_units(rec["crew_id"], day, exclude_job_id=jid)
    if booked + units > crew["daily_capacity_units"]:
        raise err("ERR_CREW_CAPACITY_EXCEEDED")

    rec["units_booked"] = units
    rec["sched_status"] = "BOOKED"
    db.touch(rec)
    return object_response(serialize.install_job(rec))


@bp.post("/install-jobs/<jid>/request-reschedule")
def request_reschedule(jid):
    user_id, role = get_identity()
    require_roles(role, {"Customer"})
    rec = db.install_jobs.get(jid)
    if rec is None:
        raise err("ERR_RESOURCE_NOT_FOUND")
    project = db.projects.get(rec["project_id"])
    domain.check_project_owner(project, user_id, role)
    if rec["sched_status"] != "BOOKED" or rec["completion_status"] != "NOT_STARTED":
        raise err("ERR_INVALID_STATE")
    rec["sched_status"] = "RESCHEDULING"
    rec["units_booked"] = 0  # frees the held capacity
    db.touch(rec)
    return object_response(serialize.install_job(rec))


@bp.post("/install-jobs/<jid>/rebook")
def rebook_job(jid):
    _, role = get_identity()
    require_roles(role, {"Scheduler"})
    rec = db.install_jobs.get(jid)
    if rec is None:
        raise err("ERR_RESOURCE_NOT_FOUND")
    mo = db.manufacture_orders.get(rec["manufacture_order_id"])
    crew = db.crews.get(rec["crew_id"])
    project = db.projects.get(rec["project_id"])
    if mo is None or crew is None or project is None:
        raise err("ERR_RESOURCE_NOT_FOUND")

    if rec["sched_status"] != "RESCHEDULING":
        raise err("ERR_INVALID_STATE")

    body = get_body()
    window_start = require_datetime(body, "window_start")
    window_end = require_datetime(body, "window_end")

    # Region check (priority 8).
    if crew["region"] != project["install_region"]:
        raise err("ERR_CREW_REGION_MISMATCH")
    # window_start >= promised_ready_date (priority 11).
    if mo["promised_ready_date"] is not None and window_start < mo["promised_ready_date"]:
        raise err("ERR_WINDOW_BEFORE_READY")
    # window validity (priority 12).
    _validate_window(window_start, window_end)

    units = _accepted_config_total_units(project)
    day = window_start.date()
    booked = _crew_day_booked_units(rec["crew_id"], day, exclude_job_id=jid)
    if booked + units > crew["daily_capacity_units"]:
        raise err("ERR_CREW_CAPACITY_EXCEEDED")

    rec["window_start"] = window_start
    rec["window_end"] = window_end
    rec["units_booked"] = units
    rec["sched_status"] = "BOOKED"
    db.touch(rec)
    return object_response(serialize.install_job(rec))


@bp.post("/install-jobs/<jid>/cancel")
def cancel_job(jid):
    _, role = get_identity()
    require_roles(role, {"Scheduler"})
    rec = db.install_jobs.get(jid)
    if rec is None:
        raise err("ERR_RESOURCE_NOT_FOUND")
    if rec["sched_status"] != "BOOKED" or rec["completion_status"] != "NOT_STARTED":
        raise err("ERR_INVALID_STATE")
    rec["sched_status"] = "CANCELLED"
    rec["units_booked"] = 0  # frees capacity
    db.touch(rec)
    return object_response(serialize.install_job(rec))


@bp.post("/install-jobs/<jid>/start")
def start_job(jid):
    _, role = get_identity()
    require_roles(role, {"Scheduler"})
    rec = db.install_jobs.get(jid)
    if rec is None:
        raise err("ERR_RESOURCE_NOT_FOUND")
    project = db.projects.get(rec["project_id"])
    if project is None:
        raise err("ERR_RESOURCE_NOT_FOUND")
    if rec["sched_status"] != "BOOKED" or rec["completion_status"] != "NOT_STARTED":
        raise err("ERR_INVALID_STATE")
    if project["status"] != "READY_TO_INSTALL":
        raise err("ERR_INVALID_STATE")
    # Start window: now must be >= window_start.
    if clock.now() < rec["window_start"]:
        raise err("ERR_INVALID_STATE")
    rec["completion_status"] = "IN_PROGRESS"
    db.touch(rec)
    project["status"] = "INSTALLING"
    db.touch(project)
    return object_response(serialize.install_job(rec))


@bp.post("/install-jobs/<jid>/complete")
def complete_job(jid):
    _, role = get_identity()
    require_roles(role, {"Scheduler"})
    rec = db.install_jobs.get(jid)
    if rec is None:
        raise err("ERR_RESOURCE_NOT_FOUND")
    project = db.projects.get(rec["project_id"])
    mo = db.manufacture_orders.get(rec["manufacture_order_id"])
    if project is None or mo is None:
        raise err("ERR_RESOURCE_NOT_FOUND")
    if rec["completion_status"] != "IN_PROGRESS":
        raise err("ERR_INVALID_STATE")
    # Deepest cascade: job DONE -> MO INSTALLED -> Project COMPLETED.
    rec["completion_status"] = "DONE"
    db.touch(rec)
    if mo["status"] == "READY":
        mo["status"] = "INSTALLED"
        db.touch(mo)
    project["status"] = "COMPLETED"
    domain.recompute_balance(project)
    return object_response(serialize.install_job(rec))
