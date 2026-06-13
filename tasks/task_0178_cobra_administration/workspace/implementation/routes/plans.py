"""Plan, clock, beneficiary-list, and tick endpoints."""
from flask import Blueprint, request, g

from db import store
from errors import ApiError
from middleware import require_role
from models import _common, serialize, PLAN_FIELDS, BENEFICIARY_FIELDS
from response import object_response, array_response
from timeutil import parse_dt, now_iso
from services import lifecycle
from services.lookup import (
    get_or_404, require_body, require_string, require_positive_int,
    require_number, require_int, paginate, sorted_by_creation,
)

bp = Blueprint("plans", __name__)


@bp.post("/plans")
@require_role({"PlanAdministrator"})
def create_plan():
    body = require_body()
    name = require_string(body, "name")
    applicable = require_positive_int(body, "applicable_premium_cents")
    standard_fee = require_number(body, "standard_admin_fee_pct", required=False,
                                  default=0.02, minimum=0, maximum=0.02)
    disability_fee = require_number(body, "disability_admin_fee_pct", required=False,
                                    default=0.50, minimum=0, maximum=0.50)
    employer_notice_days = require_int(body, "employer_notice_days", required=False, default=30)
    election_notice_days = require_int(body, "election_notice_days", required=False, default=14)
    election_window_days = require_int(body, "election_window_days", required=False, default=60)
    initial_grace = require_int(body, "initial_premium_grace_days", required=False, default=45)
    recurring_grace = require_int(body, "recurring_premium_grace_days", required=False, default=30)
    shortfall_floor = require_int(body, "insignificant_shortfall_floor_cents",
                                  required=False, default=5000)

    plan = {
        "name": name,
        "applicable_premium_cents": applicable,
        "standard_admin_fee_pct": standard_fee,
        "disability_admin_fee_pct": disability_fee,
        "employer_notice_days": employer_notice_days,
        "election_notice_days": election_notice_days,
        "election_window_days": election_window_days,
        "initial_premium_grace_days": initial_grace,
        "recurring_premium_grace_days": recurring_grace,
        "insignificant_shortfall_floor_cents": shortfall_floor,
        "status": "ACTIVE",
    }
    _common(plan)
    store.plans[plan["id"]] = plan
    return object_response(serialize(plan, PLAN_FIELDS), status=201)


@bp.get("/plans/<pid>")
@require_role({"PlanAdministrator", "PlanSponsor", "BillingAgent", "QualifiedBeneficiary"})
def get_plan(pid):
    plan = get_or_404(store.plans, pid)
    return object_response(serialize(plan, PLAN_FIELDS))


@bp.get("/plans/<pid>/beneficiaries")
@require_role({"PlanAdministrator", "PlanSponsor", "BillingAgent"})
def list_plan_beneficiaries(pid):
    get_or_404(store.plans, pid)
    items = [b for b in store.beneficiaries.values() if b["plan_id"] == pid]
    items = sorted_by_creation(items)
    page, limit, offset, total = paginate(request.args, items)
    return array_response([serialize(b, BENEFICIARY_FIELDS) for b in page],
                          limit, offset, total)


@bp.post("/plans/<pid>/tick")
@require_role({"PlanAdministrator"})
def tick(pid):
    plan = get_or_404(store.plans, pid)
    lifecycle.run_sweep(plan)
    return object_response(serialize(plan, PLAN_FIELDS))


@bp.post("/_clock/set")
@require_role({"PlanAdministrator"})
def set_clock():
    body = require_body()
    if "now_iso8601" not in body or body["now_iso8601"] is None:
        raise ApiError("ERR_INVALID_REQUEST", "Missing required field: now_iso8601")
    try:
        dt = parse_dt(body["now_iso8601"])
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_REQUEST", "now_iso8601 must be an ISO 8601 datetime")
    store.set_clock(dt)
    return object_response({"now_iso8601": now_iso(dt)})
