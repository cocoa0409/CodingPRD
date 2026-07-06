"""FinancialPlan endpoints & parallel state machine (PRD §3.6)."""

from flask import Blueprint, request

from db import db
from errors import err
from middleware import authenticate, authorize
from response import created, ok, list_ok
from services.common import stamp_new, touch
from services.lookup import get_or_404, ref_or_422
from services.recompute import recompute_plan_goals
from util import body, require_str, opt_nonneg_int, require_enum, pagination, paginate

bp = Blueprint("financial_plans", __name__)

READ_ROLES = {"Advisor", "ComplianceOfficer", "BillingAdmin"}
# lifecycle: ACTIVATE, ARCHIVE ; review: MARK_REVIEWED, MARK_STALE
ACTIONS = {"ACTIVATE", "ARCHIVE", "MARK_REVIEWED", "MARK_STALE"}


def serialize(p):
    return {
        "id": p["id"],
        "household_id": p["household_id"],
        "name": p["name"],
        "assumed_annual_return_bps": p["assumed_annual_return_bps"],
        "monthly_contribution_cents": p["monthly_contribution_cents"],
        "review_status": p["review_status"],
        "lifecycle_status": p["lifecycle_status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


@bp.route("/financial-plans", methods=["POST"])
def create():
    _, role = authenticate()
    authorize(role, {"Advisor"})
    data = body()
    household_id = require_str(data, "household_id")
    name = require_str(data, "name")
    assumed_annual_return_bps = opt_nonneg_int(data, "assumed_annual_return_bps", 600)
    monthly_contribution_cents = opt_nonneg_int(data, "monthly_contribution_cents", 0)
    ref_or_422(db.households, household_id, "household_id")
    p = {
        "household_id": household_id,
        "name": name,
        "assumed_annual_return_bps": assumed_annual_return_bps,
        "monthly_contribution_cents": monthly_contribution_cents,
        "review_status": "NEEDS_REVIEW",
        "lifecycle_status": "DRAFT",
    }
    stamp_new(p)
    db.financial_plans[p["id"]] = p
    return created(serialize(p))


@bp.route("/financial-plans/<pid>", methods=["GET"])
def read(pid):
    _, role = authenticate()
    authorize(role, READ_ROLES)
    p = get_or_404(db.financial_plans, pid)
    return ok(serialize(p))


@bp.route("/financial-plans", methods=["GET"])
def list_():
    _, role = authenticate()
    authorize(role, READ_ROLES)
    limit, offset = pagination()
    household_id = request.args.get("household_id")
    items = list(db.financial_plans.values())
    if household_id is not None:
        items = [x for x in items if x["household_id"] == household_id]
    items = sorted(items, key=lambda x: (x["created_at"], x["id"]))
    page = paginate(items, limit, offset)
    return list_ok([serialize(x) for x in page], limit, offset, len(items))


@bp.route("/financial-plans/<pid>/state", methods=["POST"])
def state(pid):
    _, role = authenticate()
    authorize(role, {"Advisor"})
    p = get_or_404(db.financial_plans, pid)
    data = body()
    action = require_enum(data, "action", ACTIONS)

    if action == "ACTIVATE":
        if p["lifecycle_status"] != "DRAFT":
            raise err("ERR_INVALID_STATE", "ACTIVATE requires DRAFT lifecycle")
        has_goal = any(g["plan_id"] == pid for g in db.goals.values())
        if not has_goal:
            raise err("ERR_INVALID_STATE", "At least one goal is required to activate")
        p["lifecycle_status"] = "ACTIVE"
        touch(p)
        recompute_plan_goals(p)

    elif action == "ARCHIVE":
        if p["lifecycle_status"] != "ACTIVE":
            raise err("ERR_INVALID_STATE", "ARCHIVE requires ACTIVE lifecycle")
        p["lifecycle_status"] = "ARCHIVED"
        touch(p)

    elif action == "MARK_REVIEWED":
        if p["review_status"] not in {"NEEDS_REVIEW", "STALE"}:
            raise err("ERR_INVALID_STATE", "MARK_REVIEWED requires NEEDS_REVIEW or STALE")
        p["review_status"] = "REVIEWED"
        touch(p)
        recompute_plan_goals(p)

    elif action == "MARK_STALE":
        if p["review_status"] != "REVIEWED":
            raise err("ERR_INVALID_STATE", "MARK_STALE requires REVIEWED")
        p["review_status"] = "STALE"
        touch(p)

    return ok(serialize(p))


@bp.route("/financial-plans/<pid>/goals", methods=["GET"])
def list_goals(pid):
    from routes.goals import serialize as serialize_goal
    _, role = authenticate()
    authorize(role, READ_ROLES)
    get_or_404(db.financial_plans, pid)
    limit, offset = pagination()
    items = [g for g in db.goals.values() if g["plan_id"] == pid]
    items = sorted(items, key=lambda x: (x["created_at"], x["id"]))
    page = paginate(items, limit, offset)
    return list_ok([serialize_goal(x) for x in page], limit, offset, len(items))
