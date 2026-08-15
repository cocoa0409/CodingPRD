"""In-memory data store plus logical clock.

The store starts empty on every boot. No seeding of any entity is permitted.
The logical clock boots at exactly 2026-08-01T00:00:00Z and only advances via
POST /_clock/set_current_utc — it never falls back to real wall-clock time.
"""

import uuid
from datetime import datetime, timezone, timedelta


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

_DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_logical_clock = _DEFAULT_CLOCK


def get_logical_now() -> datetime:
    return _logical_clock


def get_logical_now_iso() -> str:
    return format_ts(_logical_clock)


def set_logical_clock(dt: datetime):
    global _logical_clock
    _logical_clock = dt


def get_logical_date():
    return _logical_clock.date()


# ---------------------------------------------------------------------------
# Timestamp helpers — ISO 8601 UTC with three fractional digits ("...123Z")
# ---------------------------------------------------------------------------

def format_ts(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{ms:03d}Z"


def now_ts() -> str:
    """Timestamp for created_at/updated_at fields.

    PRD requires an ISO-8601 UTC timestamp with three fractional digits.
    This records when the resource was created/mutated (server receipt time).
    """
    return format_ts(datetime.now(timezone.utc))


def parse_iso_datetime(value: str) -> datetime:
    """Parse an ISO-8601 datetime (accepts trailing Z)."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_iso_date(value: str):
    """Parse a strict YYYY-MM-DD date."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    v = value.strip()
    if len(v) != 10:
        raise ValueError("bad date")
    return datetime.strptime(v, "%Y-%m-%d").date()


# ---------------------------------------------------------------------------
# ID / request-id generation
# ---------------------------------------------------------------------------

def new_id() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    return "req_" + uuid.uuid4().hex[:24]


# ---------------------------------------------------------------------------
# Entity stores — plain dicts keyed by id. Empty at boot.
# ---------------------------------------------------------------------------

provider_sites = {}
storage_units = {}
vaccine_products = {}
lots = {}
temperature_readings = {}
temperature_excursions = {}
patients = {}
eligibility_screenings = {}
dose_administrations = {}
vaccine_orders = {}
order_lines = {}
allocation_receipts = {}
borrow_tickets = {}
site_visit_audits = {}
short_date_transfers = {}

# Per-site order number sequence
_order_number_counters = {}


def next_order_number(site_id: str) -> str:
    n = _order_number_counters.get(site_id, 0) + 1
    _order_number_counters[site_id] = n
    return f"ORD-{n:06d}"


def age_years_on(date_of_birth, on_date) -> int:
    """Full years elapsed: floor((on_date - dob) / 365.25 days)."""
    days = (on_date - date_of_birth).days
    return int(days // 365.25) if days >= 0 else -1
