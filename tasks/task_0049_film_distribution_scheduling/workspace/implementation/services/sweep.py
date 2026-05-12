"""System sweep — progress showtime sale_status/lifecycle_status based on clock."""

from datetime import timedelta

from db import db
from clock import now_dt, now_iso
from datetime_utils import parse_iso8601, business_date_plus_minutes


def _apply_sale_status_transition(s):
    """Try transitioning PRESALE -> ON_SALE if eligible. Returns True if changed."""
    if s["sale_status"] != "PRESALE":
        return False
    if s["lifecycle_status"] != "SCHEDULED":
        return False
    presale_opens = parse_iso8601(s["presale_opens_at"], "presale_opens_at")
    if now_dt() < presale_opens:
        return False
    film = db.films.get(s["film_id"])
    if not film or film.get("status") != "RELEASED":
        return False
    s["sale_status"] = "ON_SALE"
    s["updated_at"] = now_iso()
    s["version"] = s.get("version", 1) + 1
    return True


def _apply_lifecycle_transition(s):
    """Try SCHEDULED -> IN_PROGRESS -> COMPLETED. Returns True if any change."""
    changed = False
    business_dt = parse_iso8601(s["business_date"], "business_date")
    start_at = business_date_plus_minutes(business_dt, s["start_minute"])
    end_at = business_date_plus_minutes(business_dt, s["end_minute"])
    now = now_dt()
    if s["lifecycle_status"] == "SCHEDULED" and now >= start_at:
        # require Film.status RELEASED
        film = db.films.get(s["film_id"])
        if film and film.get("status") == "RELEASED":
            s["lifecycle_status"] = "IN_PROGRESS"
            s["sale_status"] = "CLOSED"
            s["updated_at"] = now_iso()
            s["version"] = s.get("version", 1) + 1
            changed = True
    if s["lifecycle_status"] == "IN_PROGRESS" and now >= end_at:
        s["lifecycle_status"] = "COMPLETED"
        s["sale_status"] = "CLOSED"
        s["updated_at"] = now_iso()
        s["version"] = s.get("version", 1) + 1
        changed = True
    return changed


def run_sweep():
    """Apply system-actor transitions to all showtimes."""
    with db.lock:
        for s in list(db.showtimes.values()):
            # First sale status (PRESALE -> ON_SALE)
            _apply_sale_status_transition(s)
            # Then lifecycle (which may also flip sale_status to CLOSED)
            _apply_lifecycle_transition(s)


def lazy_sale_open(showtime):
    """Called at ticket purchase attempt — lazy PRESALE→ON_SALE if eligible."""
    with db.lock:
        _apply_sale_status_transition(showtime)
