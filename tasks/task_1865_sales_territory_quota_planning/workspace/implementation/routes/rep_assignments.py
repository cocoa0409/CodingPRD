"""RepAssignment endpoints."""
from datetime import date

from flask import Blueprint, request

from db import store
from errors import ApiError
from middleware import get_user_context, require_role
from response import success_object, success_list
from util import (get_body, reject_unknown_fields, require_fields, req_string,
                  parse_date, find_or_404, paginate, stamp_new, touch)
from services import calc

bp = Blueprint("rep_assignments", __name__)

ADMIN = ("SalesOpsAdmin",)
ALL = ("SalesOpsAdmin", "SalesOpsAnalyst", "RevOpsManager", "SalesRep")


def _windows_overlap(a_from, a_to, b_from, b_to):
    """Half-open [from, to) overlap; None end = +inf."""
    a_end = a_to if a_to is not None else date.max
    b_end = b_to if b_to is not None else date.max
    return a_from < b_end and b_from < a_end


@bp.route("/sales-planning/rep-assignments", methods=["POST"])
def create_assignment():
    ctx = get_user_context()
    require_role(ctx, ADMIN)
    body = get_body()
    reject_unknown_fields(body, {"plan_year_id", "rep_id", "territory_id",
                                 "ramp_schedule_id", "effective_from", "effective_to"})
    require_fields(body, ["plan_year_id", "rep_id", "territory_id", "effective_from"])
    plan = find_or_404(store.plan_years, body["plan_year_id"], "plan year")
    rep = find_or_404(store.reps, body["rep_id"], "sales rep")
    territory = find_or_404(store.territories, body["territory_id"], "territory")
    ramp_schedule_id = body.get("ramp_schedule_id")
    sched = None
    if ramp_schedule_id is not None:
        if not isinstance(ramp_schedule_id, str):
            raise ApiError("ERR_INVALID_REQUEST", "ramp_schedule_id must be a string", 400)
        sched = find_or_404(store.ramp_schedules, ramp_schedule_id, "ramp schedule")

    eff_from = parse_date(body["effective_from"], "effective_from")
    eff_to = None
    if body.get("effective_to") is not None:
        eff_to = parse_date(body["effective_to"], "effective_to")
        if eff_to <= eff_from:
            raise ApiError("ERR_INVALID_REQUEST",
                           "effective_to must be later than effective_from", 400)

    # Tier 4: plan gate (DRAFT|OPEN)
    if plan["status"] == "LOCKED":
        raise ApiError("ERR_PLAN_LOCKED", "Plan is LOCKED", 409)
    if plan["status"] not in ("DRAFT", "OPEN"):
        raise ApiError("ERR_PLAN_NOT_OPEN",
                       "Rep assignment creation requires plan status DRAFT or OPEN", 409)

    # Tier 5: cross-plan — territory must live in the named plan
    if territory["plan_year_id"] != plan["id"]:
        raise ApiError("ERR_CROSS_PLAN_REFERENCE",
                       "territory_id belongs to a different plan year", 409)

    # Tier 6: window within plan year
    p_start = date.fromisoformat(plan["start_date"])
    p_end = date.fromisoformat(plan["end_date"])
    if not (p_start <= eff_from <= p_end):
        raise ApiError("ERR_DATE_OUT_OF_PLAN_YEAR",
                       "effective_from falls outside the plan year", 422)
    if eff_to is not None and not (eff_from < eff_to <= p_end):
        raise ApiError("ERR_DATE_OUT_OF_PLAN_YEAR",
                       "effective_to must satisfy effective_from < effective_to <= plan.end_date", 422)

    # Tier 7: overlap + headcount
    for a in store.rep_assignments.values():
        if a["rep_id"] == rep["id"] and a["status"] == "ACTIVE":
            a_from = date.fromisoformat(a["effective_from"])
            a_to = date.fromisoformat(a["effective_to"]) if a["effective_to"] else None
            if _windows_overlap(a_from, a_to, eff_from, eff_to):
                raise ApiError("ERR_ASSIGNMENT_OVERLAP",
                               "Rep already has an ACTIVE assignment overlapping this window", 409)
    active_on_terr = [a for a in store.rep_assignments.values()
                      if a["territory_id"] == territory["id"] and a["status"] == "ACTIVE"]
    if len(active_on_terr) >= territory["headcount_capacity"]:
        raise ApiError("ERR_HEADCOUNT_EXCEEDED",
                       "Territory already has headcount_capacity ACTIVE assignments", 409)

    # New-hire ramp requirement
    hire = date.fromisoformat(rep["hire_date"])
    if p_start <= hire <= p_end and sched is None:
        raise ApiError("ERR_RAMP_SCHEDULE_REQUIRED",
                       "Rep hire_date falls inside the plan year; ramp_schedule_id is required", 422)

    asg = stamp_new({
        "plan_year_id": plan["id"],
        "rep_id": rep["id"],
        "territory_id": territory["id"],
        "ramp_schedule_id": ramp_schedule_id,
        "effective_from": eff_from.isoformat(),
        "effective_to": eff_to.isoformat() if eff_to else None,
        "status": "ACTIVE",
        "base_quota_cents": None,
        "ramped_quota_cents": None,
        "final_quota_cents": None,
        "attainment_cents": 0,
        "attainment_pct": None,
    })
    store.rep_assignments[asg["id"]] = asg
    # Recompute base shares for all ACTIVE assignments on the territory
    calc._recompute_assignment_shares_for_territory(territory)
    # Attainment rollup for this rep (may already have events? fresh rep: 0)
    calc.recompute_attainment_rollup(rep["id"], plan["id"])
    return success_object(calc.ser_rep_assignment(asg), status=201)


