"""Subcontractor routes."""
from flask import Blueprint, request

from authz import ALL_ROLES, PROJECT_ENGINEER, require_roles
from db import store
from errors import project_not_found, subcontractor_not_found
from respond import success
from serialize import ser_subcontractor
from services import require_setup_or_active
from store_ops import (
    json_body,
    new_common_fields,
    new_id,
    opt_str,
    paginate,
    req_str,
    sorted_by_creation,
)

bp = Blueprint("subcontractors", __name__)


def get_subcontractor_or_404(sub_id):
    s = store.subcontractors.get(sub_id)
    if s is None:
        raise subcontractor_not_found()
    return s


@bp.route("/v1/projects/<projectId>/subcontractors", methods=["POST"])
def create_subcontractor(projectId):
    require_roles([PROJECT_ENGINEER])
    project = store.projects.get(projectId)
    if project is None:
        raise project_not_found()
    require_setup_or_active(project)
    data = json_body()
    company_name = req_str(data, "company_name")
    trade = req_str(data, "trade")
    contact_email = opt_str(data, "contact_email", "")
    sub = {
        "id": new_id(),
        "_seq": next(store.seq),
        **new_common_fields(),
        "project_id": projectId,
        "company_name": company_name,
        "trade": trade,
        "contact_email": contact_email,
        "late_ack_count": 0,
        "standing": "GOOD",
    }
    store.subcontractors[sub["id"]] = sub
    return success(ser_subcontractor(sub), status=201)


@bp.route("/v1/projects/<projectId>/subcontractors", methods=["GET"])
def list_project_subs(projectId):
    require_roles(ALL_ROLES)
    project = store.projects.get(projectId)
    if project is None:
        raise project_not_found()
    items = sorted_by_creation(
        [s for s in store.subcontractors.values() if s["project_id"] == projectId]
    )
    page, pagination = paginate(items)
    return success([ser_subcontractor(s) for s in page], response_type="array", pagination=pagination)


@bp.route("/v1/subcontractors", methods=["GET"])
def list_subcontractors():
    require_roles(ALL_ROLES)
    items = list(store.subcontractors.values())
    project_id = request.args.get("project_id")
    if project_id:
        items = [s for s in items if s["project_id"] == project_id]
    standing = request.args.get("standing")
    if standing:
        items = [s for s in items if s["standing"] == standing]
    items = sorted_by_creation(items)
    page, pagination = paginate(items)
    return success([ser_subcontractor(s) for s in page], response_type="array", pagination=pagination)


@bp.route("/v1/subcontractors/<subcontractorId>", methods=["GET"])
def get_subcontractor(subcontractorId):
    require_roles(ALL_ROLES)
    sub = get_subcontractor_or_404(subcontractorId)
    return success(ser_subcontractor(sub))
