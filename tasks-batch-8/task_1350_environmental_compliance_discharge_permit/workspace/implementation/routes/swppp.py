"""StormwaterPlan endpoints."""

import uuid
from flask import Blueprint, request

import db
from errors import (
    err,
    ERR_INVALID_REQUEST,
    ERR_PERMIT_NOT_FOUND,
    ERR_PLAN_NOT_FOUND,
    ERR_PLAN_NOT_DRAFT,
    ERR_PERMIT_NOT_ACTIVE,
    ERR_STALE_VERSION,
)
from middleware import require_roles
from response import success, list_success
from util import get_body, require_fields
from services.core import (
    base_entity,
    touch,
    append_audit,
    serialize_swppp_plan,
    paginate,
)

bp = Blueprint("swppp", __name__)


@bp.route("/npdes/swppp-plans", methods=["POST"])
def create_plan():
    user_id, role = require_roles(["FacilityInspector"])
    body = get_body()
    require_fields(body, ["permit_id", "plan_title", "version_label", "inspection_frequency_days"])
    permit = db.permits.get(body["permit_id"])
    if permit is None:
        raise err(ERR_PERMIT_NOT_FOUND, 404, "Permit not found")
    freq = body["inspection_frequency_days"]
    if isinstance(freq, bool) or not isinstance(freq, int) or freq < 1 or freq > 365:
        raise err(ERR_INVALID_REQUEST, 400, "inspection_frequency_days must be an integer in 1..365")

    plan = base_entity("StormwaterPlan")
    plan["id"] = str(uuid.uuid4())
    plan.update(
        {
            "permit_id": permit["id"],
            "plan_title": body["plan_title"],
            "version_label": body["version_label"],
            "inspection_frequency_days": freq,
            "status": "DRAFT",
        }
    )
    db.swppp_plans[plan["id"]] = plan
    append_audit("StormwaterPlan", plan["id"], "PLAN_CREATED", user_id, role)
    return success(serialize_swppp_plan(plan), 201)


@bp.route("/npdes/swppp-plans", methods=["GET"])
def list_plans():
    require_roles(["Any"])
    items = list(db.swppp_plans.values())
    permit_id = request.args.get("permit_id")
    if permit_id:
        items = [p for p in items if p["permit_id"] == permit_id]
    status = request.args.get("status")
    if status:
        items = [p for p in items if p["status"] == status]
    page, total, limit, offset = paginate(items, request.args)
    return list_success([serialize_swppp_plan(p) for p in page], total, limit, offset)


@bp.route("/npdes/swppp-plans/<pid>", methods=["GET"])
def get_plan(pid):
    require_roles(["Any"])
    plan = db.swppp_plans.get(pid)
    if plan is None:
        raise err(ERR_PLAN_NOT_FOUND, 404, "StormwaterPlan not found")
    return success(serialize_swppp_plan(plan), 200)


@bp.route("/npdes/swppp-plans/<pid>/activate", methods=["POST"])
def activate_plan(pid):
    user_id, role = require_roles(["FacilityInspector"])
    plan = db.swppp_plans.get(pid)
    if plan is None:
        raise err(ERR_PLAN_NOT_FOUND, 404, "StormwaterPlan not found")
    body = get_body()
    require_fields(body, ["expected_permit_version"])
    expected = body["expected_permit_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err(ERR_INVALID_REQUEST, 400, "expected_permit_version must be an integer")

    permit = db.permits.get(plan["permit_id"])
    if permit is None:
        raise err(ERR_PERMIT_NOT_FOUND, 404, "Permit not found")

    # OCC guard (ladder rung 5, before state-machine guards)
    if expected != permit["version"]:
        raise err(ERR_STALE_VERSION, 412, "expected_permit_version does not match Permit.version")

    if plan["status"] != "DRAFT":
        raise err(ERR_PLAN_NOT_DRAFT, 409, "Plan is not DRAFT")
    if permit["status"] != "ACTIVE":
        raise err(ERR_PERMIT_NOT_ACTIVE, 409, "Permit is not ACTIVE")

    # Supersede the currently ACTIVE plan(s) of this permit
    for other in db.swppp_plans.values():
        if other["permit_id"] == permit["id"] and other["status"] == "ACTIVE" and other["id"] != plan["id"]:
            other["status"] = "SUPERSEDED"
            touch(other)
            append_audit("StormwaterPlan", other["id"], "PLAN_SUPERSEDED", "system", "system")

    plan["status"] = "ACTIVE"
    touch(plan)
    touch(permit)
    append_audit("StormwaterPlan", plan["id"], "PLAN_ACTIVATED", user_id, role)
    return success(serialize_swppp_plan(plan), 200)
