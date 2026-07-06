"""Fabrication Milestones (PRD §3.4)."""
from flask import Blueprint

from db import db, base_common_fields
from errors import ApiError
from middleware import get_auth, require_roles
from response import ok_object, ok_array
from validation import (get_json_body, require_enum, require_int, lookup,
                        parse_pagination, paginate)
from services import touch, recompute_milestone_progress
from serializers import milestone_out

bp = Blueprint("milestones", __name__)

STEPS = {"CASTING", "MODIFICATION", "ASSEMBLY", "QUALITY_CHECK"}


@bp.route("/op/device-orders/<rid>/fabrication-milestones", methods=["POST"])
def create_milestone(rid):
    _, role = get_auth()
    require_roles(role, {"Practitioner"})
    order = lookup(db.device_orders, rid)
    body = get_json_body()

    step = require_enum(body, "step", STEPS)
    weight = require_int(body, "weight")
    if weight < 1:
        raise ApiError("ERR_INVALID_REQUEST", "weight must be >= 1.")

    # Unique step per order (priority 12).
    for m in db.fabrication_milestones.values():
        if m["device_order_id"] == order["id"] and m["step"] == step:
            raise ApiError("ERR_DUPLICATE_MILESTONE", "Milestone step '%s' already exists for this order." % step)

    ms = base_common_fields()
    ms.update({
        "device_order_id": order["id"],
        "step": step,
        "weight": weight,
        "completed": False,
    })
    db.fabrication_milestones[ms["id"]] = ms

    # Recompute the order's milestone_progress_pct (mutation on order).
    recompute_milestone_progress(order)
    return ok_object(milestone_out(ms), 201)


@bp.route("/op/device-orders/<rid>/fabrication-milestones", methods=["GET"])
def list_milestones(rid):
    _, role = get_auth()
    require_roles(role, {"Practitioner", "BillingSpecialist", "ComplianceOfficer"})
    order = lookup(db.device_orders, rid)
    limit, offset = parse_pagination()

    items = [m for m in db.fabrication_milestones.values() if m["device_order_id"] == order["id"]]
    page, total = paginate(items, limit, offset)
    return ok_array([milestone_out(m) for m in page], limit, offset, total, 200)


@bp.route("/op/fabrication-milestones/<rid>/complete", methods=["POST"])
def complete_milestone(rid):
    _, role = get_auth()
    require_roles(role, {"Practitioner"})
    ms = lookup(db.fabrication_milestones, rid)
    order = db.device_orders.get(ms["device_order_id"])

    ms["completed"] = True
    touch(ms)

    # Recompute progress (mutates order if changed).
    recompute_milestone_progress(order)

    # CASCADE: if every milestone for the order is complete, bubble
    # FABRICATION -> READY_FOR_FITTING.
    order_ms = [m for m in db.fabrication_milestones.values() if m["device_order_id"] == order["id"]]
    if order_ms and all(m["completed"] for m in order_ms) and order["status"] == "FABRICATION":
        order["status"] = "READY_FOR_FITTING"
        touch(order)

    return ok_object(milestone_out(ms), 200)
