"""Reviewer routes."""
from flask import Blueprint, request

from authz import ALL_ROLES, PROJECT_MANAGER, require_roles
from db import store
from errors import project_not_found, reviewer_not_found
from respond import success
from serialize import ser_reviewer
from services import require_setup_or_active
from store_ops import (
    json_body,
    new_common_fields,
    new_id,
    opt_enum,
    opt_int,
    paginate,
    req_enum,
    req_str,
    sorted_by_creation,
    touch,
)

bp = Blueprint("reviewers", __name__)

DISCIPLINES = ("ARCH", "STRUCT", "MEP", "CIVIL")
REVIEWER_STATUSES = ("ACTIVE", "INACTIVE")


def get_reviewer_or_404(reviewer_id):
    r = store.reviewers.get(reviewer_id)
    if r is None:
        raise reviewer_not_found()
    return r


@bp.route("/v1/projects/<projectId>/reviewers", methods=["POST"])
def create_reviewer(projectId):
    require_roles([PROJECT_MANAGER])
    project = store.projects.get(projectId)
    if project is None:
        raise project_not_found()
    require_setup_or_active(project)
    data = json_body()
    display_name = req_str(data, "display_name")
    discipline = req_enum(data, "discipline", DISCIPLINES)
    review_capacity = opt_int(data, "review_capacity", 3, minimum=1)
    reviewer = {
        "id": new_id(),
        "_seq": next(store.seq),
        **new_common_fields(),
        "project_id": projectId,
        "display_name": display_name,
        "discipline": discipline,
        "review_capacity": review_capacity,
        "open_review_count": 0,
        "reviewer_status": "ACTIVE",
    }
    store.reviewers[reviewer["id"]] = reviewer
    return success(ser_reviewer(reviewer), status=201)


@bp.route("/v1/projects/<projectId>/reviewers", methods=["GET"])
def list_project_reviewers(projectId):
    require_roles(ALL_ROLES)
    project = store.projects.get(projectId)
    if project is None:
        raise project_not_found()
    items = sorted_by_creation(
        [r for r in store.reviewers.values() if r["project_id"] == projectId]
    )
    page, pagination = paginate(items)
    return success([ser_reviewer(r) for r in page], response_type="array", pagination=pagination)


@bp.route("/v1/reviewers", methods=["GET"])
def list_reviewers():
    require_roles(ALL_ROLES)
    items = list(store.reviewers.values())
    project_id = request.args.get("project_id")
    if project_id:
        items = [r for r in items if r["project_id"] == project_id]
    discipline = request.args.get("discipline")
    if discipline:
        items = [r for r in items if r["discipline"] == discipline]
    reviewer_status = request.args.get("reviewer_status")
    if reviewer_status:
        items = [r for r in items if r["reviewer_status"] == reviewer_status]
    items = sorted_by_creation(items)
    page, pagination = paginate(items)
    return success([ser_reviewer(r) for r in page], response_type="array", pagination=pagination)


@bp.route("/v1/reviewers/<reviewerId>", methods=["GET"])
def get_reviewer(reviewerId):
    require_roles(ALL_ROLES)
    reviewer = get_reviewer_or_404(reviewerId)
    return success(ser_reviewer(reviewer))


@bp.route("/v1/reviewers/<reviewerId>", methods=["PATCH"])
def patch_reviewer(reviewerId):
    require_roles([PROJECT_MANAGER])
    reviewer = get_reviewer_or_404(reviewerId)
    data = json_body()
    if "reviewer_status" in data and data["reviewer_status"] is not None:
        reviewer["reviewer_status"] = opt_enum(data, "reviewer_status", REVIEWER_STATUSES)
    if "review_capacity" in data and data["review_capacity"] is not None:
        reviewer["review_capacity"] = opt_int(data, "review_capacity", None, minimum=1)
    touch(reviewer)
    return success(ser_reviewer(reviewer))
