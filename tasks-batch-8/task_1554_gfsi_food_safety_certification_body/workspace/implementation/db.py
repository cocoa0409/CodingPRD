"""In-memory data store, logical clock, and serialization helpers.

The store starts empty on every boot — no entity is seeded, preloaded, or
hardcoded at startup. Tests construct all preconditions via the API surface.
"""

import random
import string
import uuid
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# In-memory stores (keyed by id). All start empty.
# ---------------------------------------------------------------------------

schemes = {}
clients = {}
auditors = {}
decision_makers = {}
applications = {}
audits = {}
nonconformities = {}
certificates = {}
scope_changes = {}
appeals = {}
witness_audits = {}
directory_listings = {}

# Global certificate issuance sequence (CERT-NNNNNN, zero-padded 6 digits).
certificate_sequence = 0

# ---------------------------------------------------------------------------
# Logical clock — startup default 2026-08-01T00:00:00Z; never falls back to
# wall-clock time.
# ---------------------------------------------------------------------------

_current_utc = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def get_now():
    return _current_utc


def set_now(value):
    global _current_utc
    _current_utc = value


def next_certificate_number():
    global certificate_sequence
    certificate_sequence += 1
    return "CERT-%06d" % certificate_sequence


# ---------------------------------------------------------------------------
# Timestamp / id helpers
# ---------------------------------------------------------------------------


def parse_iso(value):
    """Parse an ISO-8601 timestamp into an aware UTC datetime.

    Returns None when the value is not a valid parseable timestamp string.
    """
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_dt(dt):
    """Serialize an aware UTC datetime as ISO 8601 with milliseconds + Z."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    return "%s.%03dZ" % (base, dt.microsecond // 1000)


def now_iso():
    return format_dt(get_now())


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return "req_" + suffix


def days(n):
    return timedelta(days=n)


def touch(entity):
    """Refresh updated_at and bump the optimistic-concurrency version."""
    entity["updated_at"] = get_now()
    entity["version"] = int(entity.get("version", 1)) + 1


# ---------------------------------------------------------------------------
# Serializers — datetimes are stored internally as aware datetimes and
# projected to the wire format here. Monetary floats are re-rounded to 2dp.
# ---------------------------------------------------------------------------

_COMMON_DATETIME_FIELDS = {"created_at", "updated_at"}

_ENTITY_DATETIME_FIELDS = {
    "applications": {"submitted_at", "reviewed_at"},
    "audits": {"window_start", "window_end", "started_at", "reported_at", "decided_at"},
    "nonconformities": {"deadline", "submitted_at", "reviewed_at"},
    "certificates": {"valid_from", "valid_to", "status_changed_at"},
    "scope_changes": {"decided_at"},
    "appeals": {"decided_at"},
    "witness_audits": {"witnessed_on"},
    "directory_listings": {"listed_at", "unlisted_at"},
    "auditors": {"last_witnessed_on"},
}

_MONEY_FIELDS = {
    "provisional_fee_quote",
    "final_fee",
    "audit_fee",
    "base_fee",
    "per_category_fee",
    "day_rate",
}


def serialize(entity, store_name=None):
    if entity is None:
        return None
    dt_fields = set(_COMMON_DATETIME_FIELDS)
    if store_name in _ENTITY_DATETIME_FIELDS:
        dt_fields |= _ENTITY_DATETIME_FIELDS[store_name]
    out = {}
    for key, value in entity.items():
        if value is None:
            out[key] = None
        elif key in dt_fields and isinstance(value, datetime):
            out[key] = format_dt(value)
        elif key in _MONEY_FIELDS and isinstance(value, (int, float)):
            out[key] = round(float(value), 2)
        else:
            out[key] = value
    return out
