"""Maintenance window spacing + suppression cascade (PRD 3.6, 3.8)."""
from db import db
from errors import ApiError
from services.common import touch

MIN_WINDOW_GAP_MINUTES = 30


def check_spacing(service_id, starts_at, ends_at):
    """maintenance_window_spacing (PRD 3.6).

    Closed intervals on the same service vs every existing non-CANCELLED
    window. Overlap -> reject. Otherwise gap < 30 minutes -> reject.
    Raises ERR_WINDOW_OVERLAP.
    """
    buffer_seconds = MIN_WINDOW_GAP_MINUTES * 60
    for w in db.windows.values():
        if w["service_id"] != service_id:
            continue
        if w["status"] == "CANCELLED":
            continue
        w_start = w["starts_at"]
        w_end = w["ends_at"]
        # closed-interval overlap
        if starts_at <= w_end and w_start <= ends_at:
            raise ApiError("ERR_WINDOW_OVERLAP", "Maintenance window overlaps an existing window.")
        gap = max(
            (starts_at - w_end).total_seconds(),
            (w_start - ends_at).total_seconds(),
        )
        if gap < buffer_seconds:
            raise ApiError("ERR_WINDOW_OVERLAP", "Maintenance window is too close to an existing window.")


def active_window_covers(service_id):
    """True if an ACTIVE window on the service covers the current clock
    (closed interval [starts_at, ends_at])."""
    now = db.clock.now()
    for w in db.windows.values():
        if w["service_id"] != service_id:
            continue
        if w["status"] != "ACTIVE":
            continue
        if w["starts_at"] <= now <= w["ends_at"]:
            return True
    return False


def suppress_triggered_incidents(service_id):
    """Activation cascade (PRD 3.8): every TRIGGERED incident on the service
    -> SUPPRESSED, counts_against_budget=false, escalation -> EXHAUSTED.
    Each gets its own updated_at/version bump."""
    for inc in db.incidents.values():
        if inc["service_id"] != service_id:
            continue
        if inc["lifecycle_status"] != "TRIGGERED":
            continue
        inc["lifecycle_status"] = "SUPPRESSED"
        inc["counts_against_budget"] = False
        inc["escalation_status"] = "EXHAUSTED"
        touch(inc)
