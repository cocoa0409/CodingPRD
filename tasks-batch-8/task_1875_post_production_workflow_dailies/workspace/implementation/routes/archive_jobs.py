"""ArchiveJob routes (PRD §3.8)."""

from datetime import timedelta

from flask import Blueprint

import db
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
)
from helpers import (
    new_entity,
    touch,
    now_iso,
    get_json_body,
    require_fields,
    check_enum,
    check_int,
    get_pagination,
    get_filter,
    paginate,
)
from middleware import require_roles
from response import success_object, success_list
from routes.projects import get_project_or_404
from services.transitions import guard_transition
from clock import clock as logical_clock, format_iso

bp = Blueprint("archive_jobs", __name__)

LTO_GENERATIONS = ("LTO7", "LTO8", "LTO9")
TARGET_SCOPES = ("SOURCES_ONLY", "SOURCES_AND_PROXIES", "FULL_PROJECT")
ARCHIVE_TERMINAL = ("SEALED", "CANCELLED")
LIST_ROLES = ("PostSupervisor", "MediaManager")


def serialize(job):
    return dict(job)


def get_job_or_404(project, job_id):
    job = db.archive_jobs.get(job_id)
    if job is None or job["project_id"] != project["id"]:
        raise ApiError(ERR_NOT_FOUND, f"ArchiveJob {job_id} does not exist", 404)
    return job


def _scope_assets(project_id, target_scope):
    """MediaAssets in the job scope: those not PURGED (PRD calculation
    retained_until_horizon input set)."""
    return [
        a
        for a in db.assets.values()
        if a["project_id"] == project_id and a["status"] != "PURGED"
    ]


def _scope_bytes(project_id, target_scope):
    """Total bytes sealed across the job scope.

    SOURCES_ONLY counts source_bytes; SOURCES_AND_PROXIES and FULL_PROJECT
    count source_bytes + proxy_bytes.
    """
    total = 0
    for asset in _scope_assets(project_id, target_scope):
        total += asset["source_bytes"]
        if target_scope in ("SOURCES_AND_PROXIES", "FULL_PROJECT"):
            total += asset["proxy_bytes"]
    return total


@bp.route("/post-production/projects/<project_id>/archive-jobs", methods=["POST"])
def create_archive_job(project_id):
    require_roles(("MediaManager",))
    project = get_project_or_404(project_id)
    body = get_json_body()
    require_fields(body, ("lto_generation", "target_scope", "retention_years"))
    lto_generation = check_enum(body, "lto_generation", LTO_GENERATIONS)
    target_scope = check_enum(body, "target_scope", TARGET_SCOPES)
    retention_years = check_int(body, "retention_years", min_v=1, max_v=25)
    job = new_entity(
        {
            "project_id": project_id,
            "lto_generation": lto_generation,
            "target_scope": target_scope,
            "retention_years": retention_years,
            "status": "QUEUED",
            "sealed_at": None,
            "bytes_written": 0,
        }
    )
    db.archive_jobs[job["id"]] = job
    return success_object(serialize(job), 201)


@bp.route("/post-production/projects/<project_id>/archive-jobs", methods=["GET"])
def list_archive_jobs(project_id):
    require_roles(LIST_ROLES)
    get_project_or_404(project_id)
    limit, offset = get_pagination()
    items = [j for j in db.archive_jobs.values() if j["project_id"] == project_id]
    status = get_filter("status")
    if status is not None:
        items = [j for j in items if j["status"] == status]
    window, total = paginate(items, limit, offset)
    return success_list([serialize(j) for j in window], limit, offset, total)


@bp.route(
    "/post-production/projects/<project_id>/archive-jobs/<job_id>", methods=["GET"]
)
def get_archive_job(project_id, job_id):
    require_roles(LIST_ROLES)
    project = get_project_or_404(project_id)
    job = get_job_or_404(project, job_id)
    return success_object(serialize(job))


