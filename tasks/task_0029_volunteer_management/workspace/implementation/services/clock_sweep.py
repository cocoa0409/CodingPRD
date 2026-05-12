"""Time-driven Activity transitions, hours archival, and points expiration."""
from datetime import timedelta

import db
from clock import current_clock, iso, parse_iso
from db import round2

from services.completion import complete_application


def advance_clock(target_dt) -> None:
    """Advance the logical clock and run all due transitions and sweeps.

    Per PRD §2.11: "advancing the clock executes every transition that has now
    become due and runs both sweeps."
    """
    from clock import set_clock

    if current_clock() > target_dt:
        # Allow forward-only progression.
        return

    set_clock(target_dt)

    _run_activity_transitions()
    _run_hours_archival()
    _run_points_expiration()


def _run_activity_transitions() -> None:
    now = current_clock()

    # Iterate over activities; cascade transitions in the right order so that
    # an activity whose start_at and end_at are both in the past goes
    # PUBLISHED -> RECRUITING -> RUNNING -> COMPLETED in one sweep.
    for act in list(db.activities.values()):
        if act["status"] == "PUBLISHED":
            if now >= parse_iso(act["recruit_open_at"]):
                act["status"] = "RECRUITING"
                db.touch(act)
        if act["status"] == "RECRUITING":
            if now >= parse_iso(act["start_at"]):
                act["status"] = "RUNNING"
                # Auto-reject all APPLIED applications for this activity
                for app in db.applications.values():
                    if app["activity_id"] == act["id"] and app["status"] == "APPLIED":
                        app["status"] = "REJECTED"
                        db.touch(app)
                db.touch(act)
        if act["status"] == "RUNNING":
            if now >= parse_iso(act["end_at"]):
                # Cascade: CHECKED_IN -> COMPLETED with end_at; APPROVED -> NO_SHOW
                act_end_iso = act["end_at"]
                for app in db.applications.values():
                    if app["activity_id"] != act["id"]:
                        continue
                    if app["status"] == "CHECKED_IN":
                        complete_application(app, act, act_end_iso)
                    elif app["status"] == "APPROVED":
                        if not app.get("check_in_at"):
                            app["status"] = "NO_SHOW"
                            db.touch(app)
                act["status"] = "COMPLETED"
                db.touch(act)


def _run_hours_archival() -> None:
    """Hours archival sweep — see scaffold §1.3 hours_archival.

    For Applications whose check_out_at is strictly more than 365 days in
    the past, decrease Volunteer.total_service_hours by adjusted_hours and
    increase Volunteer.archived_hours by the same amount. Done at most once
    per application (we mark it as _archived).
    """
    now = current_clock()
    for app in db.applications.values():
        if app.get("status") != "COMPLETED":
            continue
        if app.get("_archived"):
            continue
        co = app.get("check_out_at")
        if not co:
            continue
        age = now - parse_iso(co)
        if age > timedelta(days=365):
            vol = db.volunteers.get(app["volunteer_id"])
            if not vol:
                continue
            adj = float(app.get("adjusted_hours", 0))
            vol["total_service_hours"] = round2(float(vol.get("total_service_hours", 0)) - adj)
            vol["archived_hours"] = round2(float(vol.get("archived_hours", 0)) + adj)
            db.touch(vol)
            app["_archived"] = True
            # Application.adjusted_hours is NOT modified per scaffold.


def _run_points_expiration() -> None:
    """Points expiration sweep — see scaffold §1.3 points_expiration_sweep.

    Each Application's unspent points beyond 730 days expire. Redemptions
    have already FIFO-consumed unspent points at fulfillment time (see
    redemption fulfill side-effect). Whatever remains in the per-application
    ledger past the cutoff is removed from Volunteer.points_balance.
    """
    now = current_clock()
    for app in db.applications.values():
        if app.get("status") != "COMPLETED":
            continue
        co = app.get("check_out_at")
        if not co:
            continue
        age = now - parse_iso(co)
        if age <= __import__("datetime").timedelta(days=730):
            continue
        unspent = db.application_points_ledger.get(app["id"], 0)
        if unspent <= 0:
            continue
        vol = db.volunteers.get(app["volunteer_id"])
        if vol:
            new_balance = max(0, int(vol.get("points_balance", 0)) - unspent)
            vol["points_balance"] = new_balance
            db.touch(vol)
        db.application_points_expired[app["id"]] = (
            db.application_points_expired.get(app["id"], 0) + unspent
        )
        db.application_points_ledger[app["id"]] = 0
