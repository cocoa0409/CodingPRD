"""RetrofitProject and RetrofitLineItem endpoints."""
from flask import Blueprint, request, Response

import db
from errors import (
    ApiError,
    ERR_BUDGET_EXCEEDED,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_POSTURE_STOP_WORK,
    ERR_PROJECT_EMPTY,
    ERR_STALE_VERSION,
    ERR_TRIGGER_FINDING_INVALID,
    ERR_TRIGGER_FINDING_OPEN,
)
from middleware import require_roles
from response import success_object
from services import calculations as calc
from services.common import (
    get_flat_or_404,
    get_site_or_404,
    init_common,
    paginate,
    parse_body,
    require_fields,
    serialize,
    touch,
    validate_enum,
    validate_int,
    validate_str,
)

bp = Blueprint("retrofit", __name__)

READ_ROLES = ("ComplianceEngineer", "ComplianceManager", "InspectorUser")
RISK_TIERS = {"LOW", "MEDIUM", "HIGH"}


def _get_project(site_id, project_id):
    site = get_site_or_404(site_id)
    project = db.retrofit_projects.get(project_id)
    if project is None or project["site_id"] != site["id"]:
        raise ApiError(ERR_NOT_FOUND, f"RetrofitProject {project_id} not found", 404)
    return site, project


def _get_line_item(site_id, project_id, line_item_id):
    site, project = _get_project(site_id, project_id)
    item = db.retrofit_line_items.get(line_item_id)
    if item is None or item["project_id"] != project["id"]:
        raise ApiError(ERR_NOT_FOUND, f"RetrofitLineItem {line_item_id} not found", 404)
    return site, project, item


@bp.route("/api/sites/<id>/retrofit-projects", methods=["POST"])
def create_project(id):
    require_roles("ComplianceEngineer")
    site = get_site_or_404(id)
    body = parse_body()
    require_fields(body, ["name", "trigger_finding_id", "scope_budget_cents"])
    validate_str(body, "name")
    validate_int(body, "scope_budget_cents", gt=0)

    finding = db.inspection_findings.get(body["trigger_finding_id"])
    if finding is None:
        raise ApiError(ERR_NOT_FOUND, "trigger_finding_id does not resolve", 404)
    # Ensure the finding belongs to an inspection on this site
    insp = db.inspections.get(finding["inspection_id"])
    if insp is None or insp["site_id"] != site["id"]:
        raise ApiError(ERR_NOT_FOUND, "trigger_finding_id does not resolve at this site", 404)

    project = {
        "site_id": site["id"],
        "name": body["name"],
        "trigger_finding_id": body["trigger_finding_id"],
        "scope_budget_cents": body["scope_budget_cents"],
        "estimated_cost_cents": 0,
        "contingency_cents": 0,
        "total_projected_cents": 0,
        "contingency_rounding_cents": 0,
        "status": "SCOPING",
    }
    init_common(project)
    db.retrofit_projects[project["id"]] = project
    return success_object(serialize(project), 201)


@bp.route("/api/sites/<id>/retrofit-projects", methods=["GET"])
def list_projects(id):
    require_roles(*READ_ROLES)
    site = get_site_or_404(id)
    items = [p for p in db.retrofit_projects.values() if p["site_id"] == site["id"]]
    filters = {}
    if request.args.get("status") is not None:
        filters["status"] = "status"
    if request.args.get("trigger_finding_id") is not None:
        filters["trigger_finding_id"] = "trigger_finding_id"
    return paginate(items, filters)


@bp.route("/api/sites/<id>/retrofit-projects/<project_id>", methods=["GET"])
def get_project(id, project_id):
    require_roles(*READ_ROLES)
    _, project = _get_project(id, project_id)
    return success_object(serialize(project), 200)


@bp.route("/api/sites/<id>/retrofit-projects/<project_id>/line-items", methods=["POST"])
def create_line_item(id, project_id):
    require_roles("ComplianceEngineer")
    site, project = _get_project(id, project_id)
    body = parse_body()
    require_fields(body, ["description", "cost_cents", "risk_tier"])
    validate_str(body, "description")
    validate_int(body, "cost_cents", gt=0)
    validate_enum(body, "risk_tier", RISK_TIERS)

    item = {
        "project_id": project["id"],
        "description": body["description"],
        "cost_cents": body["cost_cents"],
        "risk_tier": body["risk_tier"],
    }
    init_common(item)
    db.retrofit_line_items[item["id"]] = item
    calc.retrofit_contingency(project, site)
    touch(project)
    return success_object(serialize(item), 201)


@bp.route("/api/sites/<id>/retrofit-projects/<project_id>/line-items", methods=["GET"])
def list_line_items(id, project_id):
    require_roles(*READ_ROLES)
    site, project = _get_project(id, project_id)
    items = [li for li in db.retrofit_line_items.values() if li["project_id"] == project["id"]]
    filters = {}
    if request.args.get("risk_tier") is not None:
        filters["risk_tier"] = "risk_tier"
    return paginate(items, filters)


@bp.route("/api/sites/<id>/retrofit-projects/<project_id>/line-items/<line_item_id>", methods=["PATCH"])
def update_line_item(id, project_id, line_item_id):
    require_roles("ComplianceEngineer")
    site, project, item = _get_line_item(id, project_id, line_item_id)
    body = parse_body()
    validate_str(body, "description")
    validate_int(body, "cost_cents", gt=0)
    validate_enum(body, "risk_tier", RISK_TIERS)

    changed = False
    for f in ("description", "cost_cents", "risk_tier"):
        if f in body and body[f] is not None:
            item[f] = body[f]
            changed = True
    if changed:
        touch(item)
        calc.retrofit_contingency(project, site)
        touch(project)
    return success_object(serialize(item), 200)


