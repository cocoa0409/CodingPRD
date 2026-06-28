"""Warranty plans (PRD 3.10). Authored in PENDING; tier drives coverage window
and maintenance cadence. Activated by install completion; expires lazily on the
logical clock."""

from flask import Blueprint, request

from common import (
    get_json_body,
    paginate,
    public,
    require_enum,
    require_fields,
    stamp_new,
)
from db import db
from lookups import get_child_or_404, get_project_or_404
from middleware import get_auth, require_role
from ownership import enforce_project_ownership
from response import success
from services.calculations import compute_warranty_terms
from services.project_service import expire_warranty_if_due

bp = Blueprint("warranty_plans", __name__)

TIERS = {"BASIC", "PLUS", "PREMIUM"}


@bp.route("/projects/<project_id>/warranty-plans", methods=["POST"])
def create_warranty(project_id):
    _uid, role = get_auth()
    require_role(role, {"SalesRep", "OpsAdmin"})
    get_project_or_404(project_id)
    body = get_json_body()
    require_fields(body, ["tier"])
    tier = require_enum(body, "tier", TIERS)
    coverage_months, visits = compute_warranty_terms(tier)

    rec = {
        "project_id": project_id,
        "tier": tier,
        "coverage_months": coverage_months,
        "maintenance_visits_per_year": visits,
        "start_at": None,
        "expires_at": None,
        "status": "PENDING",
    }
    stamp_new(rec)
    db.warranty_plans[rec["id"]] = rec
    return success(public(rec), status=201)


def _serialize_warranty(plan):
    expire_warranty_if_due(plan)
    return public(plan)


@bp.route("/projects/<project_id>/warranty-plans", methods=["GET"])
def list_warranties(project_id):
    uid, role = get_auth()
    require_role(role, {"SalesRep", "OpsAdmin", "Customer"})
    project = get_project_or_404(project_id)
    enforce_project_ownership(project, uid, role)
    items = [w for w in db.warranty_plans.values() if w["project_id"] == project_id]
    status_filter = request.args.get("status")
    if status_filter is not None:
        for w in items:
            expire_warranty_if_due(w)
        items = [w for w in items if w["status"] == status_filter]
    data, pagination = paginate(items, _serialize_warranty)
    return success(data, status=200, pagination=pagination)


@bp.route("/projects/<project_id>/warranty-plans/<warranty_plan_id>", methods=["GET"])
def get_warranty(project_id, warranty_plan_id):
    uid, role = get_auth()
    require_role(role, {"SalesRep", "OpsAdmin", "Customer"})
    project = get_project_or_404(project_id)
    enforce_project_ownership(project, uid, role)
    rec = get_child_or_404(db.warranty_plans, warranty_plan_id, project_id, "Warranty plan")
    return success(_serialize_warranty(rec), status=200)
