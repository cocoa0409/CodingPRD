"""Line-speed waiver lifecycle."""

from flask import Blueprint

import db
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_WAIVER_WINDOW_EXPIRED,
    ERR_WAIVER_WINDOW_OVERLAP,
    ERR_INSUFFICIENT_PERMISSIONS,
)
from middleware import (
    require_roles,
    get_json_body,
    check_required,
    check_no_unknown,
    check_enum,
)
from response import success_object
from services.core import _touch, lazy_waiver, clamp_runs_for_line
from services.serializers import serialize_waiver

bp = Blueprint("waivers", __name__)

ALL_ROLES = (
    "PlantManager", "ShiftSupervisor", "ReceivingClerk", "LineOperator",
    "QATechnician", "SanitationLead", "USDAInspector", "OrderPlanner",
)


@bp.route("/poultry/waivers/<waiver_id>", methods=["GET"])
def get_waiver(waiver_id):
    require_roles(*ALL_ROLES)
    waiver = db.waivers.get(waiver_id)
    if not waiver:
        raise ApiError(ERR_NOT_FOUND, "Waiver not found", 404)
    lazy_waiver(waiver)
    return success_object(serialize_waiver(waiver))


@bp.route("/poultry/waivers/<waiver_id>/advance", methods=["POST"])
def advance_waiver(waiver_id):
    user_id, role = require_roles("PlantManager", "USDAInspector")
    waiver = db.waivers.get(waiver_id)
    if not waiver:
        raise ApiError(ERR_NOT_FOUND, "Waiver not found", 404)
    lazy_waiver(waiver)
    body = get_json_body()
    check_no_unknown(body, {"to_status", "reason"})
    check_required(body, ["to_status"])
    check_enum(body["to_status"], ("SUBMITTED", "APPROVED", "DENIED", "REVOKED"), "to_status")
    to_status = body["to_status"]

    # Per-action role split
    if to_status == "SUBMITTED" and role != "PlantManager":
        raise ApiError(ERR_INSUFFICIENT_PERMISSIONS, "Role not permitted for this action", 403)
    if to_status in ("APPROVED", "DENIED", "REVOKED") and role != "USDAInspector":
        raise ApiError(ERR_INSUFFICIENT_PERMISSIONS, "Role not permitted for this action", 403)

    if to_status == "SUBMITTED":
        if waiver["status"] not in ("DRAFT", "DENIED"):
            raise ApiError(
                ERR_INVALID_STATE_TRANSITION,
                "SUBMITTED permitted only from DRAFT or DENIED",
                409,
            )
        waiver["status"] = "SUBMITTED"
        _touch(waiver)
    elif to_status == "APPROVED":
        if waiver["status"] != "SUBMITTED":
            raise ApiError(
                ERR_INVALID_STATE_TRANSITION, "APPROVED permitted only from SUBMITTED", 409
            )
        now = db.clock_now()
        # Window-expiry (priority 7) before overlap (priority 8)
        if now >= waiver["effective_to"]:
            raise ApiError(
                ERR_WAIVER_WINDOW_EXPIRED,
                "Approve attempted when logical clock is at/after effective_to",
                409,
            )
        # Overlap check vs APPROVED/ACTIVE waivers on the same line (half-open)
        for other in db.waivers.values():
            if other["id"] == waiver["id"] or other["line_id"] != waiver["line_id"]:
                continue
            if other["status"] not in ("APPROVED", "ACTIVE"):
                continue
            if other["effective_from"] < waiver["effective_to"] and waiver["effective_from"] < other["effective_to"]:
                raise ApiError(
                    ERR_WAIVER_WINDOW_OVERLAP,
                    "Approve would overlap another APPROVED/ACTIVE waiver on the line",
                    422,
                )
        waiver["status"] = "APPROVED"
        waiver["approved_by"] = user_id
        _touch(waiver)
        # If the window already covers now, activate immediately (lazy evaluation)
        lazy_waiver(waiver)
    elif to_status == "DENIED":
        if waiver["status"] != "SUBMITTED":
            raise ApiError(
                ERR_INVALID_STATE_TRANSITION, "DENIED permitted only from SUBMITTED", 409
            )
        waiver["status"] = "DENIED"
        waiver["denial_count"] += 1
        _touch(waiver)
    elif to_status == "REVOKED":
        if waiver["status"] not in ("APPROVED", "ACTIVE"):
            raise ApiError(
                ERR_INVALID_STATE_TRANSITION,
                "REVOKED permitted only from APPROVED or ACTIVE",
                409,
            )
        was_active = waiver["status"] == "ACTIVE"
        reason = body.get("reason")
        if reason is not None:
            from middleware import check_string
            check_string(reason, "reason")
        waiver["status"] = "REVOKED"
        _touch(waiver)
        if was_active:
            # Recompute effective speed for RUNNING runs of this line; clamp
            clamp_runs_for_line(waiver["line_id"])

    return success_object(serialize_waiver(waiver))
