"""MonitoringPlan endpoints."""
from flask import Blueprint, request

import clock
from db import db, new_id
from errors import err, ERR_VALIDATION
from middleware import authenticate, require_role
from response import success, list_response
from services import validate, common
from services.derive import serialize_plan

bp = Blueprint("plans", __name__)

TIERS = {"BASIC", "PLUS", "PRO"}


@bp.route("/monitoring-plans", methods=["POST"])
def create_plan():
    caller = authenticate()
    require_role(caller, {"Administrator"})
    body = validate.get_body()

    tier = validate.require_enum(body, "tier", TIERS)
    monthly_fee_cents = validate.require_int(body, "monthly_fee_cents", minimum=0)
    police_dispatch_included = validate.require_bool(body, "police_dispatch_included")
    max_sensors = validate.require_int(body, "max_sensors", minimum=1)
    cellular_backup_included = validate.require_bool(body, "cellular_backup_included")

    # tier unique across plans
    for p in db.monitoring_plans.values():
        if p["tier"] == tier:
            raise err(ERR_VALIDATION, "tier already exists: %s" % tier)

    pid = new_id()
    plan = {
        "id": pid,
        "created_at": clock.now(),
        "_seq": db.next_seq(),
        "tier": tier,
        "monthly_fee_cents": monthly_fee_cents,
        "police_dispatch_included": police_dispatch_included,
        "max_sensors": max_sensors,
        "cellular_backup_included": cellular_backup_included,
    }
    db.monitoring_plans[pid] = plan
    return success(serialize_plan(plan), http_status=201)


@bp.route("/monitoring-plans/<pid>", methods=["GET"])
def get_plan(pid):
    caller = authenticate()
    require_role(caller, {"Administrator", "MonitoringOperator", "Subscriber"})
    plan = common.lookup(db.monitoring_plans, pid)
    return success(serialize_plan(plan))


@bp.route("/monitoring-plans", methods=["GET"])
def list_plans():
    caller = authenticate()
    require_role(caller, {"Administrator", "MonitoringOperator", "Subscriber"})
    limit, offset = common.parse_pagination()
    tier = request.args.get("tier")
    items = list(db.monitoring_plans.values())
    if tier is not None:
        items = [p for p in items if p["tier"] == tier]
    items = common.sort_by_created(items)
    window, total = common.paginate(items, limit, offset)
    return list_response([serialize_plan(p) for p in window], limit, offset, total)
