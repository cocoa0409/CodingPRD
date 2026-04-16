"""Home visit validity calculation."""

from datetime import timedelta

from db import store, now_dt

HOME_VISIT_PASS_THRESHOLD = 70
HOME_VISIT_TTL_DAYS = 180


def compute_adopter_home_visit_status(adopter_id):
    """Return (status, expires_at_dt or None)."""
    # Find latest HomeVisit for adopter
    visits = [v for v in store.home_visits.values() if v["adopter_id"] == adopter_id]
    if not visits:
        return ("PENDING", None)
    # latest in terminal states PASSED/FAILED only
    terminal = [v for v in visits if v["status"] in ("PASSED", "FAILED")]
    if not terminal:
        return ("PENDING", None)
    # Use max completed_at
    latest = max(terminal, key=lambda v: v.get("completed_at") or v["created_at"])
    if latest["status"] == "FAILED":
        return ("FAILED", None)
    # PASSED
    completed_at = latest.get("completed_at")
    if completed_at is None:
        return ("PASSED", None)
    expires_at = completed_at + timedelta(days=HOME_VISIT_TTL_DAYS)
    if now_dt() < expires_at:
        return ("PASSED", expires_at)
    else:
        return ("EXPIRED", expires_at)
