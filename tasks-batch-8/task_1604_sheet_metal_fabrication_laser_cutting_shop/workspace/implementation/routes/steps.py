"""Routing step endpoints (cross-order list, complete, skip)."""
from flask import Blueprint

from db import store, touch
from errors import ApiError
from response import ok, paginate
from middleware import get_context, require_roles
from validation import require_path_entity
from services.audit import audit
from services.routing import advance_after_step

bp = Blueprint("steps", __name__)


@bp.get("/fab/routing-steps")
def list_routing_steps():
    uid, role, _ = get_context()
    require_roles(["ShopManager", "ProductionPlanner", "MachineOperator"])
    rows = list(store.routing_steps.values())
    for f in ("order_id", "machine_id", "vendor_id", "station", "status"):
        rows = paginate.filter(rows, f)
    return ok(paginate(rows), rtype="array", pagination=paginate)


@bp.post("/fab/routing-steps/<step_id>/complete")
def complete_step(step_id):
    uid, role, _ = get_context()
    require_roles(["MachineOperator"])
    st = require_path_entity(store.routing_steps, step_id)
    if st["status"] != "IN_PROGRESS":
        raise ApiError("ERR_STEP_NOT_IN_PROGRESS", 409, "Complete requires the step to be IN_PROGRESS")
    st["status"] = "COMPLETED"
    st["completing_operator_id"] = uid
    touch(st)
    order = store.orders[st["order_id"]]
    advance_after_step(order, st)
    audit("RoutingStep", st["id"], "STEP_COMPLETED", role, uid,
          {"before": {"status": "IN_PROGRESS"}, "after": {"status": "COMPLETED"}})
    return ok(st)


@bp.post("/fab/routing-steps/<step_id>/skip")
def skip_step(step_id):
    uid, role, _ = get_context()
    require_roles(["ProductionPlanner"])
    st = require_path_entity(store.routing_steps, step_id)
    if st["status"] != "IN_PROGRESS":
        raise ApiError("ERR_STEP_NOT_IN_PROGRESS", 409, "Skip requires the step to be IN_PROGRESS")
    if st["station"] == "LASER":
        raise ApiError("ERR_STEP_NOT_SKIPPABLE", 409, "Cutting (LASER) is never skippable")
    st["status"] = "SKIPPED"
    touch(st)
    order = store.orders[st["order_id"]]
    advance_after_step(order, st)
    audit("RoutingStep", st["id"], "STEP_SKIPPED", role, uid,
          {"before": {"status": "IN_PROGRESS"}, "after": {"status": "SKIPPED"}})
    return ok(st)
