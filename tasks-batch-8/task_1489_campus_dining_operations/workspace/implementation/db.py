"""In-memory data store. The store starts empty on every boot; no seeding."""
import itertools
import uuid
from datetime import datetime, timezone

DB = {
    "dining_halls": {},
    "vendor_contracts": {},
    "menu_cycles": {},
    "recipes": {},
    "meal_periods": {},
    "swipe_events": {},
    "forecasts": {},
    "accommodation_requests": {},
    "labor_shifts": {},
    "waste_logs": {},
    "inspection_reports": {},
    "corrective_actions": {},
    "departments": {},
    "catering_orders": {},
    "commission_statements": {},
}

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# Logical clock (PRD section 2.4). value = verbatim string last supplied;
# dt = parsed datetime used for all comparisons.
CLOCK = {"value": DEFAULT_CLOCK, "dt": datetime(2026, 8, 1, tzinfo=timezone.utc)}

# Monotonic insertion sequence for stable created_at ordering / tie-breaks.
_SEQ = itertools.count(1)


def next_seq():
    return next(_SEQ)


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """Wall-clock UTC timestamp, ISO 8601 with three fractional digits."""
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def logical_now_str():
    """Current logical-clock instant as a string (verbatim as last set)."""
    return CLOCK["value"]


def logical_now_dt():
    return CLOCK["dt"]
