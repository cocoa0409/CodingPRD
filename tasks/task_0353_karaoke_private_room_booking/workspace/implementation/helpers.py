"""Shared validation / parsing / time helpers.

Field validation (PRD §2.8 priority 4: ERR_INVALID_REQUEST), datetime parsing,
pagination parameter parsing (PRD §2.3), and venue-clock resolution (PRD §2.9).
"""

from datetime import datetime, timezone

from flask import request

import db
import errors


# --- Request body access -----------------------------------------------------

def get_body():
    """Return the JSON body as a dict, or {} when none. Malformed JSON -> 422."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise errors.invalid_request("Request body is not valid JSON.")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise errors.invalid_request("Request body must be a JSON object.")
    return body


# --- Field validators (ERR_INVALID_REQUEST on failure) -----------------------

def require_field(body, name):
    if name not in body or body[name] is None:
        raise errors.invalid_request(f"Missing required field: {name}.")
    return body[name]


def opt_field(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    return body[name]


def as_string(value, name):
    if not isinstance(value, str) or value == "":
        raise errors.invalid_request(f"Field {name} must be a non-empty string.")
    return value


def as_int(value, name, minimum=None, maximum=None):
    # bool is a subclass of int — reject it explicitly.
    if isinstance(value, bool) or not isinstance(value, int):
        raise errors.invalid_request(f"Field {name} must be an integer.")
    if minimum is not None and value < minimum:
        raise errors.invalid_request(f"Field {name} must be >= {minimum}.")
    if maximum is not None and value > maximum:
        raise errors.invalid_request(f"Field {name} must be <= {maximum}.")
    return value


def as_number(value, name, minimum=None, maximum=None, exclusive_min=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise errors.invalid_request(f"Field {name} must be a number.")
    v = float(value)
    if minimum is not None and v < minimum:
        raise errors.invalid_request(f"Field {name} must be >= {minimum}.")
    if exclusive_min is not None and v <= exclusive_min:
        raise errors.invalid_request(f"Field {name} must be > {exclusive_min}.")
    if maximum is not None and v > maximum:
        raise errors.invalid_request(f"Field {name} must be <= {maximum}.")
    return v


def as_bool(value, name):
    if not isinstance(value, bool):
        raise errors.invalid_request(f"Field {name} must be a boolean.")
    return value


def as_enum(value, name, allowed):
    if not isinstance(value, str) or value not in allowed:
        raise errors.invalid_request(
            f"Field {name} must be one of {sorted(allowed)}."
        )
    return value


def parse_dt(value, name):
    """Parse an ISO 8601 UTC datetime into an aware datetime (ERR_INVALID_REQUEST)."""
    if not isinstance(value, str):
        raise errors.invalid_request(f"Field {name} must be an ISO 8601 string.")
    s = value.strip()
    try:
        if s.endswith("Z"):
            s2 = s[:-1] + "+00:00"
        else:
            s2 = s
        dt = datetime.fromisoformat(s2)
    except Exception:
        raise errors.invalid_request(f"Field {name} is not a valid ISO 8601 datetime.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def parse_stored_dt(value):
    """Parse a stored ISO string back into an aware UTC datetime."""
    if value is None:
        return None
    s = value
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s).astimezone(timezone.utc)


# --- Pagination (PRD §2.3) ---------------------------------------------------

def parse_pagination():
    """Return (limit, offset). Defaults: limit=10 (1..100), offset=0 (>=0)."""
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise errors.invalid_request("limit must be an integer.")
        if limit < 1 or limit > 100:
            raise errors.invalid_request("limit must be between 1 and 100.")

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise errors.invalid_request("offset must be an integer.")
        if offset < 0:
            raise errors.invalid_request("offset must be >= 0.")

    return limit, offset


def paginate(items, limit, offset):
    """Slice an already-sorted list and return (page, total_count)."""
    total = len(items)
    page = items[offset:offset + limit]
    return page, total


def sort_by_created(items):
    """Default list ordering: created_at ASC, id as a stable secondary key."""
    return sorted(items, key=lambda r: (r["created_at"], r["id"]))


# --- Venue clock (PRD §2.9) --------------------------------------------------

def current_utc(venue_id):
    """The venue-scoped logical clock as an aware UTC datetime.

    Falls back to real wall-clock UTC when the clock has not been set.
    """
    iso = db.venue_clocks.get(venue_id)
    if iso is None:
        return datetime.now(timezone.utc)
    return parse_stored_dt(iso)