@bp.route(
    "/post-production/projects/<project_id>/archive-jobs/<job_id>/start",
    methods=["POST"],
)
def start_archive_job(project_id, job_id):
    require_roles(("MediaManager",))
    project = get_project_or_404(project_id)
    job = get_job_or_404(project, job_id)
    guard_transition(job, "QUEUED", ARCHIVE_TERMINAL, "archive job")
    # No other ArchiveJob for this project may be in WRITING or VERIFYING.
    for other in db.archive_jobs.values():
        if (
            other["project_id"] == project_id
            and other["id"] != job_id
            and other["status"] in ("WRITING", "VERIFYING")
        ):
            raise ApiError(
                ERR_INVALID_STATE,
                "Another ArchiveJob for this project is in WRITING or "
                "VERIFYING",
                409,
            )
    job["status"] = "WRITING"
    touch(job)
    return success_object(serialize(job))


@bp.route(
    "/post-production/projects/<project_id>/archive-jobs/<job_id>/verify",
    methods=["POST"],
)
def verify_archive_job(project_id, job_id):
    require_roles(("MediaManager",))
    project = get_project_or_404(project_id)
    job = get_job_or_404(project, job_id)
    guard_transition(job, "WRITING", ARCHIVE_TERMINAL, "archive job")
    job["status"] = "VERIFYING"
    job["bytes_written"] = _scope_bytes(project_id, job["target_scope"])
    touch(job)
    return success_object(serialize(job))


@bp.route(
    "/post-production/projects/<project_id>/archive-jobs/<job_id>/seal",
    methods=["POST"],
)
def seal_archive_job(project_id, job_id):
    require_roles(("MediaManager",))
    project = get_project_or_404(project_id)
    job = get_job_or_404(project, job_id)
    guard_transition(job, "VERIFYING", ARCHIVE_TERMINAL, "archive job")
    # FULL_PROJECT seal requires the project already in WRAPPING or CLOSED.
    if job["target_scope"] == "FULL_PROJECT" and project["status"] not in (
        "WRAPPING",
        "CLOSED",
    ):
        raise ApiError(
            ERR_INVALID_STATE,
            "A FULL_PROJECT seal requires the project to be in WRAPPING or "
            "CLOSED",
            409,
        )
    sealed_at = logical_clock.now()
    job["status"] = "SEALED"
    job["sealed_at"] = format_iso(sealed_at)
    touch(job)
    # Each in-scope, non-purged MediaAsset gets retained_until := sealed_at +
    # retention_years * 365 days (fixed 365-day years, no leap days).
    for asset in _scope_assets(project_id, job["target_scope"]):
        horizon = sealed_at + timedelta(days=job["retention_years"] * 365)
        asset["retained_until"] = format_iso(horizon)
        touch(asset)
    return success_object(serialize(job))


@bp.route(
    "/post-production/projects/<project_id>/archive-jobs/<job_id>/cancel",
    methods=["POST"],
)
def cancel_archive_job(project_id, job_id):
    require_roles(("MediaManager",))
    project = get_project_or_404(project_id)
    job = get_job_or_404(project, job_id)
    guard_transition(job, "QUEUED", ARCHIVE_TERMINAL, "archive job")
    job["status"] = "CANCELLED"
    touch(job)
    return success_object(serialize(job))


@bp.route(
    "/post-production/projects/<project_id>/archive-jobs/<job_id>/retry",
    methods=["POST"],
)
def retry_archive_job(project_id, job_id):
    require_roles(("MediaManager",))
    project = get_project_or_404(project_id)
    job = get_job_or_404(project, job_id)
    guard_transition(job, "FAILED", ARCHIVE_TERMINAL, "archive job")
    job["status"] = "QUEUED"
    touch(job)
    return success_object(serialize(job))


# ---------------------------------------------------------------------------
# Flat alias
# ---------------------------------------------------------------------------


@bp.route("/post-production/archive-jobs/<job_id>", methods=["GET"])
def get_archive_job_flat(job_id):
    require_roles(LIST_ROLES)
    job = db.archive_jobs.get(job_id)
    if job is None:
        raise ApiError(ERR_NOT_FOUND, f"ArchiveJob {job_id} does not exist", 404)
    return success_object(serialize(job))
