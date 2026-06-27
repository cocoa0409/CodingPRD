"""In-memory data store. All state lives in module-level dicts keyed by id.

No persistence, no seeding. start.sh re-invocation wipes everything because the
process restarts from scratch.
"""
import uuid
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Entity tables (id -> record dict). Empty at boot — tests build all state.
# ---------------------------------------------------------------------------
drugs = {}
pharmacies = {}
price_quotes = {}
members = {}
gold_memberships = {}
discount_cards = {}
comparisons = {}
insurance_estimates = {}
claims = {}
copay_cards = {}
copay_links = {}
mail_orders = {}
telehealth_referrals = {}

# ---------------------------------------------------------------------------
# Logical clock. PRD §2.9: startup default is exactly 2026-05-01T00:00:00Z.
# ---------------------------------------------------------------------------
DEFAULT_CLOCK = "2026-05-01T00:00:00Z"
_clock = {"now": DEFAULT_CLOCK}


def set_clock(iso8601):
    _clock["now"] = iso8601


def get_clock_raw():
    return _clock["now"]


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def parse_iso(value):
    """Parse an ISO-8601 instant into a tz-aware UTC datetime. Returns None on failure."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def clock_now_dt():
    return parse_iso(_clock["now"])


def now_iso():
    """Server wall-clock timestamp for audit fields: ISO 8601 UTC, 3 fractional digits."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_id():
    return str(uuid.uuid4())


def request_id():
    return "req_" + uuid.uuid4().hex


# ---------------------------------------------------------------------------
# Record lifecycle helpers
# ---------------------------------------------------------------------------
def stamp_create(record, common_fields=True):
    """Attach id + audit fields at creation time."""
    record["id"] = new_id()
    ts = now_iso()
    record["created_at"] = ts
    if common_fields:
        record["updated_at"] = ts
        record["version"] = 1
    return record


def touch(record):
    """Refresh updated_at + bump version on any mutation (entities with full audit set)."""
    record["updated_at"] = now_iso()
    if "version" in record:
        record["version"] = record["version"] + 1


def reset_all():
    for table in (drugs, pharmacies, price_quotes, members, gold_memberships,
                  discount_cards, comparisons, insurance_estimates, claims,
                  copay_cards, copay_links, mail_orders, telehealth_referrals):
        table.clear()
    _clock["now"] = DEFAULT_CLOCK
