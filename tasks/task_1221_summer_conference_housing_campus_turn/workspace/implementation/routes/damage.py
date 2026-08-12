"""Damage assessment lifecycle with dispute branch (PRD 3.8)."""
from datetime import timedelta

from flask import Blueprint, request

from authz import ADMIN, FACILITIES, FINANCE, COORDINATOR, require_roles, check_group_ownership
from calc import DAMAGE_DISPUTE_WINDOW_DAYS, damage_assessed_total
from db import store
from errors import ApiError, invalid_state
from respond import success
from routes.rooms import validate_line_items
from serialize import ser_damage_assessment
from store_ops import (
    get_or_404, json_body, opt_field, paginate, req_enum, req_str,
    sorted_by_creation, touch,
)

bp = Blueprint("damage", __name__)

READ_ROLES = [ADMIN, FACILITIES, FINANCE, COORDINATOR]


def _not_assessed(msg):
    return ApiError("ERR_DAMAGE_NOT_ASSESSED", 409, msg)


@bp.route("/damage-assessments", methods=["GET"])
def list_damage_assessments():
    require_roles(READ_ROLES)
    room_id = request.args.get("room_id")
    group_id = request.args.get("group_id")
    status = request.args.get("status")
    items = [d for d in store.damage_assessments.values()
             if (room_id is None or d["room_id"] == room_id)
             and (group_id is None or d["group_id"] == group_id)
             and (status is None or d["status"] == status)]
    items = sorted_by_creation(items)
    page, pagination = paginate(items)
    return success([ser_damage_assessment(d) for d in page], response_type="array", pagination=pagination)


@bp.route("/damage-assessments/<did>", methods=["GET"])
def get_damage_assessment(did):
    require_roles(READ_ROLES)
    return success(ser_damage_assessment(get_or_404(store.damage_assessments, did)))


@bp.route("/damage-assessments/<did>/assess", methods=["POST"])
def assess_damage(did):
    require_roles([FACILITIES, ADMIN])
    d = get_or_404(store.damage_assessments, did)
    if d["status"] != "REPORTED":
        raise _not_assessed("Assessment must be REPORTED to assess")
    d["assessed_total_cents"] = damage_assessed_total(d["line_items"])
    d["assessed_at"] = store.clock
    d["status"] = "ASSESSED"
    touch(d)
    return success(ser_damage_assessment(d))


@bp.route("/damage-assessments/<did>/bill", methods=["POST"])
def bill_damage(did):
    require_roles([FINANCE, ADMIN])
    d = get_or_404(store.damage_assessments, did)
    if d["status"] != "ASSESSED":
        raise _not_assessed("Assessment must be ASSESSED to bill")
    g = store.groups[d["group_id"]]
    if g["status"] not in ("IN_HOUSE", "DEPARTED"):
        raise invalid_state("Group must be IN_HOUSE or DEPARTED to bill the assessment")
    d["status"] = "BILLED"
    touch(d)
    return success(ser_damage_assessment(d))


@bp.route("/damage-assessments/<did>/dispute", methods=["POST"])
def dispute_damage(did):
    uid, role = require_roles([COORDINATOR, ADMIN])
    d = get_or_404(store.damage_assessments, did)
    check_group_ownership(uid, role, d["group_id"])
    data = json_body()
    dispute_reason = req_str(data, "dispute_reason")
    if d["status"] != "ASSESSED":
        raise _not_assessed("Assessment must be ASSESSED to dispute")
    if store.clock.date() > d["assessed_at"].date() + timedelta(days=DAMAGE_DISPUTE_WINDOW_DAYS):
        raise ApiError("ERR_DISPUTE_WINDOW_CLOSED", 422,
                       "The dispute window has closed")
    d["status"] = "DISPUTED"
    d["dispute_reason"] = dispute_reason
    touch(d)
    return success(ser_damage_assessment(d))


@bp.route("/damage-assessments/<did>/resolve", methods=["POST"])
def resolve_damage(did):
    require_roles([FINANCE, ADMIN])
    d = get_or_404(store.damage_assessments, did)
    data = json_body()
    outcome = req_enum(data, "outcome", ("ACCEPT", "WAIVE"))
    adjusted = opt_field(data, "adjusted_line_items")
    if adjusted is not None:
        adjusted = validate_line_items(adjusted)
    if d["status"] != "DISPUTED":
        raise _not_assessed("Assessment must be DISPUTED to resolve")
    if outcome == "ACCEPT":
        if adjusted is not None:
            d["line_items"] = adjusted
            d["assessed_total_cents"] = damage_assessed_total(adjusted)
        d["status"] = "BILLED"
    else:
        d["assessed_total_cents"] = 0
        d["status"] = "WAIVED"
    touch(d)
    return success(ser_damage_assessment(d))
