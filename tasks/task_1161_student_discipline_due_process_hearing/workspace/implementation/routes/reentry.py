"""Re-entry plans (PRD §3.7)."""
from flask import Blueprint

from db import db, stamp, touch, serialize
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_REENTRY_OPEN,
    ERR_PLACEMENT_NOT_ACTIVE,
)
from middleware import endpoint
from response import success
from routes.common import get_or_404, render_list
from util import parse_dt

bp = Blueprint("reentry", __name__)


@bp.post("/placements/<pid>/re-entry-plans")
@endpoint("StudentServicesDirector")
def create_plan(ctx, pid):
    placement = get_or_404(db.placements, pid, "placement")
    conditions = ctx.body.get("conditions")
    if not isinstance(conditions, list) or any(not isinstance(c, str) for c in conditions):
        raise_err(ERR_INVALID_REQUEST, "conditions must be a list of strings")
    conference_date = parse_dt(ctx.body.get("conference_date"))
    if conference_date is None:
        raise_err(ERR_INVALID_REQUEST, "conference_date must be a valid ISO 8601 timestamp")
    if placement["status"] not in ("PLACED", "ACTIVE"):
        raise_err(ERR_INVALID_STATE, "placement must be PLACED or ACTIVE to add a re-entry plan")
    if any(
        r["placement_id"] == pid and r["status"] in ("DRAFT", "ACTIVE")
        for r in db.reentry_plans.values()
    ):
        raise_err(ERR_REENTRY_OPEN, "an open re-entry plan already exists for this placement")

    plan = stamp(
        {
            "placement_id": pid,
            "conditions": conditions,
            "conference_date": conference_date,
            "status": "DRAFT",
        }
    )
    db.reentry_plans[plan["id"]] = plan
    return success(serialize(plan), 201)


@bp.get("/placements/<pid>/re-entry-plans")
@endpoint("DistrictAdmin", "StudentServicesDirector")
def list_plans(ctx, pid):
    placement = get_or_404(db.placements, pid, "placement")
    plans = {k: v for k, v in db.reentry_plans.items() if v["placement_id"] == placement["id"]}
    return render_list(plans)


@bp.post("/re-entry-plans/<rid>/activate")
@endpoint("StudentServicesDirector")
def activate_plan(ctx, rid):
    plan = get_or_404(db.reentry_plans, rid, "re-entry plan")
    if plan["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, "re-entry plan is not DRAFT")
    placement = db.placements[plan["placement_id"]]
    if placement["status"] != "ACTIVE":
        raise_err(ERR_PLACEMENT_NOT_ACTIVE, "re-entry activation requires an ACTIVE placement")
    plan["status"] = "ACTIVE"
    touch(plan)
    return success(serialize(plan))


@bp.post("/re-entry-plans/<rid>/outcome")
@endpoint("StudentServicesDirector")
def plan_outcome(ctx, rid):
    plan = get_or_404(db.reentry_plans, rid, "re-entry plan")
    outcome = ctx.body.get("outcome")
    if outcome not in ("COMPLETED", "VIOLATED"):
        raise_err(ERR_INVALID_REQUEST, "outcome must be COMPLETED or VIOLATED")
    if plan["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "re-entry plan is not ACTIVE")
    plan["status"] = outcome
    touch(plan)
    return success(serialize(plan))
