"""DailiesPackage routes (PRD §3.3)."""

from flask import Blueprint

import db
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_WATERMARK_NONCOMPLIANT,
    ERR_DISTRIBUTION_INVALID,
)
from helpers import (
    new_entity,
    touch,
    now_iso,
    get_json_body,
    require_fields,
    get_pagination,
    get_filter,
    paginate,
)
from middleware import require_roles
from response import success_object, success_list
from routes.projects import get_project_or_404
from routes.watermark_profiles import tier_gate_satisfied
from services.transitions import guard_transition
from services.derived import revoke_dailies_package

bp = Blueprint("dailies", __name__)

PACKAGE_TERMINAL = ("REVOKED",)
LIST_ROLES = ("PostSupervisor", "DailiesCoordinator", "ReviewerLead")


def serialize(package):
    return dict(package)


def get_package_or_404(project, package_id):
    package = db.dailies_packages.get(package_id)
    if package is None or package["project_id"] != project["id"]:
        raise ApiError(
            ERR_NOT_FOUND, f"DailiesPackage {package_id} does not exist", 404
        )
    return package


@bp.route("/post-production/projects/<project_id>/dailies", methods=["POST"])
def create_package(project_id):
    require_roles(("DailiesCoordinator",))
    project = get_project_or_404(project_id)
    body = get_json_body()
    require_fields(body, ("batch_id", "watermark_profile_id", "distribution_list"))
    batch_id = body["batch_id"]
    watermark_profile_id = body["watermark_profile_id"]
    if not isinstance(batch_id, str):
        raise ApiError(ERR_INVALID_REQUEST, "Field 'batch_id' must be a string", 400)
    if not isinstance(watermark_profile_id, str):
        raise ApiError(
            ERR_INVALID_REQUEST,
            "Field 'watermark_profile_id' must be a string",
            400,
        )
    # FK resolution (priority 3)
    batch = db.batches.get(batch_id)
    if batch is None or batch["project_id"] != project_id:
        raise ApiError(ERR_NOT_FOUND, f"MediaBatch {batch_id} does not exist", 404)
    profile = db.watermark_profiles.get(watermark_profile_id)
    if profile is None or profile["project_id"] != project_id:
        raise ApiError(
            ERR_NOT_FOUND,
            f"WatermarkProfile {watermark_profile_id} does not exist",
            404,
        )
    # Body shape (priority 4): distribution_list 1..50 entries, unique,
    # lowercase.
    distribution_list = body["distribution_list"]
    if not isinstance(distribution_list, list):
        raise ApiError(
            ERR_INVALID_REQUEST, "Field 'distribution_list' must be an array", 400
        )
    if not (1 <= len(distribution_list) <= 50):
        raise ApiError(
            ERR_INVALID_REQUEST,
            "Field 'distribution_list' must contain between 1 and 50 entries",
            400,
        )
    for entry in distribution_list:
        if not isinstance(entry, str):
            raise ApiError(
                ERR_INVALID_REQUEST,
                "Field 'distribution_list' entries must be strings",
                400,
            )
    if len(set(distribution_list)) != len(distribution_list):
        raise ApiError(
            ERR_INVALID_REQUEST,
            "Field 'distribution_list' entries must be unique",
            400,
        )
    for entry in distribution_list:
        if entry != entry.lower():
            raise ApiError(
                ERR_INVALID_REQUEST,
                "Field 'distribution_list' entries must be lowercase",
                400,
            )
    package = new_entity(
        {
            "project_id": project_id,
            "batch_id": batch_id,
            "watermark_profile_id": watermark_profile_id,
            "distribution_list": list(distribution_list),
            "status": "DRAFT",
            "published_at": None,
            "revoked_at": None,
            "recipient_count": len(distribution_list),
        }
    )
    db.dailies_packages[package["id"]] = package
    return success_object(serialize(package), 201)


@bp.route("/post-production/projects/<project_id>/dailies", methods=["GET"])
def list_packages(project_id):
    require_roles(LIST_ROLES)
    get_project_or_404(project_id)
    limit, offset = get_pagination()
    items = [p for p in db.dailies_packages.values() if p["project_id"] == project_id]
    batch_id = get_filter("batch_id")
    if batch_id is not None:
        items = [p for p in items if p.get("batch_id") == batch_id]
    status = get_filter("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    window, total = paginate(items, limit, offset)
    return success_list([serialize(p) for p in window], limit, offset, total)


@bp.route(
    "/post-production/projects/<project_id>/dailies/<package_id>", methods=["GET"]
)
def get_package(project_id, package_id):
    require_roles(LIST_ROLES)
    project = get_project_or_404(project_id)
    package = get_package_or_404(project, package_id)
    return success_object(serialize(package))


@bp.route(
    "/post-production/projects/<project_id>/dailies/<package_id>/publish",
    methods=["POST"],
)
def publish_package(project_id, package_id):
    require_roles(("DailiesCoordinator",))
    project = get_project_or_404(project_id)
    package = get_package_or_404(project, package_id)
    # From-state (priority 6)
    guard_transition(package, "DRAFT", PACKAGE_TERMINAL, "dailies package")
    # Project must be ACTIVE — a state precondition of this transition.
    if project["status"] != "ACTIVE":
        raise ApiError(
            ERR_INVALID_STATE,
            f"Project is in state {project['status']}, not ACTIVE",
            409,
        )
    # Watermark compliance (priority 9) is evaluated before the distribution
    # check (priority 10).
    profile = db.watermark_profiles.get(package["watermark_profile_id"])
    if profile is None:
        raise ApiError(
            ERR_NOT_FOUND,
            f"WatermarkProfile {package['watermark_profile_id']} does not exist",
            404,
        )
    if profile["status"] != "ACTIVE" or not tier_gate_satisfied(
        profile, project["security_tier"]
    ):
        raise ApiError(
            ERR_WATERMARK_NONCOMPLIANT,
            "WatermarkProfile is not ACTIVE or watermark_compliance_score "
            "below the project security_tier gate",
            422,
        )
    # Distribution validity (priority 10): non-empty, unique, lowercase; and
    # the referenced batch must be READY.
    dl = package["distribution_list"]
    valid_distribution = (
        len(dl) >= 1
        and len(set(dl)) == len(dl)
        and all(isinstance(e, str) and e == e.lower() for e in dl)
    )
    batch = db.batches.get(package["batch_id"])
    if batch is None:
        raise ApiError(
            ERR_NOT_FOUND,
            f"MediaBatch {package['batch_id']} does not exist",
            404,
        )
    if not valid_distribution or batch["status"] != "READY":
        raise ApiError(
            ERR_DISTRIBUTION_INVALID,
            "distribution_list empty, contains duplicates, non-lowercase "
            "email, or referenced batch not READY",
            422,
        )
    package["status"] = "PUBLISHED"
    package["published_at"] = now_iso()
    touch(package)
    return success_object(serialize(package))


@bp.route(
    "/post-production/projects/<project_id>/dailies/<package_id>/revoke",
    methods=["POST"],
)
def revoke_package(project_id, package_id):
    require_roles(("DailiesCoordinator",))
    project = get_project_or_404(project_id)
    package = get_package_or_404(project, package_id)
    guard_transition(package, "PUBLISHED", PACKAGE_TERMINAL, "dailies package")
    revoke_dailies_package(package)
    return success_object(serialize(package))
