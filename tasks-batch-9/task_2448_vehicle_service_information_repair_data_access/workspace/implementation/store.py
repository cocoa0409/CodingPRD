"""In-memory data store, the logical clock, and row bookkeeping.

Storage is process-local Python dicts keyed by id.  The store is EMPTY on every
boot: no entity is seeded, preloaded or hardcoded anywhere.  Every row is
created through a declared API endpoint.
"""

import itertools
import re
import uuid
from datetime import datetime, timedelta, timezone

# PRD 2.9: "Before any clock-setting call has been made, the logical clock reads
# exactly 2026-08-01T00:00:00Z; the platform must never fall back to real
# wall-clock time."
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(\.\d+)?(Z|z|\+00:00|\+0000)$"
)


def parse_iso(value):
    """Parse an ISO 8601 UTC instant.  Returns None when the value is not one."""
    if not isinstance(value, str):
        return None
    m = _ISO_RE.match(value.strip())
    if not m:
        return None
    try:
        frac = m.group(7) or ""
        micro = 0
        if frac:
            digits = (frac[1:] + "000000")[:6]
            micro = int(digits)
        return datetime(
            int(m.group(1)),
            int(m.group(2)),
            int(m.group(3)),
            int(m.group(4)),
            int(m.group(5)),
            int(m.group(6)),
            micro,
            tzinfo=timezone.utc,
        )
    except ValueError:
        return None


def format_iso(dt):
    """Render an instant as ISO 8601 UTC with three fractional digits."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


class Store(object):
    def __init__(self):
        self.manufacturers = {}
        self.vehicle_models = {}
        self.system_areas = {}
        self.licenses = {}
        self.shops = {}
        self.technicians = {}
        self.entitlements = {}
        self.seat_assignments = {}
        self.diagnostic_tools = {}
        self.publications = {}
        self.publication_versions = {}
        self.gateway_sessions = {}
        self.jobs = {}
        self.audit_events = {}
        self._seq = itertools.count(1)
        self.current_utc = parse_iso(DEFAULT_CLOCK_ISO)
        self.current_utc_raw = DEFAULT_CLOCK_ISO

    # -- clock ------------------------------------------------------------
    def now(self):
        return self.current_utc

    def now_iso(self):
        return format_iso(self.current_utc)

    def set_clock(self, raw, dt):
        self.current_utc_raw = raw
        self.current_utc = dt

    # -- row bookkeeping --------------------------------------------------
    def next_seq(self):
        return next(self._seq)

    def new_id(self):
        return str(uuid.uuid4())

    def base_row(self, common=True):
        """A fresh row carrying id/created_at (+ updated_at/version when common)."""
        row = {"id": self.new_id(), "created_at": self.now_iso(), "_seq": self.next_seq()}
        if common:
            row["updated_at"] = row["created_at"]
            row["version"] = 1
        return row

    def touch(self, row):
        """Record a mutation: refresh updated_at and advance version by exactly 1."""
        row["updated_at"] = self.now_iso()
        if "version" in row:
            row["version"] = row["version"] + 1


store = Store()


DAY = timedelta(days=1)


def whole_days(later, earlier):
    """floor((later - earlier) / 86400 seconds) -- PRD 2.9 truncates downward."""
    seconds = (later - earlier).total_seconds()
    return int(seconds // 86400) if seconds >= 0 else -int((-seconds + 86399) // 86400)
