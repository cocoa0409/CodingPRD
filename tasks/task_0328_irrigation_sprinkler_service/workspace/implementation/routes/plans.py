"""MaintenancePlan routes (PRD §3.7)."""
from flask import Blueprint, request

from db import db, LOCK, stamp_new, touch
import domain
import errors
import lookups
from domain import serialize
from errors import fail
from listing import list_response
from middleware import get_auth, require_role
from response import success
from validation import get_body, require_str, require_int, require_enum

bp = Blueprint("plans", __name__)

TIERS = {"BASIC", "PLUS", "PREMIUM"}


@bp.route("/maintenance-plans", methods=["POST"])
def create_plan():
    _, role = get_auth()
    require_role(role, {"Dispatcher"})
    with LOCK:
        body = get_body()
        property_id = require_str(body, "property_id")
        lookups.get_property(property_id)
        tier = require_enum(body, "tier", TIERS)
        visits_per_year = require_int(body, "visits_per_year", minimum=1)
        rec = {
            "property_id": property_id,
            "tier": tier,
            "visits_per_year": visits_per_year,
            "annual_dues_cents": domain.plan_annual_dues(tier, visits_per_year),
            "plan_state": "ACTIVE",
        }
        stamp_new(rec)
        db.maintenance_plans[rec["id"]] = rec
        return success(serialize(rec), status=201)


@bp.route("/maintenance-plans/<pid>", methods=["GET"])
def get_plan(pid):
    _, role = get_auth()
    require_role(role, {"Dispatcher", "Customer"})
    with LOCK:
        rec = lookups.get_plan(pid)
        return success(serialize(rec), status=200)


@bp.route("/maintenance-plans", methods=["GET"])
def list_plans():
    _, role = get_auth()
    require_role(role, {"Dispatcher", "Customer"})
    with LOCK:
        rows = list(db.maintenance_plans.values())
        property_id = request.args.get("property_id")
        if property_id is not None:
            rows = [p for p in rows if p["property_id"] == property_id]
        return list_response(rows)


@bp.route("/maintenance-plans/<pid>/pause", methods=["POST"])
def pause_plan(pid):
    _, role = get_auth()
    require_role(role, {"Dispatcher"})
    with LOCK:
        plan = lookups.get_plan(pid)
        if plan["plan_state"] != "ACTIVE":
            fail(errors.ERR_PLAN_NOT_ACTIVE, "Plan is not ACTIVE")
        plan["plan_state"] = "PAUSED"
        touch(plan)
        return success(serialize(plan), status=200)


@bp.route("/maintenance-plans/<pid>/resume", methods=["POST"])
def resume_plan(pid):
    _, role = get_auth()
    require_role(role, {"Dispatcher"})
    with LOCK:
        plan = lookups.get_plan(pid)
        if plan["plan_state"] != "PAUSED":
            fail(errors.ERR_PLAN_NOT_PAUSED, "Plan is not PAUSED")
        plan["plan_state"] = "ACTIVE"
        touch(plan)
        return success(serialize(plan), status=200)


@bp.route("/maintenance-plans/<pid>/cancel", methods=["POST"])
def cancel_plan(pid):
    _, role = get_auth()
    require_role(role, {"Dispatcher"})
    with LOCK:
        plan = lookups.get_plan(pid)
        if plan["plan_state"] == "CANCELLED":
            fail(errors.ERR_PLAN_TERMINAL, "Plan is already CANCELLED")
        plan["plan_state"] = "CANCELLED"
        touch(plan)
        return success(serialize(plan), status=200)
