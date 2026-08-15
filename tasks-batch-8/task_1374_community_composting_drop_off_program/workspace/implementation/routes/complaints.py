"""ComplaintTicket endpoints."""

from datetime import timedelta

from flask import Blueprint, request

import db
import errors
from middleware import require_roles
from response import success_object, success_list
from routes.helpers import (
    body, require_fields, require_str, require_enum, require_dt_field,
    get_program_or_404, get_site_or_404, get_complaint_or_404,
    paginate, sort_created,
)
from services import posture as posture_svc
from services.programs import touch, site_posture_touch
from services.serializers import complaint as serialize_complaint

bp = Blueprint("complaints", __name__)

READ_ROLES = ("ProgramAdmin", "SiteHost", "MunicipalAuditor")
KINDS = ("ODOR", "VECTOR", "OTHER")


@bp.route("/programs/<program_id>/sites/<site_id>/complaints", methods=["POST"])
def create_complaint(program_id, site_id):
    require_roles("Anonymous")
    get_program_or_404(program_id)
    site = get_site_or_404(site_id, program_id)
    data = body()
    require_fields(data, "reporter_contact", "kind", "description", "reported_at")
    reporter_contact = require_str(data, "reporter_contact")
    kind = require_enum(data, "kind", KINDS)
    description = require_str(data, "description")
    reported_at = require_dt_field(data, "reported_at")

    now = db.iso_now()
    complaint = {
        "id": db.new_id(),
        "site_id": site["id"],
        "reporter_contact": reporter_contact,
        "kind": kind,
        "description": description,
        "reported_at": reported_at,
        "sla_due_at": reported_at + timedelta(hours=72),
        "acknowledged_at": None,
        "resolved_at": None,
        "resolved_ops_index": None,
        "sla_breached": False,
        "reopen_count": 0,
        "status": "OPEN",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.complaints[complaint["id"]] = complaint
    site_posture_touch(site)
    return success_object(serialize_complaint(complaint), status=201)


@bp.route("/programs/<program_id>/sites/<site_id>/complaints", methods=["GET"])
def list_complaints(program_id, site_id):
    require_roles(*READ_ROLES)
    get_program_or_404(program_id)
    get_site_or_404(site_id, program_id)
    items = [c for c in db.complaints.values() if c["site_id"] == site_id]
    if request.args.get("status"):
        items = [c for c in items if c["status"] == request.args["status"]]
    if request.args.get("kind"):
        items = [c for c in items if c["kind"] == request.args["kind"]]
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return success_list([serialize_complaint(c) for c in page], limit, offset, total)


@bp.route(
    "/programs/<program_id>/sites/<site_id>/complaints/<complaint_id>/acknowledge",
    methods=["POST"],
)
def acknowledge_complaint(program_id, site_id, complaint_id):
    require_roles("ProgramAdmin")
    get_program_or_404(program_id)
    get_site_or_404(site_id, program_id)
    complaint = get_complaint_or_404(complaint_id, site_id)
    if complaint["status"] != "OPEN":
        errors.raise_err(errors.ERR_INVALID_STATE, "Complaint must be OPEN to acknowledge")
    complaint["status"] = "ACKNOWLEDGED"
    complaint["acknowledged_at"] = db.clock_now()
    touch(complaint)
    return success_object(serialize_complaint(complaint))


@bp.route(
    "/programs/<program_id>/sites/<site_id>/complaints/<complaint_id>/resolve",
    methods=["POST"],
)
def resolve_complaint(program_id, site_id, complaint_id):
    require_roles("ProgramAdmin")
    program = get_program_or_404(program_id)
    site = get_site_or_404(site_id, program_id)
    complaint = get_complaint_or_404(complaint_id, site_id)
    if complaint["status"] not in ("OPEN", "ACKNOWLEDGED", "REOPENED"):
        errors.raise_err(errors.ERR_INVALID_STATE, "Complaint cannot be resolved from current state")
    complaint["status"] = "RESOLVED"
    complaint["resolved_at"] = db.clock_now()
    complaint["resolved_ops_index"] = program["ops_run_index"]
    touch(complaint)
    site_posture_touch(site)
    return success_object(serialize_complaint(complaint))


@bp.route(
    "/programs/<program_id>/sites/<site_id>/complaints/<complaint_id>/reopen",
    methods=["POST"],
)
def reopen_complaint(program_id, site_id, complaint_id):
    require_roles("MunicipalAuditor")
    get_program_or_404(program_id)
    site = get_site_or_404(site_id, program_id)
    complaint = get_complaint_or_404(complaint_id, site_id)
    if complaint["status"] != "RESOLVED":
        errors.raise_err(errors.ERR_INVALID_STATE, "Complaint must be RESOLVED to reopen")
    if complaint["reopen_count"] >= 2:
        errors.raise_err(errors.ERR_COMPLAINT_REOPEN_LIMIT, "Complaint reopen_count already at 2")
    complaint["reopen_count"] += 1
    complaint["resolved_at"] = None
    complaint["resolved_ops_index"] = None
    complaint["status"] = "REOPENED"
    touch(complaint)
    site_posture_touch(site)
    return success_object(serialize_complaint(complaint))


@bp.route(
    "/programs/<program_id>/sites/<site_id>/complaints/<complaint_id>/close",
    methods=["POST"],
)
def close_complaint(program_id, site_id, complaint_id):
    require_roles("ProgramAdmin")
    program = get_program_or_404(program_id)
    get_site_or_404(site_id, program_id)
    complaint = get_complaint_or_404(complaint_id, site_id)
    if complaint["status"] != "RESOLVED":
        errors.raise_err(errors.ERR_INVALID_STATE, "Complaint must be RESOLVED to close")
    resolved_idx = complaint.get("resolved_ops_index")
    if resolved_idx is None or program["ops_run_index"] <= resolved_idx:
        errors.raise_err(
            errors.ERR_COMPLAINT_NOT_STABLE,
            "Complaint close requires an intervening ops run after resolve",
        )
    complaint["status"] = "CLOSED"
    touch(complaint)
    return success_object(serialize_complaint(complaint))


# --- Flat aliases ---

@bp.route("/complaints", methods=["GET"])
def list_complaints_flat():
    require_roles(*READ_ROLES)
    items = list(db.complaints.values())
    if request.args.get("site_id"):
        items = [c for c in items if c["site_id"] == request.args["site_id"]]
    if request.args.get("status"):
        items = [c for c in items if c["status"] == request.args["status"]]
    if request.args.get("kind"):
        items = [c for c in items if c["kind"] == request.args["kind"]]
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return success_list([serialize_complaint(c) for c in page], limit, offset, total)


@bp.route("/complaints/<complaint_id>", methods=["GET"])
def get_complaint_flat(complaint_id):
    require_roles(*READ_ROLES)
    complaint = get_complaint_or_404(complaint_id)
    return success_object(serialize_complaint(complaint))
