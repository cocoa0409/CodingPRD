"""In-memory data store and logical clock.

All state lives in module-level dicts keyed by id. The store starts EMPTY on
every boot — nothing is seeded, preloaded, or hardcoded. Each start.sh
re-invocation produces a fresh process, so all state is wiped automatically.
"""
import uuid
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Logical clock. Before any operator sets it, the clock reads
# 2026-04-01T00:00:00Z (never the real wall clock).
# ---------------------------------------------------------------------------
DEFAULT_CLOCK = datetime(2026, 4, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = {"now": DEFAULT_CLOCK}


def now():
    """Return the current logical clock instant (UTC, tz-aware)."""
    return _clock["now"]


def set_clock(dt):
    _clock["now"] = dt


# ---------------------------------------------------------------------------
# Entity tables — one dict per entity, keyed by id.
# ---------------------------------------------------------------------------
shop_locations = {}
state_tint_regulations = {}
film_materials = {}
service_packages = {}
vehicle_profiles = {}
fleet_accounts = {}
quotes = {}
quote_lines = {}
medical_exemptions = {}
bays = {}
installers = {}
work_orders = {}
wrap_proofs = {}
callback_tickets = {}


def new_id():
    """Server-minted UUID with no type prefix."""
    return str(uuid.uuid4())


def iso(dt):
    """Render a datetime as ISO 8601 UTC with three fractional digits, Z suffix."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    # millisecond precision, trailing Z
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(value):
    """Parse an ISO 8601 datetime string into a tz-aware UTC datetime.

    Returns None if the value cannot be parsed.
    """
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    # Normalise trailing Z to +00:00 for fromisoformat
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
