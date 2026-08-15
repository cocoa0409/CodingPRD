"""In-memory data store, logical clock, and id/timestamp helpers.

The store starts empty on every boot. The ONLY pre-existing row is the
ObligationRegister singleton, which the spec mandates is auto-created at
server boot (current_version_number 0, version 1, singleton_note SINGLETON).
No other entity is ever seeded.
"""

import uuid
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Logical clock (PRD §2.4): boot default exactly 2026-08-01T00:00:00Z; never
# falls back to wall-clock time.
# ---------------------------------------------------------------------------

BOOT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Store containers (insertion-ordered dicts keyed by entity id)
# ---------------------------------------------------------------------------


def new_id():
    return uuid.uuid4().hex


class Store:
    def __init__(self):
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.business_owners = {}
        self.regulatory_changes = {}
        self.obligations = {}
        self.controls = {}
        self.mappings = {}
        self.register = None            # singleton dict
        self.register_versions = {}
        self.assessments = {}
        self.gap_analyses = {}
        self.plans = {}
        self.policy_updates = {}
        self.rollouts = {}
        self.packages = {}
        self.escalations = {}
        self.reports = {}
        self.audit_events = []          # list, replay order == sequence_number ASC
        self._bootstrap_register()

    def _bootstrap_register(self):
        """Create the single ObligationRegister row mandated by the spec."""
        now = self.clock
        self.register = {
            "id": new_id(),
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "current_version_number": 0,
            "singleton_note": "SINGLETON",
        }


store = Store()


def reset_store():
    """Re-initialize the whole store (used by tests via fresh process boot)."""
    global store
    store = Store()
    return store


# ---------------------------------------------------------------------------
# Datetime helpers — all values are aware UTC datetimes internally.
# ---------------------------------------------------------------------------


def parse_dt(value):
    """Parse an ISO 8601 datetime string; naive values are treated as UTC.

    Raises ValueError on unparseable input (caller maps to ERR_INVALID_REQUEST).
    """
    if not isinstance(value, str):
        raise ValueError("datetime must be a string")
    s = value.strip()
    if not s:
        raise ValueError("empty datetime")
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    """Serialize an aware UTC datetime as ISO 8601.

    Matches every PRD example: whole-second values render as
    '2026-08-01T00:00:00Z'; sub-second values render with three fractional
    digits, e.g. '2025-05-24T10:30:00.123Z'.
    """
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def wall_timestamp():
    """api_request_timestamp: server wall clock, always 3 fractional digits."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (now.microsecond // 1000)


def now_clock():
    return store.clock


def touch(entity):
    """Refresh updated_at and bump version on a mutated entity."""
    entity["updated_at"] = store.clock
    entity["version"] = entity.get("version", 1) + 1


def stamp_new(entity):
    """Attach common system fields to a freshly created entity."""
    entity["created_at"] = store.clock
    entity["updated_at"] = store.clock
    entity["version"] = 1
    return entity
