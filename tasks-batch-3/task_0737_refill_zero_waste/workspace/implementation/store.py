"""In-memory data store, logical clock, id/sequence generation and timestamp helpers.

All state lives in module-level dicts and is wiped on every process start — the test
harness relaunches the server (via start.sh) before every test, so a fresh boot must
guarantee empty state. Nothing is ever seeded here.
"""
import uuid
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# Logical clock. Fixed startup default; never real wall-clock. Set only via
# POST /v1/_clock/set_current_utc.
# ---------------------------------------------------------------------------
CLOCK_DEFAULT = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = {"now": CLOCK_DEFAULT}

# Monotonic sequence for stable tie-breaking of equal timestamps.
_seq = {"n": 0}

# One dict per entity type, keyed by id.
DB = {
    "members": {},
    "products": {},
    "stations": {},
    "bins": {},
    "containers": {},
    "orders": {},
    "lines": {},
    "restock_tasks": {},
    "subscriptions": {},
    "vehicles": {},
    "deliveries": {},
    "wallet_ledger": {},
}


def reset():
    for d in DB.values():
        d.clear()
    _clock["now"] = CLOCK_DEFAULT
    _seq["n"] = 0


def now():
    return _clock["now"]


def set_clock(dt):
    _clock["now"] = dt


def next_seq():
    _seq["n"] += 1
    return _seq["n"]


def new_id():
    return str(uuid.uuid4())


def add_days(dt, days):
    return dt + timedelta(days=days)


# ---------------------------------------------------------------------------
# Datetime parse / format helpers
# ---------------------------------------------------------------------------
def parse_dt(s):
    """Parse an ISO 8601 string into an aware UTC datetime. Raises ValueError on bad input."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    """Format an aware datetime as ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % millis
