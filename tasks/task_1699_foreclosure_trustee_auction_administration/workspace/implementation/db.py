"""In-memory data store + logical clock.

The store starts empty on every boot. No seeding, no preload, no disk
persistence. All domain timestamps come from the logical clock; startup
default is exactly 2026-08-01T00:00:00Z (PRD §2.5) and the clock never
falls back to wall-clock time. The clock is freely settable forward or
backward via POST /_clock/set_current_utc.
"""
import itertools
import uuid
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

_STARTUP_NOW = "2026-08-01T00:00:00Z"


def _parse_iso(value):
    """Parse an ISO8601 timestamp (accepts trailing Z) into an aware UTC datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        s = str(value).strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _format_iso(dt):
    """Format an aware UTC datetime as ISO8601 with three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".{:03d}Z".format(ms)


class LogicalClock:
    def __init__(self):
        self._now = _parse_iso(_STARTUP_NOW)

    def now(self):
        return self._now

    def now_iso(self):
        return _format_iso(self._now)

    def now_date(self):
        return self._now.date()

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


# Global creation counter: deterministic tie-break ordering when two records
# share the same logical created_at (record identifiers are never used for
# ordering, per PRD/calculations).
_seq_counter = itertools.count(1)


def next_seq():
    return next(_seq_counter)


# ---------------------------------------------------------------------------
# Entity stores (dicts keyed by id). Empty at boot — no seeding.
# ---------------------------------------------------------------------------

beneficiaries = {}
foreclosure_cases = {}
notices_of_default = {}
notices_of_trustee_sale = {}
publications = {}
auction_sales = {}
postponements = {}
bidder_registrations = {}
bids = {}
bidding_instructions = {}
quotes = {}
cost_advances = {}
stay_orders = {}
trustees_deeds = {}
surplus_claims = {}
disbursements = {}


# ---------------------------------------------------------------------------
# Common-field helpers (PRD §2.4)
# ---------------------------------------------------------------------------

def stamp_new(record, common=True):
    """Attach id / created_at (+ updated_at, version) for full-bookkeeping
    entities. Postponement and Bid pass common=False: they are immutable
    ledger entries carrying only id and created_at (no updated_at/version)."""
    record["id"] = new_id()
    record["created_at"] = now_iso()
    record["_seq"] = next_seq()
    if common:
        record["updated_at"] = record["created_at"]
        record["version"] = 1
    return record


def touch(record):
    """Refresh updated_at and increment version on a full-bookkeeping entity.
    PRD §2.4: version increments on every mutation, including cascades."""
    record["updated_at"] = now_iso()
    record["version"] = record.get("version", 1) + 1
    return record


def pub(record):
    """Public view of a record: strip internal underscore-prefixed keys."""
    if record is None:
        return None
    return {k: v for k, v in record.items() if not k.startswith("_")}
