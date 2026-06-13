"""Callback routes (PRD §3.10) — cyclic reopen branch."""
from flask import Blueprint, request

import db
import errors
import lookup
import serialize
import util
from middleware import authenticate, require_role
from response import success

bp = Blueprint("callbacks", __name__)


@bp.route("/callbacks", methods=["POST"])
def open_callback():
    _, role = authenticate()
    require_role(role, ["Customer", "ServiceManager"])
    body = util.get_body()
    util.require_fields(body, ["job_id", "reason"])
    job_id = body.get("job_id")
    if not isinstance(job_id, str):
        raise errors.err(errors.ERR_INVALID_REQUEST, "job_id must be a string")
    reason = util.require_string(body, "reason")
    lookup.job(job_id)
    c = {"job_id": job_id, "reason": reason, "status": "OPEN", "fault_confirmed": False}
    db.stamp_create(c, common_fields=True, versioned=True)
    db.callbacks[c["id"]] = c
    return success(serialize.callback(c), status=201)


@bp.route("/callbacks/<id>", methods=["GET"])
def get_callback(id):
    _, role = authenticate()
    require_role(role, ["ServiceManager", "Dispatcher", "Technician", "Customer"])
    c = lookup.callback(id)
    return success(serialize.callback(c))


@bp.route("/callbacks", methods=["GET"])
def list_callbacks():
    _, role = authenticate()
    require_role(role, ["ServiceManager", "Dispatcher", "Technician"])
    limit, offset = util.parse_pagination()
    job_id = request.args.get("job_id")
    status = request.args.get("status")
    rows = []
    for c in db.callbacks.values():
        if job_id is not None and c["job_id"] != job_id:
            continue
        if status is not None and c["status"] != status:
            continue
        rows.append(c)
    page, pagination = util.paginate(rows, limit, offset)
    return success([serialize.callback(c) for c in page], pagination=pagination)


@bp.route("/callbacks/<id>/schedule", methods=["POST"])
def schedule_callback(id):
    _, role = authenticate()
    require_role(role, ["Dispatcher"])
    c = lookup.callback(id)
    if c["status"] != "OPEN":
        raise errors.err(errors.ERR_INVALID_STATE, "Callback must be OPEN to schedule")
    job = db.jobs.get(c["job_id"])
    if job is None or job["dispatch_status"] not in ("COMPLETED", "CLOSED"):
        raise errors.err(errors.ERR_INVALID_STATE, "Parent job must be COMPLETED or CLOSED")
    c["status"] = "SCHEDULED"
    db.touch(c)
    return success(serialize.callback(c))


@bp.route("/callbacks/<id>/arrive", methods=["POST"])
def arrive_callback(id):
    _, role = authenticate()
    require_role(role, ["Technician"])
    c = lookup.callback(id)
    if c["status"] != "SCHEDULED":
        raise errors.err(errors.ERR_INVALID_STATE, "Callback must be SCHEDULED to arrive")
    c["status"] = "ON_SITE"
    db.touch(c)
    return success(serialize.callback(c))


@bp.route("/callbacks/<id>/resolve", methods=["POST"])
def resolve_callback(id):
    _, role = authenticate()
    require_role(role, ["Technician"])
    c = lookup.callback(id)
    body = util.get_body()
    util.require_fields(body, ["fault_confirmed"])
    fault_confirmed = body.get("fault_confirmed")
    if not isinstance(fault_confirmed, bool):
        raise errors.err(errors.ERR_INVALID_REQUEST, "fault_confirmed must be boolean")
    if c["status"] != "ON_SITE":
        raise errors.err(errors.ERR_INVALID_STATE, "Callback must be ON_SITE to resolve")
    c["status"] = "RESOLVED"
    c["fault_confirmed"] = fault_confirmed
    db.touch(c)
    # recompute responsible technician's rates (derive live; bump version)
    job = db.jobs.get(c["job_id"])
    if job is not None and job["technician_id"] is not None:
        tech = db.technicians.get(job["technician_id"])
        if tech is not None:
            db.touch(tech)
    return success(serialize.callback(c))


@bp.route("/callbacks/<id>/reopen", methods=["POST"])
def reopen_callback(id):
    _, role = authenticate()
    require_role(role, ["Dispatcher"])
    c = lookup.callback(id)
    if c["status"] != "ON_SITE":
        raise errors.err(errors.ERR_INVALID_STATE, "Callback must be ON_SITE to reopen")
    c["status"] = "OPEN"
    db.touch(c)
    return success(serialize.callback(c))
