"""In-memory data store and the single logical clock.

The store starts empty on every boot; no seeding. The logical clock starts at
exactly 2026-08-01T00:00:00Z and advances only via POST /api/_clock/set_current_utc
— it never falls back to wall-clock time (PRD section 2.5).
"""
import uuid
from datetime import datetime, timezone

DB = {
    "log_loads": {},
    "sawing_runs": {},
    "kiln_charges": {},
    "lumber_packages": {},
    "grade_inspections": {},
    "sales_contracts": {},
    "sales_orders": {},
    "price_lists": {},
    "byproduct_sales": {},
}

# Insertion-order counter for deterministic tie-breaking on equal timestamps.
_SEQ = {"n": 0}

DEFAULT_CLOCK_STR = "2026-08-01T00:00:00Z"


def _parse_iso(value):
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class _LogicalClock:
    def __init__(self):
        self.dt = _parse_iso(DEFAULT_CLOCK_STR)
        self.raw = DEFAULT_CLOCK_STR

    def set(self, raw):
        self.dt = _parse_iso(raw)
        self.raw = raw


CLOCK = _LogicalClock()


def new_id():
    return str(uuid.uuid4())


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


def now_dt():
    """Current logical time as an aware UTC datetime."""
    return CLOCK.dt


def fmt_dt(dt):
    """Serialize a datetime as ISO 8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    """Current logical time, ISO 8601 with three fractional digits.

    Resource timestamps (created_at, updated_at, decked_at, actual_start,
    actual_end, completed_at, stamped_at) are logical-clock values (PRD 2.5).
    """
    return fmt_dt(CLOCK.dt)


def wall_iso():
    """Wall-clock UTC timestamp for the meta envelope (three fractional digits)."""
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"
