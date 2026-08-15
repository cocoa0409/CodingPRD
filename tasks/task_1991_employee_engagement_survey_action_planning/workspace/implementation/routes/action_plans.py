"""Action plans & action items (PRD §3.7)."""

from flask import Blueprint, request

from db import db, stamp_new, touch, public, parse_ts
from errors import (
    err, ERR_VALIDATION, ERR_NOT_FOUND, ERR_REFERENCE_NOT_FOUND,
    ERR_INVALID_STATE, ERR_PLAN_OWNERSHIP, ERR_WINDOW_VIOLATION,
    ERR_STALE_VERSION, ERR_CONFIDENTIALITY,
)
from middleware import (
    require_roles, parse_pagination, paginate, get_json_body, require_fields,
    optional_fields_present, as_non_empty_string, as_enum, as_int,
)
from response import success_object, success_list
from services.domain import (
    recompute_plan_progress, maybe_auto_complete_plan,
)

bp = Blueprint("action_plans", __name__)

DIMENSIONS = {"PURPOSE", "GROWTH", "MANAGER_SUPPORT", "BELONGING", "WORKLOAD", "RECOGNITION"}
PLAN_STATUSES = {"DRAFT", "SUBMITTED", "APPROVED", "IN_PROGRESS", "COMPLETED", "REJECTED", "ABANDONED"}


def _get_plan_or_404(plan_id):
    plan = db.action_plans.get(plan_id)
    if plan is None:
        raise err(ERR_NOT_FOUND, "action plan not found", 404)
    return plan


def _get_item_or_404(item_id):
    item = db.action_items.get(item_id)
    if item is None:
        raise err(ERR_NOT_FOUND, "action item not found", 404)
    return item


def _check_plan_ownership(plan, user_id):
    unit = db.org_units.get(plan["unit_id"])
    if unit is None or unit["manager_user_id"] != user_id:
        raise err(ERR_PLAN_OWNERSHIP,
                  "X-User-ID is not the manager_user_id of the plan's unit", 403)


def _manager_can_read_plan(plan, user_id):
    """Read-scope rule for UnitManager on plans: own unit only (§1.5)."""
    unit = db.org_units.get(plan["unit_id"])
    return unit is not None and unit["manager_user_id"] == user_id


# ---------------------------------------------------------------------------
# Plans
# ---------------------------------------------------------------------------

@bp.post("/engagement/action-plans")
def create_plan():
    user_id, role = require_roles("UnitManager")
    body = get_json_body()
    optional_fields_present(body, {"cycle_id", "unit_id", "title", "focus_dimension", "due_at"})
    require_fields(body, ["cycle_id", "unit_id", "title", "focus_dimension", "due_at"])
    cycle_id = as_non_empty_string(body["cycle_id"], "cycle_id")
    unit_id = as_non_empty_string(body["unit_id"], "unit_id")
    title = as_non_empty_string(body["title"], "title")
    focus_dimension = as_enum(body["focus_dimension"], "focus_dimension", DIMENSIONS)
    try:
        due_at = parse_ts(body["due_at"])
    except (ValueError, TypeError):
        raise err(ERR_VALIDATION, "due_at must be an ISO 8601 timestamp", 400)

    # Body FK existence (validated left-to-right per declared field order).
    cycle = db.survey_cycles.get(cycle_id)
    if cycle is None:
        raise err(ERR_REFERENCE_NOT_FOUND, "cycle_id does not exist", 404)
    unit = db.org_units.get(unit_id)
    if unit is None:
        raise err(ERR_REFERENCE_NOT_FOUND, "unit_id does not exist", 404)

    # Plan ownership: caller must manage the plan's unit.
    if unit["manager_user_id"] != user_id:
        raise err(ERR_PLAN_OWNERSHIP,
                  "X-User-ID is not the manager_user_id of the plan's unit", 403)

    # due_at must fall strictly after the cycle's closes_at (§2.5).
    if not due_at > cycle["_closes_at"]:
        raise err(ERR_WINDOW_VIOLATION,
                  "due_at must be strictly after cycle.closes_at", 422)

    plan = stamp_new({
        "cycle_id": cycle_id,
        "unit_id": unit_id,
        "title": title,
        "focus_dimension": focus_dimension,
        "status": "DRAFT",
        "submitted_at": None,
        "due_at": body["due_at"],
        "_due_at": due_at,
        "progress_pct": 0,
        "rejection_reason": None,
    })
    db.action_plans[plan["id"]] = plan
    return success_object(public(plan), 201)


