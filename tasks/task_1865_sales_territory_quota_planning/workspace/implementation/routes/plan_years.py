"""PlanYear endpoints + clock capability."""
from datetime import datetime, timezone, date

from flask import Blueprint, request

from db import store, now_iso
from errors import ApiError
from middleware import get_user_context, require_role
from response import success_object, success_list
from util import (get_body, reject_unknown_fields, require_fields, req_string,
                  opt_string, req_int, opt_int, req_enum, parse_date,
                  find_or_404, paginate, stamp_new, touch, last_day_of_month)
from services import calc

bp = Blueprint("plan_years", __name__)

ADMIN = ("SalesOpsAdmin",)
ALL = ("SalesOpsAdmin", "SalesOpsAnalyst", "RevOpsManager", "SalesRep")


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    ctx = get_user_context()
    require_role(ctx, ADMIN)
    body = get_body()
    reject_unknown_fields(body, {"to_iso8601"})
    iso = req_string(body, "to_iso8601")
    try:
        s = iso.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
    except (ValueError, AttributeError):
        raise ApiError("ERR_INVALID_REQUEST", "to_iso8601 is not a valid ISO 8601 timestamp", 400)
    store.logical_clock = dt
    return success_object({"current_utc": now_iso()})


# ---------------------------------------------------------------------------
# PlanYear CRUD + lifecycle
# ---------------------------------------------------------------------------

@bp.route("/sales-planning/plan-years", methods=["POST"])
def create_plan_year():
    ctx = get_user_context()
    require_role(ctx, ADMIN)
    body = get_body()
    reject_unknown_fields(body, {
        "label", "start_date", "end_date", "company_target_cents",
        "productivity_per_rep_cents", "lock_date", "reconciliation_policy",
        "credit_transition_policy",
    })
    require_fields(body, ["label", "start_date", "end_date", "company_target_cents",
                          "productivity_per_rep_cents", "lock_date"])
    label = req_string(body, "label")
    start = parse_date(body["start_date"], "start_date")
    end = parse_date(body["end_date"], "end_date")
    lock = parse_date(body["lock_date"], "lock_date")
    target = req_int(body, "company_target_cents")
    productivity = req_int(body, "productivity_per_rep_cents")
    recon = req_enum(body, "reconciliation_policy", ("TOP_DOWN_WINS", "BLENDED")) \
        if "reconciliation_policy" in body and body["reconciliation_policy"] is not None else "TOP_DOWN_WINS"
    credit_pol = req_enum(body, "credit_transition_policy", ("PRORATE_BY_DAY", "MONTH_SNAPSHOT")) \
        if "credit_transition_policy" in body and body["credit_transition_policy"] is not None else "PRORATE_BY_DAY"

    # Tier 6: shape first (ERR_INVALID_PLAN_DATES 422), then overlap (409).
    if start.day != 1:
        raise ApiError("ERR_INVALID_PLAN_DATES", "start_date must be the first day of a month", 422)
    end_month = (start.month - 1 + 11) % 12 + 1
    end_year = start.year + (start.month - 1 + 11) // 12
    expected_end = date(end_year, end_month, last_day_of_month(end_year, end_month))
    if end != expected_end:
        raise ApiError("ERR_INVALID_PLAN_DATES",
                       "end_date must be the last day of the month 11 months after start_date's month", 422)
    if lock < start:
        raise ApiError("ERR_INVALID_PLAN_DATES", "lock_date must not precede start_date", 422)

    for other in store.plan_years.values():
        o_start = date.fromisoformat(other["start_date"])
        o_end = date.fromisoformat(other["end_date"])
        if start <= o_end and o_start <= end:
            raise ApiError("ERR_PLAN_DATE_OVERLAP",
                           "Plan year date range overlaps an existing plan year", 409)

    # Tier 8: strictly positive amounts
    if target <= 0:
        raise ApiError("ERR_AMOUNT_NOT_POSITIVE", "company_target_cents must be > 0", 422)
    if productivity <= 0:
        raise ApiError("ERR_AMOUNT_NOT_POSITIVE", "productivity_per_rep_cents must be > 0", 422)

    plan = stamp_new({
        "label": label,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "company_target_cents": target,
        "productivity_per_rep_cents": productivity,
        "reconciliation_policy": recon,
        "credit_transition_policy": credit_pol,
        "lock_date": lock.isoformat(),
        "status": "DRAFT",
        "communicated_at": None,
        "locked_at": None,
    })
    store.plan_years[plan["id"]] = plan
    return success_object(calc.ser_plan_year(plan), status=201)


@bp.route("/sales-planning/plan-years", methods=["GET"])
def list_plan_years():
    ctx = get_user_context()
    require_role(ctx, ALL)
    items = list(store.plan_years.values())
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items.sort(key=lambda p: (p["created_at"], p["id"]))
    page, limit, offset, total = paginate(items, request.args)
    return success_list([calc.ser_plan_year(p) for p in page], limit, offset, total)


@bp.route("/sales-planning/plan-years/<pid>", methods=["GET"])
def get_plan_year(pid):
    ctx = get_user_context()
    require_role(ctx, ALL)
    plan = find_or_404(store.plan_years, pid, "plan year")
    return success_object(calc.ser_plan_year(plan))


