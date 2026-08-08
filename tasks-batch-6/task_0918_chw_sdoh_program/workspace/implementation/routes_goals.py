"""Care-plan goals and measured progress (PRD §3.6)."""

from flask import Blueprint

import calc
import cascades
import store
import validate as v
from clockutil import clock, shift
from envelope import created, listing, ok
from errors import (
    ApiError, ERR_INVALID_STATE, ERR_PATIENT_NOT_ENROLLED, ERR_PATIENT_NOT_FOUND,
)
from ladder import ALL_ROLES, CHW, Endpoint, SUPERVISOR, run
from serial import dump, dump_all

bp = Blueprint("goals", __name__)

EP_GOAL_CREATE = Endpoint("goal.create", [CHW, SUPERVISOR], gated=True)
EP_GOAL_READ = Endpoint("goal.read", ALL_ROLES, path=[("goal_id", "goal")])
EP_GOAL_LIST = Endpoint("goal.list", ALL_ROLES)
EP_GOAL_PROGRESS = Endpoint("goal.progress", [CHW], path=[("goal_id", "goal")], gated=True)
EP_GOAL_CLOSE = Endpoint("goal.close", [CHW, SUPERVISOR], path=[("goal_id", "goal")], gated=True)
EP_GOAL_REOPEN = Endpoint("goal.reopen", [CHW, SUPERVISOR], path=[("goal_id", "goal")], gated=True)

DOMAINS = calc.SDOH_DOMAINS
DIRECTIONS = ("INCREASE_GOOD", "DECREASE_GOOD")
OUTCOMES = ("MET", "NOT_MET", "DEFERRED")


def _review_due(review_cycle_days):
    return shift(clock.now_raw(), days=review_cycle_days)


@bp.post("/chw/goals")
def create_goal():
    def payload(ctx):
        s = ctx.state
        s["patient_id"] = v.req_str(ctx.body, "patient_id")
        s["domain"] = v.req_enum(ctx.body, "domain", DOMAINS)
        s["direction"] = v.req_enum(ctx.body, "direction", DIRECTIONS)
        s["baseline_value"] = v.req_num(ctx.body, "baseline_value")
        s["target_value"] = v.req_num(ctx.body, "target_value")
        s["review_cycle_days"] = v.opt_int(ctx.body, "review_cycle_days", 30, minimum=1)
        if s["direction"] == "INCREASE_GOOD" and not s["target_value"] > s["baseline_value"]:
            v.bad("target_value must be greater than baseline_value for INCREASE_GOOD")
        if s["direction"] == "DECREASE_GOOD" and not s["target_value"] < s["baseline_value"]:
            v.bad("target_value must be less than baseline_value for DECREASE_GOOD")

    def body_refs(ctx):
        patient = store.get("patient", ctx.state["patient_id"])
        if patient is None:
            raise ApiError(ERR_PATIENT_NOT_FOUND, "patient_id does not resolve")
        ctx.state["patient"] = patient

    def enrollment(ctx):
        if ctx.state["patient"]["enrollment_status"] != "ENROLLED":
            raise ApiError(ERR_PATIENT_NOT_ENROLLED, "Patient is not ENROLLED")

    ctx = run(EP_GOAL_CREATE, steps={5: [payload], 6: [body_refs], 9: [enrollment]})
    s = ctx.state
    row = store.insert("goal", {
        "patient_id": s["patient"]["id"],
        "domain": s["domain"],
        "direction": s["direction"],
        "baseline_value": s["baseline_value"],
        "target_value": s["target_value"],
        "current_value": s["baseline_value"],
        "progress_pct": calc.goal_progress_pct(s["direction"], s["baseline_value"],
                                               s["target_value"], s["baseline_value"]),
        "status": "ACTIVE",
        "review_cycle_days": s["review_cycle_days"],
        "review_due_at": _review_due(s["review_cycle_days"]),
        "reopen_count": 0,
        "closed_at": None,
    })
    return created(dump(row))


@bp.get("/chw/goals/<goal_id>")
def read_goal(goal_id):
    ctx = run(EP_GOAL_READ, {"goal_id": goal_id})
    return ok(dump(ctx.row("goal_id")))


@bp.get("/chw/goals")
def list_goals():
    def pagination(ctx):
        ctx.state["page"] = v.pagination(ctx.args)

    ctx = run(EP_GOAL_LIST, steps={5: [pagination]})
    limit, offset = ctx.state["page"]
    rows = store.all_rows("goal")
    for key in ("patient_id", "status", "domain"):
        wanted = ctx.args.get(key)
        if wanted is not None:
            rows = [r for r in rows if r.get(key) == wanted]
    page, total = v.paginate(rows, limit, offset)
    return listing(dump_all(page), limit, offset, total)


@bp.post("/chw/goals/<goal_id>/progress")
def goal_progress(goal_id):
    def payload(ctx):
        ctx.state["current_value"] = v.req_num(ctx.body, "current_value")

    ctx = run(EP_GOAL_PROGRESS, {"goal_id": goal_id}, steps={5: [payload]})
    goal = ctx.row("goal_id")
    goal["current_value"] = ctx.state["current_value"]
    goal["progress_pct"] = calc.goal_progress_pct(
        goal["direction"], goal["baseline_value"], goal["target_value"], goal["current_value"])
    goal["review_due_at"] = _review_due(goal["review_cycle_days"])
    store.touch(goal)
    return ok(dump(goal))


@bp.post("/chw/goals/<goal_id>/close")
def goal_close(goal_id):
    def payload(ctx):
        ctx.state["outcome"] = v.req_enum(ctx.body, "outcome", OUTCOMES)

    def target_state(ctx):
        goal = ctx.row("goal_id")
        if goal["status"] != "ACTIVE":
            raise ApiError(ERR_INVALID_STATE, "Only an ACTIVE goal may be closed")
        if ctx.state["outcome"] == "MET" and goal.get("progress_pct") != 100.0:
            raise ApiError(ERR_INVALID_STATE, "MET requires progress_pct of exactly 100.0")

    ctx = run(EP_GOAL_CLOSE, {"goal_id": goal_id}, steps={5: [payload], 8: [target_state]})
    goal = ctx.row("goal_id")
    outcome = ctx.state["outcome"]
    goal["status"] = outcome
    goal["closed_at"] = clock.now_raw()
    store.touch(goal)
    if outcome == "NOT_MET":
        cascades.open_escalation(goal["patient_id"], "GOAL_NOT_MET", ctx.user_id)
    return ok(dump(goal))


@bp.post("/chw/goals/<goal_id>/reopen")
def goal_reopen(goal_id):
    def target_state(ctx):
        if ctx.row("goal_id")["status"] not in ("MET", "NOT_MET", "DEFERRED"):
            raise ApiError(ERR_INVALID_STATE, "Only a closed goal may be re-opened")

    def enrollment(ctx):
        patient = store.get("patient", ctx.row("goal_id")["patient_id"])
        if patient is None or patient["enrollment_status"] != "ENROLLED":
            raise ApiError(ERR_PATIENT_NOT_ENROLLED, "Patient is not ENROLLED")

    ctx = run(EP_GOAL_REOPEN, {"goal_id": goal_id},
              steps={8: [target_state], 9: [enrollment]})
    goal = ctx.row("goal_id")
    goal["status"] = "ACTIVE"
    goal["closed_at"] = None
    goal["reopen_count"] = goal.get("reopen_count", 0) + 1
    goal["review_due_at"] = _review_due(goal["review_cycle_days"])
    store.touch(goal)
    return ok(dump(goal))
