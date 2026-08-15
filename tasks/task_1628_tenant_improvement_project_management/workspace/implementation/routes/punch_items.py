"""PunchItem endpoints."""

from flask import Blueprint, request

from db import store
from middleware import (
    require_roles, check_contractor_ownership, check_tenant_ownership,
    get_project_tenant_ownership,
)
from response import success_object, success_created, success_list
from errors import not_found, invalid_request, invalid_state
from services.util import (
    make_common_fields, bump_version, get_pagination_params, paginate,
    require_fields, is_str,
)

bp = Blueprint("punch_items", __name__)


def _get_punch_or_404(pid):
    p = store.punch_items.get(pid)
    if not p:
        raise not_found("PunchItem not found")
    return p


@bp.route("/api/ti-projects/<id>/punch-items", methods=["POST"])
def create_punch_item(id):
    require_roles("LandlordPM", "BuildingEngineer")
    proj = store.ti_projects.get(id)
    if not proj:
        raise not_found("TIProject not found")
    if proj["status"] != "PUNCH":
        raise invalid_state("Project must be in PUNCH to log punch items")

    body = request.get_json(silent=True) or {}
    require_fields(body, ["assigned_engagement_id", "description", "location", "severity"])
    if not is_str(body["assigned_engagement_id"]):
        raise invalid_request("assigned_engagement_id must be a string")
    if not is_str(body["description"]):
        raise invalid_request("description must be a string")
    if not is_str(body["location"]):
        raise invalid_request("location must be a string")
    if body["severity"] not in ("COSMETIC", "STANDARD", "LIFE_SAFETY"):
        raise invalid_request("severity must be COSMETIC, STANDARD, or LIFE_SAFETY")

    # Engagement must exist
    eng = store.contractor_engagements.get(body["assigned_engagement_id"])
    if not eng:
        raise not_found("ContractorEngagement not found")

    rec = make_common_fields()
    rec.update({
        "project_id": id,
        "assigned_engagement_id": body["assigned_engagement_id"],
        "description": body["description"],
        "location": body["location"],
        "severity": body["severity"],
        "status": "OPEN",
    })
    store.punch_items[rec["id"]] = rec
    return success_created(rec)


@bp.route("/api/ti-projects/<id>/punch-items", methods=["GET"])
def list_project_punch_items(id):
    user_id, role = require_roles(
        "LandlordPM", "LandlordApprover", "TenantRep", "ContractorRep", "BuildingEngineer"
    )
    proj = store.ti_projects.get(id)
    if not proj:
        raise not_found("TIProject not found")
    if role == "TenantRep":
        check_tenant_ownership(user_id, proj["lease_id"])
    limit, offset = get_pagination_params()
    items = [p for p in store.punch_items.values() if p["project_id"] == id]
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/api/contractor-engagements/<id>/punch-items", methods=["GET"])
def list_engagement_punch_items(id):
    user_id, role = require_roles(
        "LandlordPM", "LandlordApprover", "ContractorRep", "BuildingEngineer"
    )
    eng = store.contractor_engagements.get(id)
    if not eng:
        raise not_found("ContractorEngagement not found")
    if role == "ContractorRep":
        check_contractor_ownership(user_id, id)
    limit, offset = get_pagination_params()
    items = [p for p in store.punch_items.values() if p["assigned_engagement_id"] == id]
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/api/punch-items/<id>", methods=["GET"])
def get_punch_item(id):
    user_id, role = require_roles(
        "LandlordPM", "LandlordApprover", "ContractorRep", "BuildingEngineer"
    )
    p = _get_punch_or_404(id)
    if role == "ContractorRep":
        check_contractor_ownership(user_id, p["assigned_engagement_id"])
    return success_object(p)


@bp.route("/api/punch-items/<id>/start", methods=["POST"])
def start_punch_item(id):
    user_id, role = require_roles("ContractorRep")
    p = _get_punch_or_404(id)
    check_contractor_ownership(user_id, p["assigned_engagement_id"])
    if p["status"] != "OPEN":
        raise invalid_state("PunchItem must be in OPEN to start")
    eng = store.contractor_engagements.get(p["assigned_engagement_id"])
    if not eng or eng["status"] != "ACTIVE":
        raise invalid_state("Assigned engagement must be ACTIVE")
    p["status"] = "IN_PROGRESS"
    bump_version(p)
    return success_object(p)


@bp.route("/api/punch-items/<id>/resolve", methods=["POST"])
def resolve_punch_item(id):
    user_id, role = require_roles("ContractorRep")
    p = _get_punch_or_404(id)
    check_contractor_ownership(user_id, p["assigned_engagement_id"])
    if p["status"] != "IN_PROGRESS":
        raise invalid_state("PunchItem must be in IN_PROGRESS to resolve")
    p["status"] = "RESOLVED"
    bump_version(p)
    return success_object(p)


@bp.route("/api/punch-items/<id>/verify", methods=["POST"])
def verify_punch_item(id):
    require_roles("BuildingEngineer")
    p = _get_punch_or_404(id)
    if p["status"] != "RESOLVED":
        raise invalid_state("PunchItem must be in RESOLVED to verify")
    proj = store.ti_projects.get(p["project_id"])
    if not proj or proj["status"] != "PUNCH":
        raise invalid_state("Project must be in PUNCH")
    p["status"] = "VERIFIED"
    bump_version(p)
    return success_object(p)


@bp.route("/api/punch-items/<id>/reopen", methods=["POST"])
def reopen_punch_item(id):
    require_roles("BuildingEngineer")
    p = _get_punch_or_404(id)
    if p["status"] != "RESOLVED":
        raise invalid_state("PunchItem must be in RESOLVED to reopen")
    proj = store.ti_projects.get(p["project_id"])
    if not proj or proj["status"] != "PUNCH":
        raise invalid_state("Project must be in PUNCH")
    p["status"] = "OPEN"
    bump_version(p)
    return success_object(p)
