"""In-memory data store, logical clock, identity/timestamp helpers.

Storage is in-memory only: plain dicts keyed by id. The store starts EMPTY on
every boot — nothing is seeded, preloaded, or persisted anywhere.
"""
import uuid
from datetime import datetime, timezone

# --- Entity stores (dicts keyed by id) ------------------------------------
programs = {}
contractors = {}
accounts = {}
meters = {}
waves = {}
work_orders = {}
notifications = {}
appointments = {}
no_access_cases = {}
readings = {}
endpoint_registrations = {}
bench_tests = {}
complaints = {}
quality_audits = {}
invoices = {}

_seq = [0]


def next_seq():
    _seq[0] += 1
    return _seq[0]


def new_id():
    # Server-minted UUID with no type prefix (PRD 2.4).
    return str(uuid.uuid4())


# --- Logical clock ----------------------------------------------------------
# Startup default is exactly 2026-05-01T00:00:00Z; the server never falls back
# to wall-clock time (PRD 2.4).
_clock = [datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)]


def clock_now():
    return _clock[0]


def set_clock(dt):
    _clock[0] = dt


def fmt_ts(dt):
    """ISO 8601 UTC with three fractional digits, e.g. 2026-05-01T00:00:00.000Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_dt(value):
    """Parse an ISO 8601 timestamp to an aware UTC datetime; ValueError if bad."""
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def base_resource():
    """Common fields for a mutable resource: id/created_at/updated_at/version."""
    now = clock_now()
    return {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(res):
    """Every successful mutation increments version by exactly one and
    refreshes updated_at from the logical clock (PRD 2.8)."""
    res["version"] += 1
    res["updated_at"] = clock_now()
