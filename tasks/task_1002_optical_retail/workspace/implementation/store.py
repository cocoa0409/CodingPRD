"""In-memory data store, logical clock, and identity/timestamp helpers.

The store starts EMPTY on every boot. Nothing is seeded here or anywhere else;
every entity is created by callers through the declared API surface.
"""
import uuid
from datetime import datetime, timedelta, timezone

# PRD 2.5 -- the logical clock reads exactly this before any client touches it,
# and never falls back to wall-clock time.
CLOCK_EPOCH = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)

# --------------------------------------------------------------------------
# Collections (id -> record dict)
# --------------------------------------------------------------------------
policies = {}
stores = {}
frames = {}
lens_options = {}
customers = {}
prescriptions = {}
kits = {}
kit_items = {}
appointments = {}
orders = {}
lab_orders = {}
claims = {}
warranty_claims = {}

_clock = {"now": CLOCK_EPOCH}
_seq = {"n": 0}


def clock_now():
    return _clock["now"]


def set_clock(dt):
    _clock["now"] = dt


def next_seq():
    _seq["n"] += 1
    return _seq["n"]


def new_id():
    return str(uuid.uuid4())


# --------------------------------------------------------------------------
# Timestamp formatting / parsing
# --------------------------------------------------------------------------
def iso_ms(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.4)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def wall_now_iso():
    return iso_ms(datetime.now(timezone.utc))


def parse_iso(value):
    """Parse an ISO 8601 instant. Returns an aware UTC datetime or None."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    # Normalise fractional seconds to a length datetime.fromisoformat accepts.
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        try:
            dt = datetime.strptime(text, "%Y-%m-%d")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def days_between_floor(later, earlier):
    """floor((later - earlier) / 86400 seconds)."""
    delta = later - earlier
    return int(delta.total_seconds() // 86400)


def days_between_ceil(later, earlier):
    """ceil((later - earlier) / 86400 seconds)."""
    seconds = (later - earlier).total_seconds()
    whole = int(seconds // 86400)
    if seconds % 86400 > 0:
        whole += 1
    return whole


def minus_days(dt, days):
    return dt - timedelta(days=days)


# --------------------------------------------------------------------------
# Record helpers
# --------------------------------------------------------------------------
def new_record(**fields):
    """Create a record carrying the common fields (id/created_at/updated_at/version)."""
    now = wall_now_iso()
    rec = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    rec["_seq"] = next_seq()
    rec.update(fields)
    return rec


def touch(rec):
    """A mutation of a resource: refresh updated_at and increment version (PRD 2.4)."""
    rec["updated_at"] = wall_now_iso()
    rec["version"] += 1


def ordered(collection):
    """Every list endpoint sorts by creation timestamp ascending (PRD 2.3)."""
    return sorted(collection.values(), key=lambda r: r["_seq"])
