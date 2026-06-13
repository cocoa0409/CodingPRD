"""Logical-clock / return-window arithmetic (PRD §2.10, §3.6)."""
from datetime import datetime, timezone, timedelta

from db import db


def _parse_iso(s):
    """Parse an ISO 8601 timestamp (with optional trailing Z) to aware UTC."""
    if s is None:
        return None
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def return_window_open(delivered_at_iso, return_window_days):
    """True iff current logical clock <= delivered_at + return_window_days days,
    boundary inclusive. delivered_at_iso must be a non-null delivered timestamp.
    """
    if delivered_at_iso is None:
        return False
    delivered = _parse_iso(delivered_at_iso)
    deadline = delivered + timedelta(days=return_window_days)
    now = db.current_clock
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)
    return now <= deadline