@bp.route("/sales-planning/rep-assignments", methods=["GET"])
def list_assignments():
    ctx = get_user_context()
    require_role(ctx, ALL)
    items = list(store.rep_assignments.values())
    if (v := request.args.get("plan_year_id")) is not None:
        items = [a for a in items if a["plan_year_id"] == v]
    if (v := request.args.get("rep_id")) is not None:
        items = [a for a in items if a["rep_id"] == v]
    if (v := request.args.get("territory_id")) is not None:
        items = [a for a in items if a["territory_id"] == v]
    if (v := request.args.get("ramp_schedule_id")) is not None:
        items = [a for a in items if a["ramp_schedule_id"] == v]
    if (v := request.args.get("status")) is not None:
        items = [a for a in items if a["status"] == v]
    items.sort(key=lambda a: (a["created_at"], a["id"]))
    page, limit, offset, total = paginate(items, request.args)
    return success_list([calc.ser_rep_assignment(a) for a in page], limit, offset, total)


@bp.route("/sales-planning/rep-assignments/<aid>", methods=["GET"])
def get_assignment(aid):
    ctx = get_user_context()
    require_role(ctx, ALL)
    a = find_or_404(store.rep_assignments, aid, "rep assignment")
    return success_object(calc.ser_rep_assignment(a))


@bp.route("/sales-planning/rep-assignments/<aid>/end", methods=["POST"])
def end_assignment(aid):
    ctx = get_user_context()
    require_role(ctx, ADMIN)
    a = find_or_404(store.rep_assignments, aid, "rep assignment")
    body = get_body()
    reject_unknown_fields(body, {"effective_to"})
    require_fields(body, ["effective_to"])
    plan = find_or_404(store.plan_years, a["plan_year_id"], "plan year")
    if plan["status"] == "LOCKED":
        raise ApiError("ERR_PLAN_LOCKED", "Plan is LOCKED", 409)
    if plan["status"] not in ("DRAFT", "OPEN"):
        raise ApiError("ERR_PLAN_NOT_OPEN",
                       "Ending an assignment requires plan status DRAFT or OPEN", 409)
    if a["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       f"Cannot end assignment in status {a['status']}", 409)
    eff_to = parse_date(body["effective_to"], "effective_to")
    eff_from = date.fromisoformat(a["effective_from"])
    p_end = date.fromisoformat(plan["end_date"])
    if not (eff_from < eff_to <= p_end):
        raise ApiError("ERR_INVALID_REQUEST",
                       "effective_to must satisfy effective_from < effective_to <= plan.end_date", 400)

    territory = find_or_404(store.territories, a["territory_id"], "territory")
    a["status"] = "ENDED"
    a["effective_to"] = eff_to.isoformat()
    touch(a)  # frozen values stay as-is
    # Cascade hop 2: recompute remaining ACTIVE assignments' shares
    calc._recompute_assignment_shares_for_territory(territory)
    return success_object(calc.ser_rep_assignment(a))
