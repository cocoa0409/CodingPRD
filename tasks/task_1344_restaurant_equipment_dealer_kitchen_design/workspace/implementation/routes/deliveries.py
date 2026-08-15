"""DeliveryJob endpoints (PRD 3.6): plan, dispatch (with window-conflict and
fabrication-completeness guards), mark-site-complete (items INSTALLED and
project bubble-up to DELIVERED), cancel."""

from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_DELIVERY_WINDOW_CONFLICT,
    ERR_FABRICATION_INCOMPLETE,
    ERR_INVALID_JOB_WINDOW,
    ERR_INVALID_REQUEST,
    ERR_JOB_NOT_CANCELLABLE,
    ERR_JOB_NOT_DISPATCHED,
    ERR_JOB_NOT_PLANNED,
    HTTP_STATUS,
)
from middleware import require_roles
from response import success_object
from routes.common import paginate, resolve_job, resolve_project, serialize
from services import workflow
from services.validate import json_body, opt_bool, opt_int, req_str, parse_iso

bp = Blueprint("deliveries", __name__)

JOB_READ_ROLES = ("PlatformAdmin", "ProjectManager", "LogisticsCoordinator")
BUFFER = timedelta(hours=2)


@bp.route("/design-build-projects/<id>/delivery-jobs", methods=["POST"])
@require_roles("LogisticsCoordinator")
def create_job(id, _user_id=None, _role=None):
    project = resolve_project(id)
    body = json_body(required=True)
    start_raw = req_str(body, "scheduled_start")
    end_raw = req_str(body, "scheduled_end")
    rigging_required = opt_bool(body, "rigging_required", default=False)
    crew_size = opt_int(body, "rigging_crew_size", default=0)
    start_dt = parse_iso(start_raw)
    end_dt = parse_iso(end_raw)
    if start_dt is None or end_dt is None:
        raise ApiError(
            ERR_INVALID_REQUEST, 400,
            "scheduled_start and scheduled_end must be ISO 8601 UTC timestamps",
        )
    if rigging_required and (crew_size is None or crew_size < 2):
        raise ApiError(
            ERR_INVALID_REQUEST, 400,
            "rigging_crew_size must be >= 2 when rigging_required is true",
        )
    # Structural guard: end strictly after start.
    if not (end_dt > start_dt):
        raise ApiError(
            ERR_INVALID_JOB_WINDOW, HTTP_STATUS[ERR_INVALID_JOB_WINDOW],
            "scheduled_end must be > scheduled_start",
        )
    job = db.stamp_new({
        "project_id": project["id"],
        "scheduled_start": start_raw,
        "scheduled_end": end_raw,
        "rigging_required": rigging_required,
        "rigging_crew_size": crew_size if crew_size is not None else 0,
        "status": "PLANNED",
        "_start_dt": start_dt,
        "_end_dt": end_dt,
    })
    db.jobs[job["id"]] = job
    return success_object(serialize(job), 201)


@bp.route("/design-build-projects/<id>/delivery-jobs", methods=["GET"])
@require_roles(*JOB_READ_ROLES)
def list_jobs(id, _user_id=None, _role=None):
    project = resolve_project(id)
    status = request.args.get("status")
    records = [j for j in db.jobs.values() if j["project_id"] == project["id"]]
    if status is not None:
        records = [j for j in records if j["status"] == status]
    return paginate(records)


@bp.route("/design-build-projects/<id>/delivery-jobs/<jobId>", methods=["GET"])
@require_roles(*JOB_READ_ROLES)
def get_job(id, jobId, _user_id=None, _role=None):
    project = resolve_project(id)
    job = resolve_job(project, jobId)
    return success_object(serialize(job), 200)


