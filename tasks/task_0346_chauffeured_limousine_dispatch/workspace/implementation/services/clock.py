"""Deterministic server clock (PRD §3.9)."""
from datetime import datetime, timezone

import db
from helpers import parse_dt


def current_utc_dt():
    """Server 'now' used by all lead-time / wait / flight comparisons (PRD §3.9).

    Defaults to the real wall clock when the deterministic clock has not been set.
    """
    raw = db.clock.get("current_utc")
    if raw is None:
        return datetime.now(timezone.utc)
    return parse_dt(raw, "current_utc")
