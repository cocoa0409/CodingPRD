"""Work-order scope lifecycle (PRD 3.2)."""
from flask import Blueprint, request

import lookup
import projections
from auth import ALL_ROLES, authorize
from db import all_rows, store, touch
from errors import api_error
from response import ok, paginated, parse_pagination
from serializers import serialize
from validators import F, body, no_body

bp = Blueprint("work_order", __name__)

WO_TYPES = ("MAINTENANCE", "MODIFICATION", "INSPECTION")


@bp.route("/outages/<outage_id>/work-orders", methods=["POST"])
@authorize("OutagePlanner", "OutageDirector")
def create_work_order(outage_id):
    outage = lookup.outage(outage_id)
    payload = body([
        F("wo_type", "str", enum=WO_TYPES),
        F("title", "str", min_len=1, max_len=200),
        F("estimated_hours", "num", gt=0),
        F("estimated_cost_usd", "num", ge=0),
        F("estimated_dose_mrem", "num", ge=0),
        F("regulatory_commitment", "bool", required=False, default=False),
        F("safety_function_id", "str", required=False, default=None, nullable=True),
        F("requires_rad_work", "bool", required=False, default=False),
    ])
    if payload["safety_function_id"] is not None:
        lookup.safety_function(payload["safety_function_id"])
    work_order = projections.mint_work_order(
        outage,
        payload["wo_type"],
        payload["title"],
        payload["estimated_hours"],
        payload["estimated_cost_usd"],
        payload["estimated_dose_mrem"],
        payload["regulatory_commitment"],
        payload["safety_function_id"],
        payload["requires_rad_work"],
    )
    return ok(serialize(work_order), 201)


@bp.route("/work-orders/<row_id>", methods=["GET"])
@authorize(*ALL_ROLES)
def get_work_order(row_id):
    return ok(serialize(lookup.work_order(row_id)))


@bp.route("/work-orders", methods=["GET"])
@authorize(*ALL_ROLES)
def list_work_orders():
    limit, offset = parse_pagination(request.args)
    rows = all_rows(store.work_orders)
    for key in ("outage_id", "safety_function_id", "status", "priority", "origin"):
        wanted = request.args.get(key)
        if wanted is not None:
            rows = [r for r in rows if r[key] == wanted]
    return paginated(rows, limit, offset, serialize)


# ---------------------------------------------------------------------------
# SCOPED -> PLANNED
# ---------------------------------------------------------------------------
@bp.route("/work-orders/<row_id>/plan", methods=["POST"])
@authorize("OutagePlanner")
def plan_work_order(row_id):
    work_order = lookup.work_order(row_id)
    no_body()
    if work_order["status"] != "SCOPED":
        raise api_error("ERR_WORK_ORDER_STATE_INVALID",
                        "Planning requires the work order to be in SCOPED.")
    outage = store.outages[work_order["outage_id"]]
    if outage["status"] not in ("PLANNING", "SCOPE_LOCKED", "EXECUTION"):
        raise api_error("ERR_OUTAGE_STATE_INVALID",
                        "The owning outage is not in an admissible status.")
    work_order["status"] = "PLANNED"
    touch(work_order)
    return ok(serialize(work_order))


# ---------------------------------------------------------------------------
# PLANNED -> APPROVED
# ---------------------------------------------------------------------------
@bp.route("/work-orders/<row_id>/approve-scope", methods=["POST"])
@authorize("OutageDirector")
def approve_work_order_scope(row_id):
    work_order = lookup.work_order(row_id)
    no_body()
    if work_order["status"] != "PLANNED":
        raise api_error("ERR_WORK_ORDER_STATE_INVALID",
                        "Scope approval requires the work order to be in PLANNED.")
    outage = store.outages[work_order["outage_id"]]
    if outage["status"] not in ("PLANNING", "SCOPE_LOCKED"):
        raise api_error("ERR_OUTAGE_STATE_INVALID",
                        "The owning outage is not in an admissible status.")
    if (work_order["priority"] == "DISCRETIONARY"
            and outage["schedule_posture"] != "ON_TRACK"):
        raise api_error("ERR_SCOPE_FROZEN",
                        "The discretionary scope window is closed.")
    work_order["status"] = "APPROVED"
    touch(work_order)
    projections.recompute_scope_cost(outage)
    touch(outage)
    return ok(serialize(work_order))


# ---------------------------------------------------------------------------
# APPROVED -> PLANNED, DEFERRED -> PLANNED
# ---------------------------------------------------------------------------
@bp.route("/work-orders/<row_id>/return-to-planning", methods=["POST"])
@authorize("OutageDirector")
def return_work_order_to_planning(row_id):
    work_order = lookup.work_order(row_id)
    payload = body([F("return_reason", "str", min_len=1, max_len=500)])
    if work_order["status"] not in ("APPROVED", "DEFERRED"):
        raise api_error("ERR_WORK_ORDER_STATE_INVALID",
                        "Return to planning requires APPROVED or DEFERRED.")
    outage = store.outages[work_order["outage_id"]]
    if work_order["status"] == "APPROVED":
        if projections.has_touched_activity(work_order):
            raise api_error("ERR_ACTIVITY_STATE_INVALID",
                            "Work already touched in the field cannot be un-approved.")
        work_order["status"] = "PLANNED"
        work_order["return_reason"] = payload["return_reason"]
        touch(work_order)
        projections.recompute_scope_cost(outage)
        touch(outage)
    else:
        if outage["status"] not in ("PLANNING", "SCOPE_LOCKED", "EXECUTION"):
            raise api_error("ERR_OUTAGE_STATE_INVALID",
                            "The owning outage is not in an admissible status.")
        work_order["status"] = "PLANNED"
        work_order["return_reason"] = payload["return_reason"]
        work_order["deferral_reason"] = None
        touch(work_order)
    return ok(serialize(work_order))


# ---------------------------------------------------------------------------
# PLANNED -> DEFERRED, APPROVED -> DEFERRED
# ---------------------------------------------------------------------------
@bp.route("/work-orders/<row_id>/defer", methods=["POST"])
@authorize("OutageDirector")
def defer_work_order(row_id):
    work_order = lookup.work_order(row_id)
    payload = body([F("deferral_reason", "str", min_len=1, max_len=500)])
    if work_order["status"] not in ("PLANNED", "APPROVED"):
        raise api_error("ERR_WORK_ORDER_STATE_INVALID",
                        "Deferral requires the work order to be in PLANNED or APPROVED.")
    outage = store.outages[work_order["outage_id"]]
    was_approved = work_order["status"] == "APPROVED"
    if was_approved and projections.has_touched_activity(work_order):
        raise api_error("ERR_ACTIVITY_STATE_INVALID",
                        "Work already touched in the field cannot be deferred.")

    previous_alara = outage["alara_posture"]
    work_order["status"] = "DEFERRED"
    work_order["deferral_reason"] = payload["deferral_reason"]
    touch(work_order)
    projections.defer_work_order_cascade(work_order, was_approved)

    if was_approved:
        projections.recompute_dose(outage, previous_alara)
        projections.recompute_scope_cost(outage)
    projections.recompute_critical_path(outage)
    projections.recompute_schedule_posture(outage)
    touch(outage)
    return ok(serialize(work_order))
