"""In-memory data store, the server logical clock and record helpers.

The store starts EMPTY on every boot.  Nothing is seeded, preloaded or
hardcoded here; every entity is created through the declared API surface.
"""

import random
import string
import uuid
from datetime import date, datetime, timedelta, timezone

CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------
# tables
# ---------------------------------------------------------------------------
branches = {}
trailer_types = {}
trailers = {}
customers = {}
certificates = {}
rate_cards = {}
agreements = {}
agreement_units = {}
maintenance_events = {}
damage_assessments = {}
chargebacks = {}
relocation_orders = {}

_state = {"clock": CLOCK_START, "seq": 0}


def now():
    """The server logical clock instant."""
    return _state["clock"]


def clock_date():
    return _state["clock"].date()


def set_clock(dt):
    _state["clock"] = dt


def next_seq():
    _state["seq"] += 1
    return _state["seq"]


def new_id():
    return str(uuid.uuid4())


def iso_ts(dt=None):
    dt = dt or now()
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def new_record(with_common=True):
    """Create a fresh record dict carrying the four common properties."""
    rec = {"id": new_id(), "created_at": iso_ts(), "_seq": next_seq()}
    if with_common:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    return rec


def touch(rec):
    """Register a mutation: refresh updated_at and advance version."""
    rec["updated_at"] = iso_ts()
    if "version" in rec:
        rec["version"] = rec["version"] + 1
    return rec


# ---------------------------------------------------------------------------
# date helpers
# ---------------------------------------------------------------------------
def parse_date(value):
    """Parse an ISO calendar date; returns None when unparseable."""
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def parse_datetime(value):
    if not isinstance(value, str):
        return None
    txt = value.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_days(d, n):
    return d + timedelta(days=n)


def day_count(a, b):
    """Number of calendar days in the half-open range [a, b)."""
    return (b - a).days


def sorted_rows(rows):
    """Default list ordering: created_at ascending (insertion order breaks ties)."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def reset():
    """Drop every row.  Only used by tests of this module; never at boot."""
    for table in (branches, trailer_types, trailers, customers, certificates,
                  rate_cards, agreements, agreement_units, maintenance_events,
                  damage_assessments, chargebacks, relocation_orders):
        table.clear()
    _state["clock"] = CLOCK_START
    _state["seq"] = 0
