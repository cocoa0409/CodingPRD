"""In-memory data store. All state is process-local and wiped on every boot.

No entity is ever seeded or preloaded — every record is created by tests
through the declared API surface.
"""
import uuid
import random
import string
from datetime import datetime, timezone

# One dict per entity, keyed by id.
gear_types = {}
rate_cards = {}
season_windows = {}
customers = {}
addons = {}
gear_units = {}
reservations = {}
reservation_addons = {}
condition_reports = {}
damage_assessments = {}
ledger_entries = {}

# Logical UTC clock (driven by POST /rental/_clock/set). Starts at real "now"
# but tests always set it explicitly before relying on it.
_clock = {"now": datetime.now(timezone.utc)}


def now_dt():
    return _clock["now"]


def set_clock(dt):
    _clock["now"] = dt


def new_id():
    return str(uuid.uuid4())


def iso(dt):
    """ISO 8601 UTC with exactly 3 fractional digits, e.g. 2025-05-24T10:30:00.123Z."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def request_id():
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


def request_timestamp():
    return iso(datetime.now(timezone.utc))
