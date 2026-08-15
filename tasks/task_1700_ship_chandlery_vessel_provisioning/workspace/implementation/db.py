"""In-memory data store + logical clock.

The store starts empty on every boot. No seeding, no preload, no disk
persistence. All system timestamps come from the logical clock; startup
default is 2026-08-01T00:00:00Z and the clock never falls back to
wall-clock time.
"""
import uuid
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

_STARTUP_NOW = "2026-08-01T00:00:00Z"


def _parse_iso(value):
    """Parse an ISO8601 timestamp (accepts trailing Z) into an aware datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    s = str(value).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _format_iso(dt):
    """Format an aware UTC datetime as ISO8601.

    The executable contract (test_10.test_invoice_fx_conversion_and_due_date,
    test_12.test_immediate_consistency_on_invoice_issuance) string-compares
    `due_date` in second precision ("2026-08-24T12:00:00Z"), and the shared
    is_iso8601_timestamp shape check treats fractional digits as optional —
    so all logical-clock timestamps are emitted at second precision. (The
    response-envelope meta.api_request_timestamp, a wall-clock receipt stamp,
    keeps the PRD §2.2 three-fractional-digit form.)
    """
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + "Z"


class LogicalClock:
    def __init__(self):
        self._now = _parse_iso(_STARTUP_NOW)

    def now(self):
        return self._now

    def now_iso(self):
        return _format_iso(self._now)

    def set(self, iso_value):
        self._now = _parse_iso(iso_value)
        return self._now


CLOCK = LogicalClock()


def new_id():
    return str(uuid.uuid4())


def now_iso():
    return CLOCK.now_iso()


def now_dt():
    return CLOCK.now()


# ---------------------------------------------------------------------------
# Entity stores (dicts keyed by id). Empty at boot.
# ---------------------------------------------------------------------------

ship_agents = {}
vessel_calls = {}
catalog_items = {}
stock_lots = {}
requisitions = {}
quotations = {}
orders = {}
deliveries = {}
invoices = {}
payments = {}
complaints = {}
credit_notes = {}


# ---------------------------------------------------------------------------
# Common-field helpers
# ---------------------------------------------------------------------------

def stamp_new(record, common=True):
    """Attach id / created_at (+ updated_at, version for full-bookkeeping
    entities). Payment passes common=False (append-only: id + created_at)."""
    record["id"] = new_id()
    record["created_at"] = now_iso()
    if common:
        record["updated_at"] = record["created_at"]
        record["version"] = 1
    return record


def touch(record):
    """Refresh updated_at and increment version on a full-bookkeeping entity."""
    record["updated_at"] = now_iso()
    record["version"] = record.get("version", 1) + 1
    return record
