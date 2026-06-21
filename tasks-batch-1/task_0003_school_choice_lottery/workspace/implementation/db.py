"""In-memory data store and time helpers.

Store starts empty on every boot. Tests construct every entity via the
public API; we never seed any records here.
"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone


_lock = threading.RLock()


def new_id() -> str:
    return str(uuid.uuid4())


def utc_now_iso() -> str:
    """ISO 8601 UTC with 3 fractional digits, 'Z' suffix."""
    now = datetime.now(timezone.utc)
    ms = f"{now.microsecond // 1000:03d}"
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + ms + "Z"


def parse_iso8601(s: str) -> datetime:
    """Accept ISO 8601 with or without 'Z' / fractional seconds; return aware UTC datetime."""
    if not isinstance(s, str) or not s:
        raise ValueError("invalid iso8601")
    raw = s.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except Exception as exc:
        raise ValueError(f"invalid iso8601: {s}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_iso(dt: datetime) -> str:
    dt = dt.astimezone(timezone.utc)
    ms = f"{dt.microsecond // 1000:03d}"
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ms + "Z"


class Store:
    """All collections keyed by id; SystemClock is a single singleton."""

    def __init__(self):
        self.districts = {}
        self.schools = {}
        self.boundary_rules = {}
        self.windows = {}
        self.families = {}
        self.students = {}
        self.applications = {}
        self.sibling_bonds = {}
        self.offers = {}
        self.waitlist_entries = {}
        # SystemClock is a logical singleton with one mutable field
        self.clock_current_utc = None

    def reset(self):
        self.__init__()


store = Store()


def get_lock():
    return _lock
