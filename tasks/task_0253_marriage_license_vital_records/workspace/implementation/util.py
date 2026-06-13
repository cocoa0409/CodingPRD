"""Time helpers, common-field management, serialization."""
from datetime import datetime, timezone

from db import store
from errors import ApiError


def parse_dt(value, field_name="value"):
    """Parse an ISO 8601 string (date or datetime) into a tz-aware UTC datetime.

    Accepts trailing 'Z'. Bare dates ('YYYY-MM-DD') are treated as midnight UTC.
    Raises ERR_INVALID_REQUEST on a malformed value.
    """
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_REQUEST", f"{field_name} must be an ISO 8601 string")
    raw = value.strip()
    s = raw
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        # Try bare date.
        try:
            dt = datetime.strptime(raw, "%Y-%m-%d")
        except ValueError:
            raise ApiError("ERR_INVALID_REQUEST", f"{field_name} is not a valid ISO 8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def fmt_dt(dt):
    """Serialize a datetime to ISO 8601 UTC with three fractional digits and 'Z'."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_common(entity_type):
    """Build common system fields for a freshly created entity.

    entity_type 'ledger' carries only id + created_at (append-only audit row).
    """
    now = store.now()
    base = {
        "id": store.new_id(),
        "created_at": now,
        "_seq": store.next_seq(),
    }
    if entity_type != "ledger":
        base["updated_at"] = now
        base["version"] = 1
    return base


def touch(entity):
    """Bump updated_at + version on any mutation."""
    entity["updated_at"] = store.now()
    entity["version"] = entity.get("version", 1) + 1


# Fields that are internal bookkeeping and must not appear in responses.
_INTERNAL = {"_seq", "_absorbed_cents"}

# Datetime-typed fields per entity that need ISO formatting in output.
_DT_FIELDS = {
    "created_at", "updated_at",
    "date_of_birth", "prior_dissolution_date", "registration_expires_on",
    "issued_at", "valid_from", "expires_at",
    "ceremony_date", "filing_deadline", "registered_at",
}


def serialize(entity):
    """Convert an internal entity dict into a JSON-safe response object."""
    out = {}
    for k, v in entity.items():
        if k in _INTERNAL:
            continue
        if isinstance(v, datetime):
            out[k] = fmt_dt(v)
        else:
            out[k] = v
    return out
