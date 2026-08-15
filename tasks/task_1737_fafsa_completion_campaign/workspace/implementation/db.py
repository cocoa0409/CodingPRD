"""In-memory data store. The store starts EMPTY on every boot — no seeding."""

import uuid
from datetime import datetime, timezone


def new_id():
    return str(uuid.uuid4())


def _now_iso():
    """ISO 8601 UTC with three fractional digits, e.g. 2025-05-24T10:30:00.123Z."""
    now = datetime.now(timezone.utc)
    ms = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
    return ms


class Store:
    """A flat in-memory store: one dict per collection, keyed by id."""

    def __init__(self):
        # Logical clock default: 2026-08-01T00:00:00Z
        self.clock_now = datetime(2026, 8, 1, tzinfo=timezone.utc)

        self.campaigns = {}
        self.schools = {}
        self.staff_profiles = {}
        self.senior_records = {}
        self.aid_records = {}
        self.aid_status_events = {}
        self.match_links = {}
        self.consent_records = {}
        self.events = {}
        self.staff_assignments = {}
        self.event_registrations = {}
        self.checklists = {}
        self.checklist_items = {}
        self.support_cases = {}
        self.completion_reports = {}

        # Per-collection creation ordering sequence for stable created_at ASC sorts
        # (created_at has ms precision; this breaks ties deterministically).
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


store = Store()


def make_common():
    """Return (id, created_at, updated_at, version) initial common field values."""
    now = _now_iso()
    return {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }


def touch(obj):
    """Refresh updated_at and bump version on mutation."""
    obj["updated_at"] = _now_iso()
    obj["version"] = obj.get("version", 1) + 1


def now_iso():
    return _now_iso()