def _get_plan_or_404(pid):
    return find_or_404(store.plan_years, pid, "plan year")


@bp.route("/sales-planning/plan-years/<pid>/open", methods=["POST"])
def open_plan(pid):
    ctx = get_user_context()
    require_role(ctx, ADMIN)
    plan = _get_plan_or_404(pid)
    if plan["status"] == "LOCKED":
        raise ApiError("ERR_PLAN_LOCKED", "Plan is LOCKED", 409)
    if plan["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       f"Cannot open plan in status {plan['status']}", 409)
    has_active = any(t["plan_year_id"] == pid and t["status"] == "ACTIVE"
                     for t in store.territories.values())
    if not has_active:
        raise ApiError("ERR_NO_ACTIVE_TERRITORY",
                       "Plan open requires at least one ACTIVE territory", 409)
    plan["status"] = "OPEN"
    touch(plan)
    return success_object(calc.ser_plan_year(plan))


@bp.route("/sales-planning/plan-years/<pid>/close-submissions", methods=["POST"])
def close_submissions(pid):
    ctx = get_user_context()
    require_role(ctx, ADMIN)
    plan = _get_plan_or_404(pid)
    if plan["status"] == "LOCKED":
        raise ApiError("ERR_PLAN_LOCKED", "Plan is LOCKED", 409)
    if plan["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       f"Cannot close submissions in status {plan['status']}", 409)
    for s in store.submissions.values():
        if s["plan_year_id"] == pid and s["status"] == "SUBMITTED":
            s["status"] = "LOCKED_IN"
            touch(s)
    plan["status"] = "SUBMISSIONS_CLOSED"
    touch(plan)
    return success_object(calc.ser_plan_year(plan))


@bp.route("/sales-planning/plan-years/<pid>/communicate", methods=["POST"])
def communicate_plan(pid):
    ctx = get_user_context()
    require_role(ctx, ADMIN)
    plan = _get_plan_or_404(pid)
    if plan["status"] == "LOCKED":
        raise ApiError("ERR_PLAN_LOCKED", "Plan is LOCKED", 409)
    if plan["status"] != "RECONCILED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       f"Cannot communicate plan in status {plan['status']}", 409)
    plan["status"] = "COMMUNICATED"
    plan["communicated_at"] = now_iso()
    touch(plan)
    return success_object(calc.ser_plan_year(plan))


@bp.route("/sales-planning/plan-years/<pid>/lock", methods=["POST"])
def lock_plan(pid):
    ctx = get_user_context()
    require_role(ctx, ADMIN)
    plan = _get_plan_or_404(pid)
    if plan["status"] == "LOCKED":
        raise ApiError("ERR_PLAN_LOCKED", "Plan is LOCKED", 409)
    if plan["status"] != "COMMUNICATED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       f"Cannot lock plan in status {plan['status']}", 409)
    today = datetime.now(timezone.utc)  # placeholder; replaced below
    from db import logical_today
    today = logical_today()
    lock_date = date.fromisoformat(plan["lock_date"])
    if today < lock_date:
        raise ApiError("ERR_LOCK_DATE_NOT_REACHED",
                       "Current logical date is before the plan lock_date", 409)
    open_disputes = [d for d in store.disputes.values()
                     if d["plan_year_id"] == pid and d["status"] in ("FILED", "UNDER_REVIEW", "ESCALATED")]
    if open_disputes:
        raise ApiError("ERR_PLAN_HAS_UNRESOLVED_DISPUTES",
                       "Plan has unresolved disputes", 409)
    plan["status"] = "LOCKED"
    plan["locked_at"] = now_iso()
    touch(plan)
    return success_object(calc.ser_plan_year(plan))


@bp.route("/sales-planning/plan-years/<pid>/evaluate-assignments", methods=["POST"])
def evaluate_assignments(pid):
    ctx = get_user_context()
    require_role(ctx, ADMIN)
    plan = _get_plan_or_404(pid)
    if plan["status"] == "LOCKED":
        raise ApiError("ERR_PLAN_LOCKED", "Plan is LOCKED", 409)
    evaluated = 0
    reassigned = 0
    still_unassigned = 0
    accounts = [a for a in store.accounts.values() if a["plan_year_id"] == pid]
    accounts.sort(key=lambda a: (a["created_at"], a["id"]))
    for a in accounts:
        evaluated += 1
        changed = calc.resolve_assignment(a)
        if changed:
            reassigned += 1
            touch(a)
        if a["assigned_territory_id"] is None:
            still_unassigned += 1
    touch(plan)
    return success_object({
        "evaluated_count": evaluated,
        "reassigned_count": reassigned,
        "still_unassigned_count": still_unassigned,
    })


@bp.route("/sales-planning/plan-years/<pid>/coverage-report", methods=["GET"])
def coverage(pid):
    ctx = get_user_context()
    require_role(ctx, ("SalesOpsAdmin", "RevOpsManager"))
    plan = _get_plan_or_404(pid)
    return success_object(calc.coverage_report(plan))
