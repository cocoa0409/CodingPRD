"""Application endpoints — apply, approve/reject, withdraw, check-in/leave/check-out, manual-correction."""
from flask import Blueprint, g, request

import db
from clock import current_clock, parse_iso
from errors import (
    ERR_BACKGROUND_CHECK_REQUIRED,
    ERR_CHECK_IN_PROOF_FAILED,
    ERR_DISTANCE_EXCEEDED,
    ERR_DUPLICATE_APPLICATION,
    ERR_FORBIDDEN,
    ERR_IDENTITY_NOT_VERIFIED,
    ERR_INVALID_INPUT,
    ERR_INVALID_REFERENCE,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_QUOTA_EXCEEDED,
    ERR_RECRUITMENT_CLOSED,
    ERR_SKILL_MISMATCH,
    ERR_TIME_CONFLICT,
    err,
)
from middleware import auth_required
from response import success
from services.audit import append_audit
from services.calculations import compute_points_awarded, compute_service_hours, haversine_km
from services.completion import complete_application
from services.conflict import has_time_conflict
from services.occ import check_occ
from validators import as_iso, as_lat, as_lng, as_number, as_str, opt_field, require_field
from views import view_application


bp = Blueprint("applications", __name__)


@bp.post("/applications")
@auth_required(["Volunteer"])
def apply_to_activity():
    body = request.get_json(silent=True) or {}
    activity_id = as_str(require_field(body, "activity_id"), "activity_id", 1)
    activity_role_id = opt_field(body, "activity_role_id", None)

    activity = db.activities.get(activity_id)
    if not activity:
        raise err(ERR_NOT_FOUND, "activity not found")

    role = None
    if activity_role_id is not None:
        role = db.activity_roles.get(activity_role_id)
        if not role:
            raise err(ERR_NOT_FOUND, "activity_role not found")

    volunteer = db.volunteers.get(g.user_id)
    if not volunteer:
        raise err(ERR_FORBIDDEN, "acting volunteer not found")

    # Validation priority order:
    # 6. cross-aggregate ownership: implicit (acting volunteer is the volunteer_id)
    # 6.b nested-reference well-formedness
    if role and role["activity_id"] != activity_id:
        raise err(ERR_INVALID_REFERENCE, "activity_role belongs to a different activity")

    # 8. identity verification
    if volunteer["identity_verification_status"] != "VERIFIED":
        raise err(ERR_IDENTITY_NOT_VERIFIED, "identity not verified")

    # 9. background-check requirement
    if activity.get("requires_sensitive_clearance") and \
            volunteer["background_check_status"] != "CLEARED":
        raise err(ERR_BACKGROUND_CHECK_REQUIRED, "background check not cleared")

    # 10. skill-tag match
    required = activity.get("required_skill_codes") or []
    if required:
        approved_skill_codes = set()
        skill_by_id = db.skills
        for vs in db.volunteer_skills.values():
            if vs["volunteer_id"] == g.user_id and vs["review_status"] == "APPROVED":
                s = skill_by_id.get(vs["skill_id"])
                if s:
                    approved_skill_codes.add(s["code"])
        for code in required:
            if code not in approved_skill_codes:
                raise err(ERR_SKILL_MISMATCH, f"missing approved skill: {code}")

    # 11. recruitment window: status must be RECRUITING and now in [open, close)
    now = current_clock()
    if activity.get("status") != "RECRUITING":
        raise err(ERR_RECRUITMENT_CLOSED, "activity not in RECRUITING")
    if not (parse_iso(activity["recruit_open_at"]) <= now < parse_iso(activity["recruit_close_at"])):
        raise err(ERR_RECRUITMENT_CLOSED, "outside recruitment window")

    # 12. time conflict
    if has_time_conflict(g.user_id, activity):
        raise err(ERR_TIME_CONFLICT, "overlaps another active application")

    # 13. geographic distance
    distance_km = haversine_km(volunteer["home_lat"], volunteer["home_lng"],
                               activity["location_lat"], activity["location_lng"])
    if distance_km > 50.0:
        raise err(ERR_DISTANCE_EXCEEDED, f"distance {distance_km} km exceeds 50 km")

    # 16. duplicate application
    NON_TERMINAL = {"APPLIED", "APPROVED", "CHECKED_IN", "ON_LEAVE", "COMPLETED"}
    for existing in db.applications.values():
        if existing["activity_id"] == activity_id and existing["volunteer_id"] == g.user_id \
                and existing["status"] in NON_TERMINAL:
            raise err(ERR_DUPLICATE_APPLICATION, "duplicate application")

    row = {
        "activity_id": activity_id,
        "volunteer_id": g.user_id,
        "activity_role_id": activity_role_id,
        "distance_km": distance_km,
        "status": "APPLIED",
        "check_in_at": None,
        "check_in_lat": None,
        "check_in_lng": None,
        "check_out_at": None,
        "late_marker": False,
        "early_departure_marker": False,
        "credited_hours": 0,
        "adjusted_hours": 0,
        "points_awarded": 0,
        "leave_reason": None,
    }
    db.init_common(row)
    db.applications[row["id"]] = row
    return success(view_application(row), status_code=201)


