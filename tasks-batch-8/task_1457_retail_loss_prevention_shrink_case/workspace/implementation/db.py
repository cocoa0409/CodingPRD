"""In-memory data store and logical clock.

All state lives in module-level dicts keyed by id. A fresh process boot
starts with empty state; nothing is seeded here.
"""

from datetime import datetime, timezone, timedelta

DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"


class Store:
    def __init__(self):
        self.stores = {}
        self.employees = {}
        self.exception_events = {}
        self.alerts = {}
        self.cases = {}
        self.interviews = {}
        self.evidence_items = {}
        self.custody_events = {}
        self.civil_demands = {}
        self.restitution_payments = {}
        self.orc_groups = {}
        self.case_links = {}
        self.shrink_periods = {}
        self.referral_packets = {}
        # per-store case sequence for case_number minting: {store_id: next_int}
        self.case_seq = {}


db = Store()


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

_clock = {"current": datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)}


def clock_now() -> datetime:
    """Current logical instant (never wall-clock)."""
    return _clock["current"]


def clock_set(dt: datetime):
    _clock["current"] = dt


def parse_iso(s):
    """Parse an ISO 8601 datetime string; accepts trailing Z."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_iso(dt: datetime) -> str:
    """ISO 8601 UTC with three fractional digits (milliseconds)."""
    dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % ms
