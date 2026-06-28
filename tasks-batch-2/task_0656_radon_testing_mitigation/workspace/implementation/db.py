"""In-memory data store for the Radon Testing & Mitigation API.

All state lives in process-local dicts keyed by UUID id. Nothing is persisted to
disk, no SQLite, no /tmp cache. A fresh process starts completely empty (the only
non-empty default is the logical clock value, per PRD §1) — the test harness builds
every entity via the declared API surface.
"""

import datetime
import uuid

# Logical-clock default at server start (PRD §1, §2.4, §3.8).
CLOCK_DEFAULT = "2026-04-01T00:00:00Z"


class Store:
    """Process-local in-memory store. Re-instantiated on every boot."""

    def __init__(self):
        # One dict per entity collection, keyed by id.
        self.properties = {}
        self.inspectors = {}
        self.crews = {}
        self.radon_tests = {}
        self.mitigation_jobs = {}
        self.permits = {}
        self.warranties = {}
        self.retest_schedules = {}
        self.payment_records = {}
        # The logical clock (ClockState). current_utc is an aware UTC datetime.
        self.clock_current_utc = parse_iso8601(CLOCK_DEFAULT)
        # ClockState resource fields (id + created_at only, per PRD §2.4).
        self.clock_id = new_id()
        self.clock_created_at = self.clock_current_utc
        # Monotonic creation counter for stable secondary ordering / tie-breaks.
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


def new_id():
    """Server-minted UUID with no type prefix (PRD §2.4)."""
    return str(uuid.uuid4())


def parse_iso8601(value):
    """Parse an ISO 8601 UTC instant into an aware UTC datetime.

    Accepts a trailing 'Z' or an explicit offset. Returns a tz-aware datetime
    normalized to UTC. Raises ValueError on malformed input.
    """
    if not isinstance(value, str):
        raise ValueError("datetime must be a string")
    s = value.strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    dt = datetime.datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc)


def format_iso8601_millis(dt):
    """Format an aware datetime as ISO 8601 UTC with exactly three fractional
    digits and a trailing 'Z' (PRD §2.2, §2.4)."""
    dt = dt.astimezone(datetime.timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# Module-level singleton store. Created once per process => wiped on every reboot.
store = Store()


def reset():
    """Replace the store with a brand-new empty one (used only for completeness;
    a fresh process already starts empty)."""
    global store
    store = Store()
