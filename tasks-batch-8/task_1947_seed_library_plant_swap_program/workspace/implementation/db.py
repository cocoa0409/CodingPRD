"""In-memory data store + logical clock. Store starts empty on every boot."""

import uuid
import threading
from datetime import datetime, timezone


_lock = threading.RLock()

# Logical clock: startup default exactly 2026-08-01T00:00:00Z. Never wall-clock.
_DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"


def parse_iso(s):
    """Parse an ISO8601 timestamp to an aware datetime (UTC). Accepts trailing Z."""
    if not isinstance(s, str):
        return None
    try:
        txt = s.strip()
        if txt.endswith("Z"):
            txt = txt[:-1] + "+00:00"
        dt = datetime.fromisoformat(txt)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def iso_z(dt):
    """Format a datetime as ISO8601 UTC with three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    ms = dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}"
    return ms + "Z"


class Store:
    def __init__(self):
        self.sites = {}
        self.members = {}
        self.volunteers = {}
        self.varieties = {}
        self.lots = {}
        self.tests = {}
        self.packets = {}
        self.checkouts = {}
        self.events = {}
        self.intake_items = {}
        self.credit_entries = {}
        self.sessions = {}
        self.assignments = {}
        # insertion-order counters for stable created_at ordering
        self.seq = 0
        # logical clock
        self._clock = parse_iso(_DEFAULT_CLOCK_ISO)

    # ---- logical clock ----
    def now(self):
        return self._clock

    def now_iso(self):
        return iso_z(self._clock)

    def set_clock(self, dt):
        self._clock = dt

    # ---- ids / timestamps ----
    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        self.seq += 1
        return self.seq

    def stamp_new(self, entity):
        """Set id, created_at, updated_at, version for a fresh entity."""
        entity["id"] = self.new_id()
        ts = self.now_iso()
        entity["created_at"] = ts
        entity["updated_at"] = ts
        entity["version"] = 1
        entity["_seq"] = self.next_seq()
        return entity

    def stamp_ledger(self, entity):
        """CreditEntry: only id and created_at (no updated_at, no version)."""
        entity["id"] = self.new_id()
        entity["created_at"] = self.now_iso()
        entity["_seq"] = self.next_seq()
        return entity

    def touch(self, entity):
        """Bump updated_at + version on mutation."""
        entity["updated_at"] = self.now_iso()
        entity["version"] = entity.get("version", 1) + 1


db = Store()


def reset_store():
    """For safety on re-import; normally a fresh process per test."""
    global db
    with _lock:
        db.__init__()
