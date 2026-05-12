"""Cascade logic for completing an Application (manual or automatic)."""
import db

from services.calculations import compute_points_awarded, compute_service_hours


def complete_application(app: dict, activity: dict, check_out_at: str) -> None:
    """Run the full completion cascade for an Application that is currently CHECKED_IN.

    - Sets status=COMPLETED, check_out_at, early_departure_marker
    - Computes credited_hours, adjusted_hours, points_awarded
    - Increments Volunteer totals
    - Touches the application's version/updated_at and the volunteer's
    """
    from clock import parse_iso

    app["status"] = "COMPLETED"
    app["check_out_at"] = check_out_at

    # early_departure_marker: check_out_at < end_at - 15min
    end_dt = parse_iso(activity["end_at"])
    co_dt = parse_iso(check_out_at)
    if (end_dt - co_dt).total_seconds() > 15 * 60:
        app["early_departure_marker"] = True

    role = db.activity_roles.get(app.get("activity_role_id")) if app.get("activity_role_id") else None
    credited = compute_service_hours(app, activity, role)
    app["credited_hours"] = credited
    app["adjusted_hours"] = credited
    pts = compute_points_awarded(app["adjusted_hours"], activity, role)
    app["points_awarded"] = pts

    # Volunteer totals
    vol = db.volunteers.get(app["volunteer_id"])
    if vol:
        vol["total_completed_activities"] = int(vol.get("total_completed_activities", 0)) + 1
        from db import round2
        vol["total_service_hours"] = round2(float(vol.get("total_service_hours", 0)) + credited)
        vol["points_balance"] = int(vol.get("points_balance", 0)) + pts
        db.touch(vol)

    # Application points ledger (unspent points, used by FIFO redemption + expiry)
    db.application_points_ledger[app["id"]] = pts
    db.application_points_expired.setdefault(app["id"], 0)

    db.touch(app)
