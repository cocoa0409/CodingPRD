"""In-memory data store. All state lives in module-level dicts; rebooting the
process wipes everything (per-test-server isolation)."""

import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.jurisdictions = {}        # id -> dict
        self.contractors = {}          # id -> dict
        self.engagements = {}          # id -> dict
        self.questionnaires = {}       # engagement_id -> dict (upsert, one per engagement)
        self.determinations = {}       # id -> dict
        self.exceptions = {}           # id -> dict (ExceptionGrant)
        self.contracts = {}            # id -> dict
        self.amendments = {}           # id -> dict
        self.reviews = {}              # id -> dict
        self.audits = {}               # id -> dict
        self.remediation_actions = {}  # id -> dict
        self.filings = {}              # id -> dict
        self.inquiries = {}            # id -> dict
        self.conversions = {}          # id -> dict

        # logical clock; startup default exactly 2026-08-01T00:00:00Z
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


store = Store()


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """Current logical clock instant as ISO 8601 UTC with three fractional digits."""
    dt = store.clock
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(value):
    """Parse an ISO-8601 datetime (accepts trailing Z). Returns aware datetime or None."""
    if not isinstance(value, str):
        return None
    try:
        v = value
        if v.endswith("Z"):
            v = v[:-1] + "+00:00"
        dt = datetime.fromisoformat(v)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def parse_date(value):
    """Parse an ISO date string YYYY-MM-DD -> date or None."""
    if not isinstance(value, str):
        return None
    try:
        parts = value.split("T")[0]
        y, m, d = parts.split("-")
        from datetime import date
        return date(int(y), int(m), int(d))
    except (ValueError, TypeError):
        return None