@bp.route("/api/sites/<id>/retrofit-projects/<project_id>/line-items/<line_item_id>", methods=["DELETE"])
def delete_line_item(id, project_id, line_item_id):
    require_roles("ComplianceEngineer")
    site, project, item = _get_line_item(id, project_id, line_item_id)
    del db.retrofit_line_items[item["id"]]
    calc.retrofit_contingency(project, site)
    touch(project)
    return Response(status=204)


@bp.route("/api/sites/<id>/retrofit-projects/<project_id>/finalize_estimate", methods=["POST"])
def finalize_estimate(id, project_id):
    require_roles("ComplianceEngineer")
    site, project = _get_project(id, project_id)
    if project["status"] != "SCOPING":
        raise ApiError(ERR_INVALID_STATE, "Project is not in SCOPING", 409)

    has_items = any(li["project_id"] == project["id"] for li in db.retrofit_line_items.values())
    if not has_items:
        raise ApiError(ERR_PROJECT_EMPTY, "Project has no line items", 422)

    calc.retrofit_contingency(project, site)

    if project["total_projected_cents"] > project["scope_budget_cents"]:
        raise ApiError(ERR_BUDGET_EXCEEDED, "Total projected cost exceeds scope budget", 422)

    body = parse_body()
    expected = body.get("expected_project_version")
    if expected is not None:
        if not isinstance(expected, int) or isinstance(expected, bool):
            raise ApiError(ERR_STALE_VERSION, "expected_project_version mismatch", 412)
        if expected != project["version"]:
            raise ApiError(ERR_STALE_VERSION, "expected_project_version mismatch", 412)

    project["status"] = "ESTIMATED"
    touch(project)
    return success_object(serialize(project), 200)


@bp.route("/api/sites/<id>/retrofit-projects/<project_id>/approve", methods=["POST"])
def approve_project(id, project_id):
    require_roles("ComplianceManager")
    site, project = _get_project(id, project_id)
    if project["status"] != "ESTIMATED":
        raise ApiError(ERR_INVALID_STATE, "Project is not ESTIMATED", 409)
    finding = db.inspection_findings.get(project["trigger_finding_id"])
    if (
        finding is None
        or finding["severity"] != "CRITICAL"
        or finding["status"] not in ("OPEN", "IN_PROGRESS", "RESOLVED")
    ):
        raise ApiError(ERR_TRIGGER_FINDING_INVALID, "Trigger finding is not a CRITICAL active finding", 422)

    project["status"] = "APPROVED"
    touch(project)
    if finding["status"] == "OPEN":
        finding["status"] = "IN_PROGRESS"
        touch(finding)
    calc.site_posture_derivation(site)
    touch(site)
    return success_object(serialize(project), 200)


@bp.route("/api/sites/<id>/retrofit-projects/<project_id>/start_execution", methods=["POST"])
def start_execution(id, project_id):
    require_roles("ComplianceEngineer")
    site, project = _get_project(id, project_id)
    if project["status"] != "APPROVED":
        raise ApiError(ERR_INVALID_STATE, "Project is not APPROVED", 409)
    if site["posture"] == "STOP_WORK":
        raise ApiError(ERR_POSTURE_STOP_WORK, "Site is in STOP_WORK posture", 409)
    project["status"] = "IN_EXECUTION"
    touch(project)
    return success_object(serialize(project), 200)


@bp.route("/api/sites/<id>/retrofit-projects/<project_id>/close", methods=["POST"])
def close_project(id, project_id):
    require_roles("ComplianceManager")
    site, project = _get_project(id, project_id)
    if project["status"] != "IN_EXECUTION":
        raise ApiError(ERR_INVALID_STATE, "Project is not IN_EXECUTION", 409)
    finding = db.inspection_findings.get(project["trigger_finding_id"])
    if finding is None or finding["status"] != "VERIFIED":
        raise ApiError(ERR_TRIGGER_FINDING_OPEN, "Trigger finding is not VERIFIED", 422)
    project["status"] = "CLOSED"
    touch(project)
    calc.site_posture_derivation(site)
    touch(site)
    return success_object(serialize(project), 200)


@bp.route("/api/sites/<id>/retrofit-projects/<project_id>/cancel", methods=["POST"])
def cancel_project(id, project_id):
    require_roles("ComplianceManager")
    site, project = _get_project(id, project_id)
    if project["status"] not in ("SCOPING", "ESTIMATED"):
        raise ApiError(ERR_INVALID_STATE, "Only SCOPING or ESTIMATED projects can be cancelled", 409)
    project["status"] = "CANCELLED"
    touch(project)
    return success_object(serialize(project), 200)


# ----- Flat endpoints -----
@bp.route("/api/retrofit-projects/<id>", methods=["GET"])
def get_project_flat(id):
    require_roles(*READ_ROLES)
    project = get_flat_or_404(db.retrofit_projects, id, "RetrofitProject")
    return success_object(serialize(project), 200)


@bp.route("/api/retrofit-projects/<id>/line-items", methods=["GET"])
def list_project_line_items_flat(id):
    require_roles(*READ_ROLES)
    project = get_flat_or_404(db.retrofit_projects, id, "RetrofitProject")
    items = [li for li in db.retrofit_line_items.values() if li["project_id"] == project["id"]]
    return paginate(items)
