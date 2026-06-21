"""ServicePlan endpoints (PRD §3.3)."""
from flask import Blueprint, request

from db import db
from errors import err
from middleware import require_roles
from response import success, success_list
from services.common import (
    new_record,
    optional_enum,
    optional_int,
    paginate,
    require_enum,
    require_int,
    require_json_object,
    require_str,
    serialize,
    sort_by_created,
    touch,
)
from services.derived import compute_visits_remaining
from services.lookup import get_plan_or_404, get_pool_or_404

bp = Blueprint("service_plans", __name__)

PLAN_TYPES = {"RECURRING", "ONE_TIME"}
FREQUENCIES = {"WEEKLY", "BIWEEKLY", "MONTHLY", "NONE"}


def _serialize_plan(plan):
    out = serialize(plan)
    out["visits_remaining"] = plan["visits_remaining"]
    return out


@bp.post("/service-plans")
@require_roles("AccountManager")
def create_plan():
    with db.lock:
        body = require_json_object(request.get_json(silent=True))
        pool_id = require_str(body, "pool_id")
        plan_type = require_enum(body, "plan_type", PLAN_TYPES)
        frequency = optional_enum(body, "frequency", FREQUENCIES, "NONE")
        per_visit_rate_cents = require_int(body, "per_visit_rate_cents", minimum=0)
        prepaid_visit_count = optional_int(body, "prepaid_visit_count", 0, minimum=0)
        # Existence (priority 3) before business constraint (priority 6).
        get_pool_or_404(pool_id)
        # ONE_TIME must have frequency NONE; RECURRING must have frequency != NONE.
        if plan_type == "ONE_TIME" and frequency != "NONE":
            raise err("ERR_FREQUENCY_PLAN_MISMATCH", "ONE_TIME plan must have frequency NONE")
        if plan_type == "RECURRING" and frequency == "NONE":
            raise err("ERR_FREQUENCY_PLAN_MISMATCH", "RECURRING plan must have a non-NONE frequency")
        rec = new_record(
            {
                "pool_id": pool_id,
                "plan_type": plan_type,
                "frequency": frequency,
                "per_visit_rate_cents": per_visit_rate_cents,
                "prepaid_visit_count": prepaid_visit_count,
                "visits_remaining": 0,
                "status": "DRAFT",
            }
        )
        # Seed visits_remaining from the formula (no visits yet).
        rec["visits_remaining"] = compute_visits_remaining(rec)
        db.service_plans[rec["id"]] = rec
        return success(_serialize_plan(rec), 201)


@bp.get("/service-plans/<plan_id>")
@require_roles("AccountManager", "RouteManager", "Customer")
def get_plan(plan_id):
    with db.lock:
        plan = get_plan_or_404(plan_id)
        return success(_serialize_plan(plan), 200)


@bp.get("/service-plans")
@require_roles("AccountManager", "RouteManager")
def list_plans():
    with db.lock:
        limit, offset = paginate(request.args)
        pool_id = request.args.get("pool_id")
        items = list(db.service_plans.values())
        if pool_id is not None:
            items = [p for p in items if p["pool_id"] == pool_id]
        items = sort_by_created(items)
        total = len(items)
        page = items[offset : offset + limit]
        return success_list([_serialize_plan(p) for p in page], limit, offset, total)


@bp.post("/service-plans/<plan_id>/activate")
@require_roles("AccountManager")
def activate_plan(plan_id):
    with db.lock:
        plan = get_plan_or_404(plan_id)
        # State validity (priority 5). Activation requires DRAFT and ACTIVE customer;
        # activating for a suspended customer is rejected as an invalid operation.
        pool = db.pools.get(plan["pool_id"])
        customer = db.customers.get(pool["customer_id"]) if pool else None
        if plan["status"] != "DRAFT" or not customer or customer["account_status"] != "ACTIVE":
            raise err("ERR_INVALID_STATE", "Plan cannot be activated from its current state")
        plan["status"] = "ACTIVE"
        touch(plan)
        return success(_serialize_plan(plan), 200)


@bp.post("/service-plans/<plan_id>/cancel")
@require_roles("AccountManager")
def cancel_plan(plan_id):
    with db.lock:
        plan = get_plan_or_404(plan_id)
        if plan["status"] != "ACTIVE":
            raise err("ERR_INVALID_STATE", "Plan cannot be cancelled from its current state")
        plan["status"] = "CANCELLED"
        touch(plan)
        # Cascade: cancel every SCHEDULED/RECOVERY_SCHEDULED visit on this plan.
        for v in db.visits.values():
            if v["plan_id"] == plan["id"] and v["status"] in ("SCHEDULED", "RECOVERY_SCHEDULED"):
                v["status"] = "CANCELLED"
                touch(v)
        return success(_serialize_plan(plan), 200)