@bp.route("/design-build-projects/<id>/delivery-jobs/<jobId>/dispatch", methods=["POST"])
@require_roles("LogisticsCoordinator")
def dispatch_job(id, jobId, _user_id=None, _role=None):
    project = resolve_project(id)
    job = resolve_job(project, jobId)
    # Guards in PRD 3.6 order: PLANNED, fabrication readiness, window conflict.
    if job["status"] != "PLANNED":
        raise ApiError(
            ERR_JOB_NOT_PLANNED, HTTP_STATUS[ERR_JOB_NOT_PLANNED],
            "Dispatch requires DeliveryJob in PLANNED",
        )
    fab_ready = project["status"] == "FABRICATION"
    if project["status"] == "CONTRACTED":
        custom_items = [
            it for it in db.items.values()
            if it["project_id"] == project["id"]
            and it["item_kind"] == "CUSTOM_FABRICATION"
            and it["status"] != "CANCELLED"
        ]
        fab_ready = all(it["status"] == "RECEIVED" for it in custom_items)
    if not fab_ready:
        raise ApiError(
            ERR_FABRICATION_INCOMPLETE, HTTP_STATUS[ERR_FABRICATION_INCOMPLETE],
            "CUSTOM_FABRICATION items exist without FAB_COMPLETE FabricationOrder",
        )
    for other in db.jobs.values():
        if (
            other["project_id"] == project["id"]
            and other["id"] != job["id"]
            and other["status"] != "CANCELLED"
        ):
            if other["rigging_required"] != job["rigging_required"]:
                continue  # differing rigging needs may overlap
            o_start, o_end = other["_start_dt"], other["_end_dt"]
            j_start, j_end = job["_start_dt"], job["_end_dt"]
            disjoint_with_buffer = (j_start >= o_end + BUFFER) or (o_start >= j_end + BUFFER)
            if not disjoint_with_buffer:
                raise ApiError(
                    ERR_DELIVERY_WINDOW_CONFLICT,
                    HTTP_STATUS[ERR_DELIVERY_WINDOW_CONFLICT],
                    "Overlapping windows with same rigging_required and < 2h buffer",
                )
    job["status"] = "DISPATCHED"
    db.touch(job)
    # STOCK items covered by the job move ORDERED -> RECEIVED on dispatch.
    for it in db.items.values():
        if (
            it["project_id"] == project["id"]
            and it["item_kind"] == "STOCK"
            and it["status"] == "ORDERED"
        ):
            it["status"] = "RECEIVED"
            db.touch(it)
    return success_object(serialize(job), 200)


@bp.route("/design-build-projects/<id>/delivery-jobs/<jobId>/mark-site-complete", methods=["POST"])
@require_roles("LogisticsCoordinator")
def mark_site_complete(id, jobId, _user_id=None, _role=None):
    project = resolve_project(id)
    job = resolve_job(project, jobId)
    if job["status"] != "DISPATCHED":
        raise ApiError(
            ERR_JOB_NOT_DISPATCHED, HTTP_STATUS[ERR_JOB_NOT_DISPATCHED],
            "Mark-site-complete requires DISPATCHED",
        )
    job["status"] = "SITE_COMPLETE"
    db.touch(job)
    # Covered items advance RECEIVED -> INSTALLED.
    for it in db.items.values():
        if it["project_id"] == project["id"] and it["status"] == "RECEIVED":
            it["status"] = "INSTALLED"
            db.touch(it)
    # Last job done + fabrication finished: bubble up to DELIVERED.
    workflow.maybe_deliver_project(project)
    return success_object(serialize(job), 200)


@bp.route("/design-build-projects/<id>/delivery-jobs/<jobId>/cancel", methods=["POST"])
@require_roles("LogisticsCoordinator")
def cancel_job(id, jobId, _user_id=None, _role=None):
    project = resolve_project(id)
    job = resolve_job(project, jobId)
    if job["status"] not in ("PLANNED", "DISPATCHED"):
        raise ApiError(
            ERR_JOB_NOT_CANCELLABLE, HTTP_STATUS[ERR_JOB_NOT_CANCELLABLE],
            "Cancel requires PLANNED or DISPATCHED",
        )
    # Items this job marked RECEIVED but not yet INSTALLED stay RECEIVED.
    job["status"] = "CANCELLED"
    db.touch(job)
    return success_object(serialize(job), 200)
