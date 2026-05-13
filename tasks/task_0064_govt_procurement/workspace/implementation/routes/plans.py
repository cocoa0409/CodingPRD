"""Procurement plan + plan-item routes."""

from flask import Blueprint, request

from common import get_json_body, get_pagination, slice_page
from middleware import require_roles
from response import paginated, success
from services import plan as svc


bp = Blueprint("plans", __name__, url_prefix="/procurement")


@bp.post("/plans")
@require_roles("ProcurementOfficer")
def create_plan():
    body = get_json_body()
    agency_id = body.get("agency_id")
    fiscal_year = body.get("fiscal_year")
    p = svc.create_plan(agency_id, fiscal_year)
    return success(p, 201)


@bp.post("/plans/<pid>/items")
@require_roles("ProcurementOfficer")
def add_item(pid):
    body = get_json_body()
    title = body.get("title")
    category = body.get("category")
    budget_cents = body.get("budget_cents")
    item = svc.add_plan_item(pid, title, category, budget_cents)
    return success(item, 201)


@bp.post("/plan-items/<iid>/approve")
@require_roles("ProcurementOfficer")
def approve_item(iid):
    return success(svc.approve_plan_item(iid), 200)


@bp.post("/plan-items/<iid>/reject")
@require_roles("ProcurementOfficer")
def reject_item(iid):
    return success(svc.reject_plan_item(iid), 200)


@bp.post("/plan-items/<iid>/cancel")
@require_roles("ProcurementOfficer")
def cancel_item(iid):
    return success(svc.cancel_plan_item(iid), 200)


@bp.post("/plans/<pid>/submit-review")
@require_roles("ProcurementOfficer")
def submit_review(pid):
    return success(svc.submit_review(pid), 200)


@bp.post("/plans/<pid>/publish")
@require_roles("ProcurementOfficer")
def publish_plan(pid):
    return success(svc.publish_plan(pid), 200)


@bp.post("/plans/<pid>/reject")
@require_roles("Regulator")
def reject_plan(pid):
    return success(svc.reject_plan(pid), 200)


@bp.post("/plans/<pid>/begin-amendment")
@require_roles("ProcurementOfficer")
def begin_amendment(pid):
    return success(svc.begin_amendment(pid), 200)


@bp.post("/plans/<pid>/archive")
@require_roles("ProcurementOfficer")
def archive_plan(pid):
    return success(svc.archive_plan(pid), 200)


@bp.get("/plans")
@require_roles("ProcurementOfficer", "Regulator", "Supplier")
def list_plans():
    from db import db

    limit, offset = get_pagination()
    status_f = request.args.get("status")
    fy_f = request.args.get("fiscal_year")
    items = list(db.plans.values())
    if status_f:
        items = [p for p in items if p["status"] == status_f]
    if fy_f:
        try:
            fy = int(fy_f)
            items = [p for p in items if p["fiscal_year"] == fy]
        except (ValueError, TypeError):
            from errors import ERR_VALIDATION, raise_error
            raise_error(ERR_VALIDATION, "fiscal_year must be integer")
    items.sort(key=lambda p: p["created_at"])
    page, total = slice_page(items, limit, offset)
    return paginated(page, limit, offset, total, 200)


@bp.get("/plans/<pid>")
@require_roles("ProcurementOfficer", "Regulator", "Supplier")
def get_plan(pid):
    return success(svc.get_plan_or_404(pid), 200)
