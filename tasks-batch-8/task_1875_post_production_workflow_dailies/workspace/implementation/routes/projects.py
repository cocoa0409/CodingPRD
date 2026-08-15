"""Project routes (PRD §3.1, §3.8)."""

import re

from flask import Blueprint

import db
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_PROJECT_NOT_WRAPPABLE,
)
from helpers import (
    new_entity,
    touch,
    get_json_body,
    require_fields,
    check_string,
    check_number,
    check_int,
    check_enum,
    get_pagination,
    get_filter,
    paginate,
)
from middleware import require_roles
from response import success_object, success_list
from services.transitions import guard_transition
from services.derived import revoke_dailies_package

bp = Blueprint("projects", __name__)

FPS_ALLOWED = (23.976, 24, 25, 29.97, 30)
SECURITY_TIERS = ("STANDARD", "ELEVATED", "LOCKDOWN")
PROJECT_TERMINAL = ("ARCHIVED",)

LIST_ROLES = (
    "PostSupervisor",
    "MediaManager",
    "ConformEditor",
    "DailiesCoordinator",
    "ReviewerLead",
    "QCOperator",
    "FacilityAdmin",
)
GET_ROLES = LIST_ROLES + ("VendorRep", "Artist")


def serialize(project):
    return dict(project)


def get_project_or_404(project_id):
    project = db.projects.get(project_id)
    if project is None:
        raise ApiError(ERR_NOT_FOUND, f"Project {project_id} does not exist", 404)
    return project


@bp.route("/post-production/projects", methods=["POST"])
def create_project():
    require_roles(("PostSupervisor",))
    body = get_json_body()
    require_fields(
        body,
        (
            "title",
            "client_code",
            "fps",
            "resolution_width",
            "resolution_height",
            "storage_quota_gb",
            "security_tier",
        ),
    )
    title = check_string(body, "title")
    client_code = check_string(body, "client_code")
    if not re.fullmatch(r"[A-Z0-9]{3,8}", client_code):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Field 'client_code' must be 3-8 uppercase alphanumeric characters",
            400,
        )
    fps = check_number(body, "fps")
    if fps not in FPS_ALLOWED:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Field 'fps' must be one of 23.976, 24, 25, 29.97, 30",
            400,
        )
    resolution_width = check_int(body, "resolution_width", min_v=1)
    resolution_height = check_int(body, "resolution_height", min_v=1)
    storage_quota_gb = check_int(body, "storage_quota_gb", min_v=0)
    security_tier = check_enum(body, "security_tier", SECURITY_TIERS)

    project = new_entity(
        {
            "title": title,
            "client_code": client_code,
            "fps": fps,
            "resolution_width": resolution_width,
            "resolution_height": resolution_height,
            "storage_quota_gb": storage_quota_gb,
            "storage_used_gb": 0,
            "security_tier": security_tier,
            "status": "SETUP",
            "open_change_list_count": 0,
            "conform_ready": False,
        }
    )
    db.projects[project["id"]] = project
    return success_object(serialize(project), 201)


