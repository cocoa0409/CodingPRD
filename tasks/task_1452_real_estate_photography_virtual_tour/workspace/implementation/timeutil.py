"""Time helpers — all time logic reads from the logical clock in db.store."""

import uuid
from datetime import datetime, timezone, timedelta

from db import store


def new_id():
    return str(uuid.uuid4())


def now_dt():
    return store.now()


def iso_now_ms():
    """Logical clock as ISO 8601 UTC with three fractional digits."""
    n = now_dt()
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def dt_to_iso(dt):
    """Format a datetime as ISO 8601 UTC with whole-second precision (no
    fractional digits). PRD §2.5 reserves 'three fractional digits' for
    `api_request_timestamp`, `created_at`, and `updated_at` only; all other
    datetime fields (scheduled_start_utc, scheduled_end_utc, delivery_due_utc,
    window_start_utc, window_end_utc, decided_at_utc, delivered_at_utc,
    published_at_utc, activated_at_utc, checked_at_utc, shot_at_utc,
    revision_window_closes_utc, old_start_utc, new_start_utc) are emitted at
    whole-second precision."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt_utc = dt.astimezone(timezone.utc)
    return dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s):
    """Parse an ISO 8601 datetime string to aware datetime in UTC."""
    if s is None:
        return None
    if isinstance(s, datetime):
        return s.astimezone(timezone.utc)
    if not isinstance(s, str):
        return None
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def is_quarter_hour(dt):
    """Check quarter-hour boundary: minute in {0,15,30,45}, zero seconds/micros."""
    return (
        dt.minute in (0, 15, 30, 45)
        and dt.second == 0
        and dt.microsecond == 0
    )


def day_key(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d")
