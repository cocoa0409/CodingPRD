"""Marketplace-wide pricing-plan reads and retirement."""
from flask import Blueprint

from core import (
    authenticate,
    db,
    fail,
    filter_eq,
    ok,
    ok_list,
    ordered,
    pagination,
    paginate,
    public,
    require_owner,
    touch,
)
from services import lookup

bp = Blueprint("pricing_plans", __name__)


def _owner_of(plan):
    app = db.apps.get(plan["app_id"])
    return app["developer_id"] if app else None


@bp.get("/api/pricing-plans")
def list_plans():
    authenticate({"Developer", "PlatformAdmin", "FinanceOps", "StorefrontService"})
    limit, offset = pagination()
    rows = ordered(db.pricing_plans)
    rows = filter_eq(rows, "app_id")
    rows = filter_eq(rows, "kind")
    rows = filter_eq(rows, "status")
    items, total = paginate(rows, limit, offset)
    return ok_list(items, limit, offset, total)


@bp.get("/api/pricing-plans/<pricing_plan_id>")
def read_plan(pricing_plan_id):
    authenticate({"Developer", "PlatformAdmin", "FinanceOps", "StorefrontService"})
    plan = lookup("pricing_plans", pricing_plan_id)
    require_owner(_owner_of(plan))
    return ok(public(plan))


@bp.post("/api/pricing-plans/<pricing_plan_id>/retire")
def retire_plan(pricing_plan_id):
    authenticate({"Developer"})
    plan = lookup("pricing_plans", pricing_plan_id)
    require_owner(_owner_of(plan))
    if plan["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE", "Plan is not ACTIVE.")
    plan["status"] = "RETIRED"
    touch(plan)
    return ok(public(plan))