@bp.post("/applications/<app_id>/approve")
@auth_required(["Organizer"])
def approve_application(app_id):
    app = db.applications.get(app_id)
    if not app:
        raise err(ERR_NOT_FOUND, "application not found")
    activity = db.activities.get(app["activity_id"])
    if not activity:
        raise err(ERR_NOT_FOUND, "activity not found")
    if activity["organizer_id"] != g.user_id:
        raise err(ERR_FORBIDDEN, "ownership mismatch")
    body = request.get_json(silent=True) or {}
    check_occ(app, body)

    with db.lock():
        if app["status"] != "APPLIED":
            raise err(ERR_INVALID_STATE, "must be APPLIED")
        if activity.get("status") != "RECRUITING":
            raise err(ERR_INVALID_STATE, "activity must be RECRUITING")
        if has_time_conflict(app["volunteer_id"], activity, exclude_application_id=app_id):
            raise err(ERR_TIME_CONFLICT, "overlaps another active application")
        if int(activity.get("filled_positions", 0)) >= int(activity["position_quota"]):
            raise err(ERR_QUOTA_EXCEEDED, "position quota exceeded")

        app["status"] = "APPROVED"
        activity["filled_positions"] = int(activity.get("filled_positions", 0)) + 1
        db.touch(app)
        db.touch(activity)
    return success(view_application(app))


@bp.post("/applications/<app_id>/reject")
@auth_required(["Organizer"])
def reject_application(app_id):
    app = db.applications.get(app_id)
    if not app:
        raise err(ERR_NOT_FOUND, "application not found")
    activity = db.activities.get(app["activity_id"])
    if not activity:
        raise err(ERR_NOT_FOUND, "activity not found")
    if activity["organizer_id"] != g.user_id:
        raise err(ERR_FORBIDDEN, "ownership mismatch")
    body = request.get_json(silent=True) or {}
    check_occ(app, body)
    with db.lock():
        if app["status"] != "APPLIED":
            raise err(ERR_INVALID_STATE, "must be APPLIED")
        app["status"] = "REJECTED"
        db.touch(app)
    return success(view_application(app))


@bp.post("/applications/<app_id>/withdraw")
@auth_required(["Volunteer"])
def withdraw_application(app_id):
    app = db.applications.get(app_id)
    if not app:
        raise err(ERR_NOT_FOUND, "application not found")
    if app["volunteer_id"] != g.user_id:
        raise err(ERR_FORBIDDEN, "ownership mismatch")
    activity = db.activities.get(app["activity_id"])
    body = request.get_json(silent=True) or {}
    check_occ(app, body)

    # Identity check
    vol = db.volunteers.get(g.user_id)
    if not vol or vol["identity_verification_status"] != "VERIFIED":
        raise err(ERR_IDENTITY_NOT_VERIFIED, "identity not verified")

    # PRD §2.9: when an organizer's approve and a volunteer's withdraw arrive at
    # the same Application simultaneously while it is still APPLIED,
    # first-writer-wins on Application.status admits exactly one transition; the
    # loser receives ERR_INVALID_STATE. Snapshot the pre-lock status so that a
    # withdraw which loses the race to an approve fails — the second writer must
    # not chain APPROVED -> WITHDRAWN as a fall-through.
    pre_status = app["status"]
    with db.lock():
        if pre_status == "APPLIED" and app["status"] != "APPLIED":
            # Lost the race to a concurrent approve/reject.
            raise err(ERR_INVALID_STATE, "lost concurrent race; status no longer APPLIED")
        if app["status"] == "APPLIED":
            app["status"] = "WITHDRAWN"
            db.touch(app)
        elif app["status"] == "APPROVED":
            if not activity or activity.get("status") != "RECRUITING":
                raise err(ERR_INVALID_STATE,
                          "approved withdraw only allowed while parent activity is RECRUITING")
            app["status"] = "WITHDRAWN"
            activity["filled_positions"] = max(0, int(activity.get("filled_positions", 0)) - 1)
            db.touch(app)
            db.touch(activity)
        else:
            raise err(ERR_INVALID_STATE, "cannot withdraw in current state")
    return success(view_application(app))


