"""In-memory data store and logical clock.

The store starts empty on every boot — no seeding of any kind.
"""
import uuid
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

_START_ISO = "2026-05-01T00:00:00Z"
_clock_iso = None  # stored as aware datetime


def _parse_iso(s):
    if s is None:
        return None
    if isinstance(s, datetime):
        return s
    txt = str(s).strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def clock_init():
    global _clock_iso
    _clock_iso = _parse_iso(_START_ISO)


def now():
    return _clock_iso


def set_clock(to_iso8601):
    global _clock_iso
    _clock_iso = _parse_iso(to_iso8601)


def iso_now():
    return format_iso(now())


def format_iso(dt):
    """Format an aware datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % ms


clock_init()

# ---------------------------------------------------------------------------
# Entity stores (dicts keyed by id). Empty at boot.
# ---------------------------------------------------------------------------

campaigns = {}
members = {}
stations = {}
piles = {}
bookings = {}
tickets = {}
samples = {}
pile_allocations = {}
loss_events = {}
pools = {}
installments = {}
ledger_entries = {}
settlements = {}


def new_id():
    return str(uuid.uuid4())


def stamp_new(obj):
    ts = iso_now()
    obj["id"] = new_id()
    obj["created_at"] = ts
    obj["updated_at"] = ts
    obj["version"] = 1
    return obj


def touch(obj):
    obj["updated_at"] = iso_now()
    obj["version"] = obj.get("version", 1) + 1
    return obj


def stamp_ledger(obj):
    # PaymentLedgerEntry: append-only; only id + created_at
    ts = iso_now()
    obj["id"] = new_id()
    obj["created_at"] = ts
    return obj
