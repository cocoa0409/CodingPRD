"""Logical clock helpers (PRD §2.6).

Deadline / window comparisons use a server-maintained logical clock set by a
Registrar via POST /_clock/set. When unset, fall back to real wall-clock UTC.
"""
from __future__ import annotations

from datetime import datetime, timezone

import db


def _parse(iso: str) -> datetime:
    """Parse an ISO 8601 instant into an aware UTC datetime.

    Accepts a trailing 'Z' or an explicit offset; naive values are treated as
    UTC. Returns a timezone-aware datetime in UTC.
    """
    s = iso.strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def now() -> datetime:
    """The logical 'now' as an aware UTC datetime."""
    val = db.logical_clock.get("now")
    if val is None:
        return datetime.now(timezone.utc)
    return _parse(val)


def to_dt(iso: str) -> datetime:
    """Parse a stored ISO datetime field into an aware UTC datetime."""
    return _parse(iso)
