"""In-memory data store. Wiped on every fresh process boot — NO seeding."""
import itertools
import uuid
from datetime import datetime, timezone

# Each collection is a dict keyed by entity id.
restaurants = {}
menu_items = {}
happy_hour_windows = {}
dining_tables = {}
waitlist_entries = {}
seatings = {}
checks = {}
courses = {}
order_items = {}
item_modifiers = {}
staff_members = {}
staff_shifts = {}
tip_pools = {}
tip_allocations = {}
payments = {}

# Monotonic counter giving every created record a strict creation order,
# used as the deterministic tie-break (created_at ASC == this seq ASC).
_seq = itertools.count(1)


def next_seq():
    return next(_seq)


def new_id():
    return str(uuid.uuid4())


EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def iso_ms(dt):
    """Render a datetime as ISO 8601 UTC with three fractional digits + Z."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(s):
    """Parse an ISO 8601 string into an aware UTC datetime."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