@bp.post("/applications/<app_id>/check-in")
@auth_required(["Volunteer"])
def check_in(app_id):
    app = db.applications.get(app_id)
    if not app:
        raise err(ERR_NOT_FOUND, "application not found")
    if app["volunteer_id"] != g.user_id:
        raise err(ERR_FORBIDDEN, "ownership mismatch")
    activity = db.activities.get(app["activity_id"])

    body = request.get_json(silent=True) or {}
    check_occ(app, body)

    vol = db.volunteers.get(g.user_id)
    if not vol or vol["identity_verification_status"] != "VERIFIED":
        raise err(ERR_IDENTITY_NOT_VERIFIED, "identity not verified")

    with db.lock():
        if app["status"] != "APPROVED":
            raise err(ERR_INVALID_STATE, "must be APPROVED to check in")
        if not activity or activity.get("status") != "RUNNING":
            raise err(ERR_INVALID_STATE, "activity not RUNNING")

        site_code = opt_field(body, "site_code", None)
        ci_lat = opt_field(body, "check_in_lat", None)
        ci_lng = opt_field(body, "check_in_lng", None)

        proof_ok = False
        if site_code is not None:
            if not isinstance(site_code, str):
                raise err(ERR_INVALID_INPUT, "site_code must be a string")
            if site_code == activity.get("site_code"):
                proof_ok = True
        if not proof_ok and ci_lat is not None and ci_lng is not None:
            ci_lat_v = as_lat(ci_lat, "check_in_lat")
            ci_lng_v = as_lng(ci_lng, "check_in_lng")
            d = haversine_km(ci_lat_v, ci_lng_v,
                             activity["location_lat"], activity["location_lng"])
            if d <= 0.50:
                proof_ok = True
            app["check_in_lat"] = ci_lat_v
            app["check_in_lng"] = ci_lng_v
        if not proof_ok:
            raise err(ERR_CHECK_IN_PROOF_FAILED,
                      "neither site_code matches nor GPS within 0.50 km")

        now = current_clock()
        from clock import iso
        app["check_in_at"] = iso(now)
        from datetime import timedelta
        if now > parse_iso(activity["start_at"]) + timedelta(minutes=15):
            app["late_marker"] = True
        app["status"] = "CHECKED_IN"
        db.touch(app)
    return success(view_application(app))


@bp.post("/applications/<app_id>/leave")
@auth_required(["Volunteer"])
def request_leave(app_id):
    app = db.applications.get(app_id)
    if not app:
        raise err(ERR_NOT_FOUND, "application not found")
    if app["volunteer_id"] != g.user_id:
        raise err(ERR_FORBIDDEN, "ownership mismatch")
    activity = db.activities.get(app["activity_id"])
    body = request.get_json(silent=True) or {}
    check_occ(app, body)

    vol = db.volunteers.get(g.user_id)
    if not vol or vol["identity_verification_status"] != "VERIFIED":
        raise err(ERR_IDENTITY_NOT_VERIFIED, "identity not verified")

    with db.lock():
        if app["status"] != "CHECKED_IN":
            raise err(ERR_INVALID_STATE, "must be CHECKED_IN")
        if not activity or activity.get("status") != "RUNNING":
            raise err(ERR_INVALID_STATE, "activity not RUNNING")
        leave_reason = require_field(body, "leave_reason")
        leave_reason = as_str(leave_reason, "leave_reason", 1, 500)
        app["status"] = "ON_LEAVE"
        app["leave_reason"] = leave_reason
        app["_leave_was_reached"] = True
        db.touch(app)
    return success(view_application(app))


