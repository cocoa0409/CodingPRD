"""Budget plans endpoints."""

from flask import Blueprint, request

from db import store
from errors import (
    ERR_ALREADY_TERMINAL,
    ERR_CLIENT_NOT_ACTIVE,
    ERR_CLIENT_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_PLAN_NOT_FOUND,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_STALE_VERSION,
    err,
)
from middleware import require_roles
from response import success_object, success_list
from serializers import serialize_budget_plan
from services.calcs import compute_allocated_lines, CANONICAL_CATEGORY_ORDER
from services.cascade import clock_now_iso
from util import (
    new_id,
    parse_month,
    parse_pagination,
    require_body,
    get_string,
    get_int,
    reject_unexpected,
)

bp = Blueprint("budget_plans", __name__)

READ_ROLES = ("FiduciaryAdmin", "CaseManager", "FinancialOfficer", "ConservatorOfficer", "ComplianceAuditor")
CATEGORIES = set(CANONICAL_CATEGORY_ORDER)


def _validate_lines(lines):
    if not isinstance(lines, list) or not lines:
        raise err(ERR_INVALID_REQUEST, 400, "lines must be a non-empty array")
    seen = set()
    total = 0
    for line in lines:
        if not isinstance(line, dict):
            raise err(ERR_INVALID_REQUEST, 400, "each line must be an object")
        if set(line.keys()) != {"category", "percent"}:
            raise err(ERR_INVALID_REQUEST, 400, "each line must have category and percent")
        cat = line["category"]
        if cat not in CATEGORIES:
            raise err(ERR_INVALID_REQUEST, 400, f"unknown category {cat}")
        if cat in seen:
            raise err(ERR_INVALID_REQUEST, 400, "duplicate category in lines")
        seen.add(cat)
        pct = line["percent"]
        if isinstance(pct, bool) or not isinstance(pct, int):
            raise err(ERR_INVALID_REQUEST, 400, "percent must be an integer")
        if pct < 0 or pct > 100:
            raise err(ERR_INVALID_REQUEST, 400, "percent must be 0-100")
        total += pct
    if total != 100:
        raise err(ERR_INVALID_REQUEST, 400, "percents must sum to exactly 100")


