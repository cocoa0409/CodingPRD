"""In-memory data store. Every dict starts empty at boot — no seeding."""

import threading
import uuid
from datetime import datetime, timezone, timedelta


class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.products = {}
        self.components = {}
        self.scans = {}
        self.boms = {}
        self.bom_entries = {}
        self.approvals = {}
        self.tickets = {}
        self.vulnerabilities = {}
        self.findings = {}
        self.gates = {}
        self.plans = {}
        self.engagements = {}
        # Logical clock — default 2026-08-01T00:00:00Z
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

    def now(self):
        return self.clock

    def now_iso(self):
        return iso_fmt(self.clock)

    def set_clock(self, dt):
        self.clock = dt


store = Store()


def new_id():
    return str(uuid.uuid4())


def iso_fmt(dt):
    """ISO 8601 UTC with three fractional digits, e.g. 2026-08-01T00:00:00.000Z"""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    ms = dt.microsecond // 1000
    return f"{base}.{ms:03d}Z"


def parse_iso(s):
    """Parse an ISO 8601 timestamp into an aware datetime (UTC)."""
    if s is None:
        return None
    if isinstance(s, datetime):
        return s if s.tzinfo else s.replace(tzinfo=timezone.utc)
    s = str(s).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        # try a couple of fallbacks
        for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(s, fmt)
                break
            except ValueError:
                continue
        else:
            raise
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def touch(resource):
    """Refresh updated_at and bump the system revision counter on a mutated resource.

    Most entities expose the revision counter as `version`. Components carry a
    client-supplied package-version string under `version` (PRD section 2.4 naming
    note), so their revision counter lives in `_rev` instead.
    """
    resource["updated_at"] = store.now_iso()
    v = resource.get("version")
    if isinstance(v, int):
        resource["version"] = v + 1
    else:
        resource["_rev"] = int(resource.get("_rev", 1)) + 1


def base_resource():
    now = store.now_iso()
    return {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }


def days_from(dt, days):
    return dt + timedelta(days=days)
