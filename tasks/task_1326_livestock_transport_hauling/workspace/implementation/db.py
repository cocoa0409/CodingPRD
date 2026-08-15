"""In-memory data store and logical clock. Fresh process => empty store."""
import itertools
import uuid
from datetime import datetime, timezone

DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"
DEFAULT_CLOCK_DT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

store = {
    "shippers": {},
    "drivers": {},
    "duty_events": {},
    "trailers": {},
    "compartments": {},
    "loads": {},
    "allocations": {},
    "health_papers": {},
    "brand_inspections": {},
    "washouts": {},
    "weight_tickets": {},
    "settlements": {},
    "incidents": {},
    "holds": {},
}

clock = {"dt": DEFAULT_CLOCK_DT, "raw": DEFAULT_CLOCK_ISO}

_seq = itertools.count(1)


def next_seq():
    """Monotonic insertion sequence (stable tie-break for created_at)."""
    return next(_seq)


def new_id():
    return str(uuid.uuid4())


def now():
    return clock["dt"]
