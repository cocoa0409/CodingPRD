"""Install jobs (PRD 3.8, 3.9). Scheduling enforces certification, capacity,
half-open overlap, and window validity, then advances DEPOSIT_PAID->SCHEDULED.
Start/complete/abort run the install lifecycle with the completion cascade."""

from flask import Blueprint, request

from common import (
    add_months,
    get_json_body,
    iso_format,
    paginate,
    parse_iso8601,
    public,
    require_fields,
    require_string,
    stamp_new,
    touch,
)
from clock import clock
from db import db
from errors import err
from lookups import get_child_or_404, get_project_or_404, ref_crew_or_404
from middleware import get_auth, require_role
from ownership import enforce_project_ownership
from response import success

bp = Blueprint("install_jobs", __name__)


def _overlaps(a_start, a_end, b_start, b_end):
    """Half-open overlap: [a_start, a_end) intersects [b_start, b_end).
    Adjacent (a_end == b_start or b_end == a_start) does NOT overlap."""
    return a_start < b_end and b_start < a_end


@bp.route("/projects/<project_id>/install-jobs", methods=["POST"])
def create_job(project_id):
    _uid, role = get_auth()
    require_role(role, {"Scheduler", "OpsAdmin"})
    project = get_project_or_404(project_id)
    body = get_json_body()
    require_fields(body, ["crew_id", "scheduled_start", "scheduled_end"])
    crew = ref_crew_or_404(body["crew_id"])

    start = parse_iso8601(require_string(body, "scheduled_start"))
    end = parse_iso8601(require_string(body, "scheduled_end"))
    if start is None or end is None:
        raise err("ERR_INVALID_REQUEST", "scheduled_start/scheduled_end must be ISO 8601.")

    # State (priority 8): project must be DEPOSIT_PAID.
    if project["workflow_status"] != "DEPOSIT_PAID":
        raise err("ERR_INVALID_STATE", "Project is not in DEPOSIT_PAID status.")

    # Crew certification + active (priority 13).
    variant = project["variant"]
    if not crew["active"]:
        raise err("ERR_CREW_NOT_CERTIFIED", "Crew is inactive.")
    if variant == "PUTTING_GREEN" and not crew["certified_putting"]:
        raise err("ERR_CREW_NOT_CERTIFIED", "Crew is not certified for PUTTING_GREEN.")
    if variant == "PLAYGROUND" and not crew["certified_playground"]:
        raise err("ERR_CREW_NOT_CERTIFIED", "Crew is not certified for PLAYGROUND.")

    # Crew capacity (priority 14).
    if crew["daily_capacity_sqft"] < project["billable_area_sqft"]:
        raise err("ERR_CREW_CAPACITY_EXCEEDED", "Crew capacity is below billable area.")

    # Crew double-booking on the half-open interval (priority 15).
    for job in db.install_jobs.values():
        if job["crew_id"] != crew["id"]:
            continue
        if job["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        b_start = parse_iso8601(job["scheduled_start"])
        b_end = parse_iso8601(job["scheduled_end"])
        if _overlaps(start, end, b_start, b_end):
            raise err("ERR_CREW_DOUBLE_BOOKED", "Crew window overlaps another job.")

    # Window validity (priority 16): end strictly after start.
    if not (end > start):
        raise err("ERR_INVALID_WINDOW", "scheduled_end must be after scheduled_start.")

    rec = {
        "project_id": project_id,
        "crew_id": crew["id"],
        "scheduled_start": iso_format(start),
        "scheduled_end": iso_format(end),
        "install_area_sqft": project["billable_area_sqft"],
        "status": "SCHEDULED",
    }
    stamp_new(rec)
    db.install_jobs[rec["id"]] = rec

    project["workflow_status"] = "SCHEDULED"
    touch(project)

    return success(public(rec), status=201)


@bp.route("/projects/<project_id>/install-jobs", methods=["GET"])
def list_jobs(project_id):
    uid, role = get_auth()
    require_role(role, {"Scheduler", "OpsAdmin", "Customer"})
    project = get_project_or_404(project_id)
    enforce_project_ownership(project, uid, role)
    items = [j for j in db.install_jobs.values() if j["project_id"] == project_id]
    for field in ("crew_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [j for j in items if j[field] == val]
    data, pagination = paginate(items, public)
    return success(data, status=200, pagination=pagination)


@bp.route("/projects/<project_id>/install-jobs/<install_job_id>", methods=["GET"])
def get_job(project_id, install_job_id):
    uid, role = get_auth()
    require_role(role, {"Scheduler", "OpsAdmin", "Customer"})
    project = get_project_or_404(project_id)
    enforce_project_ownership(project, uid, role)
    rec = get_child_or_404(db.install_jobs, install_job_id, project_id, "Install job")
    return success(public(rec), status=200)


@bp.route("/projects/<project_id>/install-jobs/<install_job_id>/start", methods=["POST"])
def start_job(project_id, install_job_id):
    _uid, role = get_auth()
    require_role(role, {"Scheduler", "OpsAdmin"})
    get_project_or_404(project_id)
    job = get_child_or_404(db.install_jobs, install_job_id, project_id, "Install job")

    if job["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Install job is not in SCHEDULED status.")
    start = parse_iso8601(job["scheduled_start"])
    if clock.now() < start:
        raise err("ERR_INVALID_STATE", "Clock has not reached scheduled_start.")

    job["status"] = "IN_PROGRESS"
    touch(job)
    return success(public(job), status=200)


@bp.route("/projects/<project_id>/install-jobs/<install_job_id>/complete", methods=["POST"])
def complete_job(project_id, install_job_id):
    _uid, role = get_auth()
    require_role(role, {"Scheduler", "OpsAdmin"})
    project = get_project_or_404(project_id)
    job = get_child_or_404(db.install_jobs, install_job_id, project_id, "Install job")

    if job["status"] != "IN_PROGRESS":
        raise err("ERR_INVALID_STATE", "Install job is not in IN_PROGRESS status.")

    # Cascade hop 1: complete the job.
    job["status"] = "COMPLETED"
    touch(job)

    # Cascade hop 2: activate any PENDING warranty plan.
    job_end = parse_iso8601(job["scheduled_end"])
    for w in db.warranty_plans.values():
        if w["project_id"] == project["id"] and w["status"] == "PENDING":
            w["status"] = "ACTIVE"
            w["start_at"] = iso_format(job_end)
            w["expires_at"] = iso_format(add_months(job_end, w["coverage_months"]))
            touch(w)

    # Bubble up: project workflow SCHEDULED->INSTALLED; finance ->BALANCE_DUE.
    if project["workflow_status"] == "SCHEDULED":
        project["workflow_status"] = "INSTALLED"
    project["finance_status"] = "BALANCE_DUE"
    touch(project)

    return success(public(job), status=200)


@bp.route("/projects/<project_id>/install-jobs/<install_job_id>/abort", methods=["POST"])
def abort_job(project_id, install_job_id):
    _uid, role = get_auth()
    require_role(role, {"Scheduler", "OpsAdmin"})
    get_project_or_404(project_id)
    job = get_child_or_404(db.install_jobs, install_job_id, project_id, "Install job")

    if job["status"] not in ("SCHEDULED", "IN_PROGRESS"):
        raise err("ERR_INVALID_STATE", "Install job cannot be aborted in its current state.")

    # Abort releases the crew interval (frees the overlap window); no warranty,
    # no finance change.
    job["status"] = "ABORTED"
    touch(job)
    return success(public(job), status=200)
