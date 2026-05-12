"""HourAdjustment endpoints — file/approve/reject."""
from flask import Blueprint, g, request

import db
from errors import (
    ERR_FORBIDDEN,
    ERR_INVALID_INPUT,
    ERR_INVALID_STATE,
    ERR_NEGATIVE_HOURS,
    ERR_NOT_FOUND,
    err,
)
from middleware import auth_required
from response import success
from services.audit import append_audit
from services.calculations import compute_points_awarded
from services.occ import check_occ
from validators import as_number, as_str, require_field
from views import view_hour_adjustment


bp = Blueprint("hour_adjustments", __name__)


@bp.post("/hour-adjustments")
@auth_required(["Organizer"])
def create_adjustment():
    body = request.get_json(silent=True) or {}
    application_id = as_str(require_field(body, "application_id"), "application_id", 1)
    delta_hours = as_number(require_field(body, "delta_hours"), "delta_hours", -8.0, 8.0)
    if delta_hours == 0:
        raise err(ERR_INVALID_INPUT, "delta_hours must be non-zero")
    delta_hours = db.round2(delta_hours)
    reason = as_str(require_field(body, "reason"), "reason", 10, 500)

    app = db.applications.get(application_id)
    if not app:
        raise err(ERR_NOT_FOUND, "application not found")
    activity = db.activities.get(app["activity_id"])
    if not activity:
        raise err(ERR_NOT_FOUND, "activity not found")
    if activity["organizer_id"] != g.user_id:
        raise err(ERR_FORBIDDEN, "ownership mismatch")

    with db.lock():
        if app["status"] != "COMPLETED":
            raise err(ERR_INVALID_STATE, "application must be COMPLETED")
        new_total = db.round2(float(app.get("adjusted_hours", 0)) + delta_hours)
        if new_total < 0:
            raise err(ERR_NEGATIVE_HOURS, "adjusted_hours would go negative")

        row = {
            "application_id": application_id,
            "requested_by_id": g.user_id,
            "delta_hours": delta_hours,
            "reason": reason,
            "status": "PENDING",
            "approver_id": None,
            "decided_at": None,
        }
        db.init_common(row)
        db.hour_adjustments[row["id"]] = row

        append_audit("Organizer", g.user_id, "HOUR_ADJUST_REQUEST",
                     "HourAdjustment", row["id"],
                     {"application_id": application_id, "delta_hours": delta_hours,
                      "reason": reason})
    return success(view_hour_adjustment(row), status_code=201)


@bp.post("/hour-adjustments/<haid>/approve")
@auth_required(["SkillAdmin"])
def approve_adjustment(haid):
    row = db.hour_adjustments.get(haid)
    if not row:
        raise err(ERR_NOT_FOUND, "hour-adjustment not found")
    body = request.get_json(silent=True) or {}
    check_occ(row, body)

    with db.lock():
        if row["status"] != "PENDING":
            raise err(ERR_INVALID_STATE, "must be PENDING")
        app = db.applications.get(row["application_id"])
        if not app:
            raise err(ERR_NOT_FOUND, "application not found")
        if app["status"] != "COMPLETED":
            raise err(ERR_INVALID_STATE, "application not COMPLETED")
        old_adjusted = float(app.get("adjusted_hours", 0))
        new_adjusted = db.round2(old_adjusted + float(row["delta_hours"]))
        if new_adjusted < 0:
            raise err(ERR_NEGATIVE_HOURS, "adjusted_hours would go negative")

        old_points = int(app.get("points_awarded", 0))
        activity = db.activities.get(app["activity_id"])
        role = db.activity_roles.get(app.get("activity_role_id")) if app.get("activity_role_id") else None
        new_points = compute_points_awarded(new_adjusted, activity, role)
        delta_points = new_points - old_points

        # Apply
        app["adjusted_hours"] = new_adjusted
        app["points_awarded"] = new_points
        db.touch(app)

        vol = db.volunteers.get(app["volunteer_id"])
        if vol:
            vol["total_service_hours"] = db.round2(
                float(vol.get("total_service_hours", 0)) + (new_adjusted - old_adjusted)
            )
            # Clamp at zero per PRD §3.8 last paragraph
            new_balance = int(vol.get("points_balance", 0)) + delta_points
            if new_balance < 0:
                new_balance = 0
            vol["points_balance"] = new_balance
            db.touch(vol)

        # Update per-application unspent ledger by the delta — additional points added
        # reset the 730-day clock on the delta only (handled by check_out_at unchanged).
        unspent = db.application_points_ledger.get(app["id"], 0)
        unspent = max(0, unspent + delta_points)
        db.application_points_ledger[app["id"]] = unspent

        row["status"] = "APPROVED"
        row["approver_id"] = g.user_id
        row["decided_at"] = db.now_str()
        db.touch(row)

        append_audit("SkillAdmin", g.user_id, "HOUR_ADJUST_APPROVE",
                     "HourAdjustment", row["id"],
                     {"old_adjusted_hours": old_adjusted,
                      "new_adjusted_hours": new_adjusted,
                      "old_points_awarded": old_points,
                      "new_points_awarded": new_points})
    return success(view_hour_adjustment(row))


@bp.post("/hour-adjustments/<haid>/reject")
@auth_required(["SkillAdmin"])
def reject_adjustment(haid):
    row = db.hour_adjustments.get(haid)
    if not row:
        raise err(ERR_NOT_FOUND, "hour-adjustment not found")
    body = request.get_json(silent=True) or {}
    check_occ(row, body)
    with db.lock():
        if row["status"] != "PENDING":
            raise err(ERR_INVALID_STATE, "must be PENDING")
        row["status"] = "REJECTED"
        row["approver_id"] = g.user_id
        row["decided_at"] = db.now_str()
        db.touch(row)
        append_audit("SkillAdmin", g.user_id, "HOUR_ADJUST_REJECT",
                     "HourAdjustment", row["id"], {})
    return success(view_hour_adjustment(row))
