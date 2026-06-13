"""Logical-clock side effect: auto-expire LOCKED quotes (PRD §2.11, §3.3).

When the clock reaches or passes a LOCKED quote's expires_at, the quote moves to
EXPIRED before any later read can observe it as still locked. We re-evaluate on
every clock mutation and defensively whenever a quote is read/consumed.
"""
from datetime import datetime, timezone

import db


def parse_iso(s):
    """Parse an ISO 8601 instant (accepting a trailing Z) to aware UTC datetime."""
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def expire_quotes():
    """Move any LOCKED quote whose expires_at <= clock to EXPIRED."""
    now = db.get_clock()
    for quote in db.quotes.values():
        if quote["status"] == "LOCKED" and quote.get("expires_at"):
            if parse_iso(quote["expires_at"]) <= now:
                quote["status"] = "EXPIRED"
                # Note: auto-expiry has no version side effect (state machine
                # side_effects is empty for LOCKED -> EXPIRED).
