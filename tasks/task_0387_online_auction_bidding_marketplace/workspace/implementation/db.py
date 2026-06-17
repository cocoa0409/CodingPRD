"""In-memory data store.

All state lives in module-level dicts keyed by id. Nothing is persisted to disk
and nothing is seeded at startup — every entity is created via the API surface.
A fresh process therefore starts completely empty.

The logical clock (PRD §3.12) is also stored here. It defaults to "real" UTC now
until an admin sets/advances it.
"""
import uuid
from datetime import datetime, timezone

# Entity tables (id -> dict)
accounts = {}
listings = {}
bids = {}
watches = {}
offers = {}
orders = {}
seller_fee_invoices = {}
payments = {}
feedback = {}
disputes = {}

# Logical clock. None means "use real wall-clock now"; otherwise a datetime (UTC).
_clock = {"now": None}


def new_id():
    # PRD §2.4: id is a server-minted UUID with no type prefix.
    return str(uuid.uuid4())


def iso(dt):
    """Format a datetime as ISO 8601 UTC with three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def now_dt():
    """Current logical clock as a timezone-aware datetime."""
    if _clock["now"] is not None:
        return _clock["now"]
    return datetime.now(timezone.utc)


def now_iso():
    return iso(now_dt())


def set_clock(dt):
    _clock["now"] = dt


def parse_iso(value):
    """Parse an ISO 8601 timestamp into a tz-aware UTC datetime, or raise ValueError."""
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def reset():
    """Wipe every byte of state. Used only for completeness; a fresh process is empty."""
    for table in (accounts, listings, bids, watches, offers, orders,
                  seller_fee_invoices, payments, feedback, disputes):
        table.clear()
    _clock["now"] = None
