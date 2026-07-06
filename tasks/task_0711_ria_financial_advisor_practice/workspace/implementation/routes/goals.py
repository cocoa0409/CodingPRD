"""Goal endpoints & funding (PRD §3.6)."""

from flask import Blueprint

from db import db
from errors import err
from middleware import authenticate, authorize
from response import created, ok
from services.common import stamp_new, touch
from services.lookup import get_or_404, ref_or_422
from services.recompute import recompute_goal
from util import (body, require_str, require_iso_date, opt_nonneg_int,
                  require_int, opt_enum)

bp = Blueprint("goals", __name__)

READ_ROLES = {"Advisor", "ComplianceOfficer", "BillingAdmin"}
PRIORITIES = {"ESSENTIAL", "SECONDARY", "ASPIRATIONAL"}


def serialize(g):
    return {
        "id": g["id"],
        "plan_id": g["plan_id"],
        "name": g["name"],
        "target_amount_cents": g["target_amount_cents"],
        "target_date": g["target_date"],
        "current_amount_cents": g["current_amount_cents"],
        "funded_ratio_bps": g["funded_ratio_bps"],
        "on_track": g["on_track"],
        "priority": g["priority"],
        "created_at": g["created_at"],
        "updated_at": g["updated_at"],
        "version": g["version"],
    }


@bp.route("/goals", methods=["POST"])
def create():
    _, role = authenticate()
    authorize(role, {"Advisor"})
    data = body()
    plan_id = require_str(data, "plan_id")
    name = require_str(data, "name")
    target_amount_cents = require_int(data, "target_amount_cents")
    target_date = require_iso_date(data, "target_date")
    current_amount_cents = opt_nonneg_int(data, "current_amount_cents", 0)
    priority = opt_enum(data, "priority", PRIORITIES, "SECONDARY")
    plan = ref_or_422(db.financial_plans, plan_id, "plan_id")
    # goal-amount guard (priority handled in §3.6) — must be > 0
    if target_amount_cents <= 0:
        raise err("ERR_GOAL_AMOUNT_INVALID", "target_amount_cents must be greater than 0")
    g = {
        "plan_id": plan_id,
        "name": name,
        "target_amount_cents": target_amount_cents,
        "target_date": target_date,
        "current_amount_cents": current_amount_cents,
        "funded_ratio_bps": 0,
        "on_track": False,
        "priority": priority,
    }
    stamp_new(g)
    db.goals[g["id"]] = g
    # compute funded ratio per the active variant
    recompute_goal(g, plan)
    return created(serialize(g))


@bp.route("/goals/<gid>", methods=["GET"])
def read(gid):
    _, role = authenticate()
    authorize(role, READ_ROLES)
    g = get_or_404(db.goals, gid)
    return ok(serialize(g))


@bp.route("/goals/<gid>/fund", methods=["POST"])
def fund(gid):
    _, role = authenticate()
    authorize(role, {"Advisor"})
    g = get_or_404(db.goals, gid)
    data = body()
    amount_cents = require_int(data, "amount_cents")
    if amount_cents <= 0:
        raise err("ERR_GOAL_AMOUNT_INVALID", "amount_cents must be greater than 0")
    g["current_amount_cents"] += amount_cents
    touch(g)
    plan = db.financial_plans.get(g["plan_id"])
    recompute_goal(g, plan)
    return ok(serialize(g))