@bp.route("/budget-plans", methods=["POST"])
def create_plan():
    user_id, _ = require_roles("CaseManager")
    body = require_body()
    reject_unexpected(body, {
        "client_id", "period_month", "source_benefit_cents", "lines", "expected_client_version",
    })
    client_id = get_string(body, "client_id")
    period_month = parse_month(get_string(body, "period_month"), "period_month")
    source = get_int(body, "source_benefit_cents", min_value=1)
    lines = body.get("lines")
    _validate_lines(lines)
    expected_client_version = get_int(body, "expected_client_version", min_value=1)

    c = store.clients.get(client_id)
    if not c:
        raise err(ERR_CLIENT_NOT_FOUND, 404, "client not found")

    # OCC check
    if c["version"] != expected_client_version:
        raise err(ERR_STALE_VERSION, 412, "expected_client_version mismatch")

    # client-activity gate: cannot be TERMINATED
    if c["status"] == "TERMINATED":
        raise err(ERR_CLIENT_NOT_ACTIVE, 409, "Client is TERMINATED")

    now = clock_now_iso()

    # supersede existing non-SUPERSEDED plan for same (client, period_month)
    for p in store.budget_plans.values():
        if (p["client_id"] == client_id
                and p["period_month"] == period_month
                and p["status"] in ("DRAFT", "PROPOSED", "APPROVED")):
            p["status"] = "SUPERSEDED"
            p["updated_at"] = now
            p["version"] += 1
            # superseded_by_plan_id set below after we have new id
            p["_pending_supersede_target"] = True

    allocated = compute_allocated_lines(source, lines)

    pid = new_id()
    plan = {
        "id": pid,
        "client_id": client_id,
        "period_month": period_month,
        "source_benefit_cents": source,
        "lines": [{"category": l["category"], "percent": l["percent"]} for l in lines],
        "allocated_lines": allocated,
        "total_planned_cents": source,
        "status": "DRAFT",
        "superseded_by_plan_id": None,
        "created_by_user_id": user_id,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.budget_plans[pid] = plan

    # fix up superseded_by_plan_id
    for p in store.budget_plans.values():
        if p.get("_pending_supersede_target"):
            p["superseded_by_plan_id"] = pid
            del p["_pending_supersede_target"]

    # increment client version (create-bumps-owner rule)
    c["version"] += 1
    c["updated_at"] = now

    return success_object(serialize_budget_plan(plan), status=201)


@bp.route("/budget-plans", methods=["GET"])
def list_plans():
    require_roles(*READ_ROLES)
    limit, offset = parse_pagination()
    client_id = request.args.get("client_id")
    period_month = request.args.get("period_month")
    status = request.args.get("status")
    superseded_by = request.args.get("superseded_by_plan_id")
    items = list(store.budget_plans.values())
    if client_id is not None:
        items = [p for p in items if p["client_id"] == client_id]
    if period_month is not None:
        items = [p for p in items if p["period_month"] == period_month]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    if superseded_by is not None:
        items = [p for p in items if p.get("superseded_by_plan_id") == superseded_by]
    items.sort(key=lambda p: p["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_budget_plan(p) for p in page], limit, offset, total)


def _get_plan_or_404(pid):
    p = store.budget_plans.get(pid)
    if not p:
        raise err(ERR_PLAN_NOT_FOUND, 404, "plan not found")
    return p


@bp.route("/budget-plans/<pid>", methods=["GET"])
def get_plan(pid):
    require_roles(*READ_ROLES)
    p = _get_plan_or_404(pid)
    return success_object(serialize_budget_plan(p))


@bp.route("/budget-plans/<pid>/propose", methods=["POST"])
def propose_plan(pid):
    require_roles("CaseManager")
    p = _get_plan_or_404(pid)
    if p["status"] == "SUPERSEDED":
        raise err(ERR_ALREADY_TERMINAL, 409, "Plan is SUPERSEDED")
    if p["status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, 409, "Only DRAFT -> PROPOSED")
    now = clock_now_iso()
    p["status"] = "PROPOSED"
    p["updated_at"] = now
    p["version"] += 1
    return success_object(serialize_budget_plan(p))


@bp.route("/budget-plans/<pid>/approve", methods=["POST"])
def approve_plan(pid):
    user_id, _ = require_roles("FinancialOfficer")
    p = _get_plan_or_404(pid)
    if p["status"] == "SUPERSEDED":
        raise err(ERR_ALREADY_TERMINAL, 409, "Plan is SUPERSEDED")
    if p["status"] != "PROPOSED":
        raise err(ERR_INVALID_STATE, 409, "Only PROPOSED -> APPROVED")
    if user_id == p.get("created_by_user_id"):
        raise err(ERR_SEGREGATION_OF_DUTIES, 403, "Approver cannot equal created_by_user_id")
    now = clock_now_iso()
    p["status"] = "APPROVED"
    p["updated_at"] = now
    p["version"] += 1
    return success_object(serialize_budget_plan(p))


@bp.route("/budget-plans/<pid>/revise", methods=["POST"])
def revise_plan(pid):
    require_roles("CaseManager")
    p = _get_plan_or_404(pid)
    if p["status"] == "SUPERSEDED":
        raise err(ERR_ALREADY_TERMINAL, 409, "Plan is SUPERSEDED")
    if p["status"] != "APPROVED":
        raise err(ERR_INVALID_STATE, 409, "Only APPROVED -> DRAFT")
    now = clock_now_iso()
    p["status"] = "DRAFT"
    p["updated_at"] = now
    p["version"] += 1
    # allocated_lines persist untouched
    return success_object(serialize_budget_plan(p))


@bp.route("/budget-plans/<pid>/rebalance", methods=["POST"])
def rebalance_plan(pid):
    require_roles("CaseManager")
    p = _get_plan_or_404(pid)
    if p["status"] == "SUPERSEDED":
        raise err(ERR_ALREADY_TERMINAL, 409, "Plan is SUPERSEDED")
    if p["status"] not in ("DRAFT", "APPROVED"):
        raise err(ERR_INVALID_STATE, 409, "Rebalance only allowed in DRAFT or APPROVED")
    body = require_body()
    reject_unexpected(body, {"from_category", "to_category", "amount_cents"})
    from_cat = get_string(body, "from_category")
    to_cat = get_string(body, "to_category")
    amount = get_int(body, "amount_cents", min_value=1)
    if from_cat == to_cat:
        raise err(ERR_INVALID_REQUEST, 400, "from_category and to_category must differ")
    if from_cat not in CATEGORIES or to_cat not in CATEGORIES:
        raise err(ERR_INVALID_REQUEST, 400, "unknown category")
    from_line = next((l for l in p["allocated_lines"] if l["category"] == from_cat), None)
    to_line = next((l for l in p["allocated_lines"] if l["category"] == to_cat), None)
    if from_line is None or to_line is None:
        raise err(ERR_INVALID_REQUEST, 400, "category not present in allocated_lines")
    if from_line["amount_cents"] < amount:
        raise err(ERR_INVALID_REQUEST, 400, "amount exceeds source line")
    from_line["amount_cents"] -= amount
    to_line["amount_cents"] += amount
    now = clock_now_iso()
    p["updated_at"] = now
    p["version"] += 1
    return success_object(serialize_budget_plan(p))