@bp.route("/post-production/projects", methods=["GET"])
def list_projects():
    require_roles(LIST_ROLES)
    limit, offset = get_pagination()
    items = list(db.projects.values())
    status = get_filter("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    tier = get_filter("security_tier")
    if tier is not None:
        items = [p for p in items if p["security_tier"] == tier]
    window, total = paginate(items, limit, offset)
    return success_list([serialize(p) for p in window], limit, offset, total)


@bp.route("/post-production/projects/<project_id>", methods=["GET"])
def get_project(project_id):
    require_roles(GET_ROLES)
    project = get_project_or_404(project_id)
    return success_object(serialize(project))


@bp.route("/post-production/projects/<project_id>/activate", methods=["POST"])
def activate_project(project_id):
    require_roles(("PostSupervisor",))
    project = get_project_or_404(project_id)
    guard_transition(project, "SETUP", PROJECT_TERMINAL, "project")
    has_bay = any(
        b["project_id"] == project_id and b["status"] == "AVAILABLE"
        for b in db.edit_bays.values()
    )
    has_profile = any(
        w["project_id"] == project_id and w["status"] == "ACTIVE"
        for w in db.watermark_profiles.values()
    )
    if not (has_bay and has_profile):
        raise ApiError(
            ERR_PROJECT_NOT_WRAPPABLE,
            "Project activation requires at least one EditBay in status "
            "AVAILABLE and at least one WatermarkProfile in status ACTIVE",
            422,
        )
    project["status"] = "ACTIVE"
    touch(project)
    return success_object(serialize(project))


@bp.route("/post-production/projects/<project_id>/wrap", methods=["POST"])
def wrap_project(project_id):
    require_roles(("PostSupervisor",))
    project = get_project_or_404(project_id)
    guard_transition(project, "ACTIVE", PROJECT_TERMINAL, "project")
    # Every deliverable must be in {DELIVERED, REJECTED, SUPERSEDED}.
    for d in db.deliverables.values():
        if d["project_id"] == project_id and d["status"] not in (
            "DELIVERED",
            "REJECTED",
            "SUPERSEDED",
        ):
            raise ApiError(
                ERR_PROJECT_NOT_WRAPPABLE,
                "All Deliverables for the project must be in DELIVERED, "
                "REJECTED, or SUPERSEDED before wrap",
                422,
            )
    # ReviewRounds with target_kind in {CUT, VENDOR_RETURN, DELIVERABLE} must
    # be in {APPROVED, REJECTED, VOID}; DAILIES rounds may still be OPEN.
    for rr in db.review_rounds.values():
        if rr["project_id"] != project_id:
            continue
        if rr["target_kind"] == "DAILIES":
            continue
        if rr["status"] not in ("APPROVED", "REJECTED", "VOID"):
            raise ApiError(
                ERR_PROJECT_NOT_WRAPPABLE,
                "All ReviewRounds with target_kind CUT, VENDOR_RETURN, or "
                "DELIVERABLE must be in APPROVED, REJECTED, or VOID before wrap",
                422,
            )
    if project.get("open_change_list_count", 0) != 0:
        raise ApiError(
            ERR_PROJECT_NOT_WRAPPABLE,
            "open_change_list_count must be zero before wrap",
            422,
        )
    project["status"] = "WRAPPING"
    touch(project)
    # Cascade: every PUBLISHED dailies package -> REVOKED (which voids OPEN
    # review rounds targeting it, which void their OPEN notes).
    for pkg in db.dailies_packages.values():
        if pkg["project_id"] == project_id and pkg["status"] == "PUBLISHED":
            revoke_dailies_package(pkg)
    return success_object(serialize(project))


@bp.route("/post-production/projects/<project_id>/close", methods=["POST"])
def close_project(project_id):
    require_roles(("PostSupervisor",))
    project = get_project_or_404(project_id)
    guard_transition(project, "WRAPPING", PROJECT_TERMINAL, "project")
    jobs = [j for j in db.archive_jobs.values() if j["project_id"] == project_id]
    has_sealed = any(j["status"] == "SEALED" for j in jobs)
    has_open = any(j["status"] in ("QUEUED", "WRITING", "VERIFYING") for j in jobs)
    if not has_sealed or has_open:
        raise ApiError(
            ERR_PROJECT_NOT_WRAPPABLE,
            "Project close requires at least one ArchiveJob in SEALED state "
            "and none in QUEUED, WRITING, or VERIFYING",
            422,
        )
    project["status"] = "CLOSED"
    touch(project)
    # Cascade: every EditBay still AVAILABLE -> MAINTENANCE.
    for bay in db.edit_bays.values():
        if bay["project_id"] == project_id and bay["status"] == "AVAILABLE":
            bay["status"] = "MAINTENANCE"
            touch(bay)
    return success_object(serialize(project))


@bp.route("/post-production/projects/<project_id>/archive", methods=["POST"])
def archive_project(project_id):
    require_roles(("PostSupervisor",))
    project = get_project_or_404(project_id)
    guard_transition(project, "CLOSED", PROJECT_TERMINAL, "project")
    for j in db.archive_jobs.values():
        if j["project_id"] == project_id and j["status"] not in (
            "SEALED",
            "CANCELLED",
        ):
            raise ApiError(
                ERR_PROJECT_NOT_WRAPPABLE,
                "Project archive requires every ArchiveJob to be in SEALED "
                "or CANCELLED",
                422,
            )
    project["status"] = "ARCHIVED"
    touch(project)
    return success_object(serialize(project))