@bp.get("/engagement/action-plans")
def list_plans():
    user_id, role = require_roles("HRAdmin", "PeopleAnalyst", "UnitManager", "Executive")
    limit, offset = parse_pagination({"cycle_id", "unit_id", "status"})
    cycle_id = request.args.get("cycle_id")
    unit_id = request.args.get("unit_id")
    status = request.args.get("status")
    items = list(db.action_plans.values())
    if cycle_id is not None:
        items = [p for p in items if p["cycle_id"] == cycle_id]
    if unit_id is not None:
        items = [p for p in items if p["unit_id"] == unit_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    if role == "UnitManager":
        items = [p for p in items if _manager_can_read_plan(p, user_id)]
    page, total = paginate(items, limit, offset)
    return success_list([public(p) for p in page], limit, offset, total)


@bp.get("/engagement/action-plans/<plan_id>")
def get_plan(plan_id):
    user_id, role = require_roles("HRAdmin", "PeopleAnalyst", "UnitManager", "Executive")
    plan = _get_plan_or_404(plan_id)
    if role == "UnitManager" and not _manager_can_read_plan(plan, user_id):
        raise err(ERR_PLAN_OWNERSHIP,
                  "X-User-ID is not the manager_user_id of the plan's unit", 403)
    return success_object(public(plan))


@bp.post("/engagement/action-plans/<plan_id>/items")
def add_plan_item(plan_id):
    user_id, role = require_roles("UnitManager")
    plan = _get_plan_or_404(plan_id)
    body = get_json_body()
    optional_fields_present(body, {"description", "owner_user_id", "target_at"})
    require_fields(body, ["description", "owner_user_id", "target_at"])
    description = as_non_empty_string(body["description"], "description")
    owner_user_id = as_non_empty_string(body["owner_user_id"], "owner_user_id")
    try:
        target_at = parse_ts(body["target_at"])
    except (ValueError, TypeError):
        raise err(ERR_VALIDATION, "target_at must be an ISO 8601 timestamp", 400)

    _check_plan_ownership(plan, user_id)

    if plan["status"] != "DRAFT":
        raise err(ERR_INVALID_STATE,
                  f"cannot add items to a plan in status {plan['status']}", 409)

    if target_at > plan["_due_at"]:
        raise err(ERR_WINDOW_VIOLATION,
                  "target_at must be no later than plan.due_at", 422)

    item = stamp_new({
        "plan_id": plan["id"],
        "description": description,
        "owner_user_id": owner_user_id,
        "status": "OPEN",
        "target_at": body["target_at"],
        "_target_at": target_at,
    })
    db.action_items[item["id"]] = item
    recompute_plan_progress(plan)
    touch(plan)
    return success_object(public(item), 201)


@bp.get("/engagement/action-plans/<plan_id>/items")
def list_plan_items(plan_id):
    user_id, role = require_roles("HRAdmin", "PeopleAnalyst", "UnitManager", "Executive")
    plan = _get_plan_or_404(plan_id)
    if role == "UnitManager" and not _manager_can_read_plan(plan, user_id):
        raise err(ERR_PLAN_OWNERSHIP,
                  "X-User-ID is not the manager_user_id of the plan's unit", 403)
    limit, offset = parse_pagination(set())
    items = [ai for ai in db.action_items.values() if ai["plan_id"] == plan["id"]]
    page, total = paginate(items, limit, offset)
    return success_list([public(ai) for ai in page], limit, offset, total)


@bp.post("/engagement/action-plans/<plan_id>/submit")
def submit_plan(plan_id):
    user_id, role = require_roles("UnitManager")
    plan = _get_plan_or_404(plan_id)
    body = get_json_body()
    optional_fields_present(body, {"expected_plan_version"})
    require_fields(body, ["expected_plan_version"])
    expected = as_int(body["expected_plan_version"], "expected_plan_version")

    _check_plan_ownership(plan, user_id)

    if plan["status"] != "DRAFT":
        raise err(ERR_INVALID_STATE,
                  f"cannot submit a plan in status {plan['status']}", 409)

    open_items = [ai for ai in db.action_items.values()
                  if ai["plan_id"] == plan["id"] and ai["status"] == "OPEN"]
    if len(open_items) < 1:
        raise err(ERR_INVALID_STATE,
                  "plan requires at least one OPEN action item to submit", 409)

    # The manager must have seen own scores: the unit's DIRECT snapshot for the
    # cycle must not be numeric_suppressed.
    snap = next((s for s in db.report_snapshots.values()
                 if s["cycle_id"] == plan["cycle_id"]
                 and s["unit_id"] == plan["unit_id"]
                 and s["scope"] == "DIRECT"), None)
    if snap is None or snap["numeric_suppressed"]:
        raise err(ERR_CONFIDENTIALITY,
                  "unit snapshot is numerically suppressed; manager has not seen own scores", 403)

    # OCC runs last (§2.8).
    if expected != plan["version"]:
        raise err(ERR_STALE_VERSION, "expected_plan_version mismatch", 412)

    plan["status"] = "SUBMITTED"
    from db import now_iso
    plan["submitted_at"] = now_iso()
    touch(plan)
    return success_object(public(plan))


@bp.post("/engagement/action-plans/<plan_id>/approve")
def approve_plan(plan_id):
    require_roles("PeopleAnalyst")
    plan = _get_plan_or_404(plan_id)
    if plan["status"] != "SUBMITTED":
        raise err(ERR_INVALID_STATE,
                  f"cannot approve a plan in status {plan['status']}", 409)
    cycle = db.survey_cycles.get(plan["cycle_id"])
    if cycle is None or cycle["status"] != "REPORTED":
        raise err(ERR_INVALID_STATE,
                  "plan approval requires the cycle to be REPORTED", 409)
    plan["status"] = "APPROVED"
    touch(plan)
    return success_object(public(plan))


@bp.post("/engagement/action-plans/<plan_id>/reject")
def reject_plan(plan_id):
    require_roles("PeopleAnalyst")
    plan = _get_plan_or_404(plan_id)
    body = get_json_body()
    optional_fields_present(body, {"rejection_reason"})
    require_fields(body, ["rejection_reason"])
    reason = as_non_empty_string(body["rejection_reason"], "rejection_reason")
    if plan["status"] != "SUBMITTED":
        raise err(ERR_INVALID_STATE,
                  f"cannot reject a plan in status {plan['status']}", 409)
    plan["status"] = "REJECTED"
    plan["rejection_reason"] = reason
    touch(plan)
    return success_object(public(plan))


@bp.post("/engagement/action-plans/<plan_id>/revise")
def revise_plan(plan_id):
    user_id, role = require_roles("UnitManager")
    plan = _get_plan_or_404(plan_id)
    _check_plan_ownership(plan, user_id)
    if plan["status"] != "REJECTED":
        raise err(ERR_INVALID_STATE,
                  f"cannot revise a plan in status {plan['status']}", 409)
    plan["status"] = "DRAFT"
    plan["rejection_reason"] = None
    touch(plan)
    return success_object(public(plan))


@bp.post("/engagement/action-plans/<plan_id>/start")
def start_plan(plan_id):
    user_id, role = require_roles("UnitManager")
    plan = _get_plan_or_404(plan_id)
    _check_plan_ownership(plan, user_id)
    if plan["status"] != "APPROVED":
        raise err(ERR_INVALID_STATE,
                  f"cannot start a plan in status {plan['status']}", 409)
    plan["status"] = "IN_PROGRESS"
    touch(plan)
    return success_object(public(plan))


@bp.post("/engagement/action-plans/<plan_id>/abandon")
def abandon_plan(plan_id):
    user_id, role = require_roles("UnitManager")
    plan = _get_plan_or_404(plan_id)
    _check_plan_ownership(plan, user_id)
    if plan["status"] not in ("DRAFT", "IN_PROGRESS"):
        raise err(ERR_INVALID_STATE,
                  f"cannot abandon a plan in status {plan['status']}", 409)
    # Abandonment is permitted only once the logical clock is strictly after due_at.
    if not db.clock > plan["_due_at"]:
        raise err(ERR_WINDOW_VIOLATION,
                  "plan may be abandoned only after its due_at", 422)
    if plan["status"] == "IN_PROGRESS":
        for ai in db.action_items.values():
            if ai["plan_id"] == plan["id"] and ai["status"] == "OPEN":
                ai["status"] = "DROPPED"
                touch(ai)
    plan["status"] = "ABANDONED"
    touch(plan)
    return success_object(public(plan))


# ---------------------------------------------------------------------------
# Action items
# ---------------------------------------------------------------------------

@bp.post("/engagement/action-items/<item_id>/complete")
def complete_item(item_id):
    user_id, role = require_roles("UnitManager")
    item = _get_item_or_404(item_id)
    plan = db.action_plans.get(item["plan_id"])
    if item["status"] != "OPEN":
        raise err(ERR_INVALID_STATE,
                  f"cannot complete an item in status {item['status']}", 409)
    if plan is None or plan["status"] != "IN_PROGRESS":
        raise err(ERR_INVALID_STATE,
                  "parent plan must be IN_PROGRESS", 409)
    unit = db.org_units.get(plan["unit_id"])
    is_manager = unit is not None and unit["manager_user_id"] == user_id
    is_owner = item["owner_user_id"] == user_id
    if not (is_manager or is_owner):
        raise err(ERR_PLAN_OWNERSHIP,
                  "only the item owner or the unit manager may complete an item", 403)

    item["status"] = "DONE"
    touch(item)
    recompute_plan_progress(plan)
    maybe_auto_complete_plan(plan)
    if plan["status"] != "COMPLETED":
        touch(plan)
    return success_object(public(item))


@bp.post("/engagement/action-items/<item_id>/drop")
def drop_item(item_id):
    user_id, role = require_roles("UnitManager")
    item = _get_item_or_404(item_id)
    plan = db.action_items and db.action_plans.get(item["plan_id"])
    if item["status"] != "OPEN":
        raise err(ERR_INVALID_STATE,
                  f"cannot drop an item in status {item['status']}", 409)
    if plan is None or plan["status"] != "IN_PROGRESS":
        raise err(ERR_INVALID_STATE,
                  "parent plan must be IN_PROGRESS", 409)
    # Dropping is the manager's act alone.
    unit = db.org_units.get(plan["unit_id"])
    if unit is None or unit["manager_user_id"] != user_id:
        raise err(ERR_PLAN_OWNERSHIP,
                  "only the unit manager may drop an item", 403)

    item["status"] = "DROPPED"
    touch(item)
    recompute_plan_progress(plan)
    maybe_auto_complete_plan(plan)
    if plan["status"] != "COMPLETED":
        touch(plan)
    return success_object(public(item))