@bp.post("/applications/<app_id>/check-out")
@auth_required(["Volunteer"])
def check_out(app_id):
    app = db.applications.get(app_id)
    if not app:
        raise err(ERR_NOT_FOUND, "application not found")
    if app["volunteer_id"] != g.user_id:
        raise err(ERR_FORBIDDEN, "ownership mismatch")
    activity = db.activities.get(app["activity_id"])
    body = request.get_json(silent=True) or {}
    check_occ(app, body)

    vol = db.volunteers.get(g.user_id)
    if not vol or vol["identity_verification_status"] != "VERIFIED":
        raise err(ERR_IDENTITY_NOT_VERIFIED, "identity not verified")

    with db.lock():
        # PRD §3.5 names CHECKED_IN as the explicit prerequisite for /check-out,
        # but PRD §3.6 step 2's "leave_reason in history" branch is only
        # reachable if a volunteer who has reached ON_LEAVE can still finalise
        # the application via the same endpoint — otherwise the leave penalty
        # branch would be unimplementable. Treat ON_LEAVE as an additional
        # accepted entry state for /check-out so the leave-penalty path is
        # exposable end-to-end.
        if app["status"] not in ("CHECKED_IN", "ON_LEAVE"):
            raise err(ERR_INVALID_STATE, "must be CHECKED_IN")
        if not activity or activity.get("status") != "RUNNING":
            raise err(ERR_INVALID_STATE, "activity not RUNNING")
        from clock import iso
        co_iso = iso(current_clock())
        complete_application(app, activity, co_iso)
    return success(view_application(app))


@bp.post("/applications/<app_id>/manual-correction")
@auth_required(["Organizer"])
def manual_correction(app_id):
    app = db.applications.get(app_id)
    if not app:
        raise err(ERR_NOT_FOUND, "application not found")
    activity = db.activities.get(app["activity_id"])
    if not activity:
        raise err(ERR_NOT_FOUND, "activity not found")
    if activity["organizer_id"] != g.user_id:
        raise err(ERR_FORBIDDEN, "ownership mismatch")
    body = request.get_json(silent=True) or {}
    check_occ(app, body)

    fields_present = {k: body[k] for k in
                      ("check_in_at", "check_out_at", "late_marker", "early_departure_marker")
                      if k in body}
    if not fields_present:
        raise err(ERR_INVALID_INPUT, "no correctable fields provided")

    with db.lock():
        before = {k: app.get(k) for k in fields_present}
        # Validate types
        if "check_in_at" in fields_present and fields_present["check_in_at"] is not None:
            as_iso(fields_present["check_in_at"], "check_in_at")
            app["check_in_at"] = fields_present["check_in_at"]
        elif "check_in_at" in fields_present and fields_present["check_in_at"] is None:
            app["check_in_at"] = None
        if "check_out_at" in fields_present and fields_present["check_out_at"] is not None:
            as_iso(fields_present["check_out_at"], "check_out_at")
            app["check_out_at"] = fields_present["check_out_at"]
        elif "check_out_at" in fields_present and fields_present["check_out_at"] is None:
            app["check_out_at"] = None
        if "late_marker" in fields_present:
            if not isinstance(fields_present["late_marker"], bool):
                raise err(ERR_INVALID_INPUT, "late_marker must be boolean")
            app["late_marker"] = fields_present["late_marker"]
        if "early_departure_marker" in fields_present:
            if not isinstance(fields_present["early_departure_marker"], bool):
                raise err(ERR_INVALID_INPUT, "early_departure_marker must be boolean")
            app["early_departure_marker"] = fields_present["early_departure_marker"]

        after = {k: app.get(k) for k in fields_present}

        # If COMPLETED, recompute service-hour and propagate delta to volunteer total_service_hours
        if app["status"] == "COMPLETED":
            role = db.activity_roles.get(app.get("activity_role_id")) if app.get("activity_role_id") else None
            new_credited = compute_service_hours(app, activity, role)
            old_adjusted = float(app.get("adjusted_hours", 0))
            # Recompute credited_hours; adjusted_hours mirrors credited only when no
            # HourAdjustment delta has been previously applied. We'll set
            # adjusted_hours to new_credited too — manual corrections re-baseline.
            app["credited_hours"] = new_credited
            app["adjusted_hours"] = new_credited
            delta = new_credited - old_adjusted
            vol = db.volunteers.get(app["volunteer_id"])
            if vol and delta != 0:
                vol["total_service_hours"] = db.round2(
                    float(vol.get("total_service_hours", 0)) + delta
                )
                db.touch(vol)

        db.touch(app)
        append_audit("Organizer", g.user_id, "HOUR_ADJUST_REQUEST",
                     "Application", app["id"],
                     {"before": before, "after": after})
    return success(view_application(app))


@bp.get("/applications/<app_id>")
@auth_required(["Volunteer", "Organizer", "SkillAdmin"])
def get_application(app_id):
    app = db.applications.get(app_id)
    if not app:
        raise err(ERR_NOT_FOUND, "application not found")
    return success(view_application(app))
