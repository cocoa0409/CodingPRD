"""Shared helpers: serialization, pagination, body parsing, field validation,
and logical-clock time arithmetic.
"""
import datetime

from flask import request

import errors

# Internal bookkeeping fields hidden from API output.
_HIDDEN = {"_seq"}


def serialize(rec):
    """Return a copy of the record without internal bookkeeping fields."""
    return {k: v for k, v in rec.items() if k not in _HIDDEN}


def get_json_body():
    """Parse the request JSON body. Missing/empty body -> empty dict.

    A body that is present but not a JSON object is malformed.
    """
    if request.method in ("POST", "PUT", "PATCH"):
        raw = request.get_data(cache=True, as_text=True)
        if raw is None or raw.strip() == "":
            return {}
        try:
            data = request.get_json(force=True, silent=False)
        except Exception:
            raise errors.invalid_request("Malformed JSON body")
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise errors.invalid_request("Request body must be a JSON object")
        return data
    return {}


def paginate(items):
    """Apply limit/offset pagination per PRD §2.3.

    limit defaults 10, min 1, max 100. offset defaults 0, min 0. Returns
    (page_items, limit, offset, total_count).
    """
    total_count = len(items)
    limit = _parse_int_param("limit", default=10, minimum=1, maximum=100)
    offset = _parse_int_param("offset", default=0, minimum=0, maximum=None)
    page = items[offset:offset + limit]
    return page, limit, offset, total_count


def _parse_int_param(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        val = int(raw)
    except (ValueError, TypeError):
        raise errors.invalid_request(f"Invalid {name} parameter")
    if minimum is not None and val < minimum:
        raise errors.invalid_request(f"{name} below minimum")
    if maximum is not None and val > maximum:
        raise errors.invalid_request(f"{name} above maximum")
    return val


def sort_by_created(items):
    """Sort by created_at ascending; _seq breaks ties (PRD §2.3)."""
    return sorted(items, key=lambda r: (r["created_at"], r["_seq"]))


# --- body field validators ----------------------------------------------------

def require_fields(body, names):
    for n in names:
        if n not in body or body[n] is None:
            raise errors.invalid_request(f"Missing required field: {n}")


def require_string(body, name):
    require_fields(body, [name])
    val = body[name]
    if not isinstance(val, str) or val.strip() == "":
        raise errors.invalid_request(f"Field {name} must be a non-empty string")
    return val


def require_int(body, name):
    require_fields(body, [name])
    val = body[name]
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request(f"Field {name} must be an integer")
    return val


def require_positive_int(body, name):
    val = require_int(body, name)
    if val <= 0:
        raise errors.invalid_request(f"Field {name} must be a positive integer")
    return val


def require_nonneg_int(body, name):
    val = require_int(body, name)
    if val < 0:
        raise errors.invalid_request(f"Field {name} must not be negative")
    return val


def optional_nonneg_int(body, name, default=0):
    if name not in body or body[name] is None:
        return default
    val = body[name]
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request(f"Field {name} must be an integer")
    if val < 0:
        raise errors.invalid_request(f"Field {name} must not be negative")
    return val


def optional_positive_int(body, name):
    """Optional integer that, when present, must be > 0. Returns None if absent."""
    if name not in body or body[name] is None:
        return None
    val = body[name]
    if isinstance(val, bool) or not isinstance(val, int):
        raise errors.invalid_request(f"Field {name} must be an integer")
    if val <= 0:
        raise errors.invalid_request(f"Field {name} must be a positive integer")
    return val


def require_enum(body, name, members):
    val = require_string(body, name)
    if val not in members:
        raise errors.invalid_request(f"Field {name} must be one of {sorted(members)}")
    return val


# --- logical clock / time arithmetic ------------------------------------------

def parse_iso8601(value):
    """Parse an ISO 8601 instant into a timezone-aware UTC datetime.

    Accepts a trailing 'Z' or an explicit offset. Naive values are treated as
    UTC. Raises ERR_INVALID_REQUEST on a malformed value.
    """
    if not isinstance(value, str) or value.strip() == "":
        raise errors.invalid_request("Invalid ISO 8601 timestamp")
    raw = value.strip()
    candidate = raw
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        dt = datetime.datetime.fromisoformat(candidate)
    except ValueError:
        raise errors.invalid_request("Invalid ISO 8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc)


def to_iso(dt):
    """Format a UTC datetime as ISO 8601 with three fractional digits + Z."""
    dt = dt.astimezone(datetime.timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def add_months(dt, months):
    """Add a whole number of calendar months to a datetime (clamping day)."""
    month_index = dt.month - 1 + months
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    # Clamp the day to the last valid day of the target month.
    day = min(dt.day, _days_in_month(year, month))
    return dt.replace(year=year, month=month, day=day)


def add_days(dt, days):
    return dt + datetime.timedelta(days=days)


def _days_in_month(year, month):
    if month == 12:
        nxt = datetime.date(year + 1, 1, 1)
    else:
        nxt = datetime.date(year, month + 1, 1)
    first = datetime.date(year, month, 1)
    return (nxt - first).days


def months_between(start_dt, end_dt):
    """Whole calendar months elapsed from start to end; never negative.

    Counts a month as complete only once the day-of-month (and time-of-day) has
    been reached, matching the "due = booking + N months" schedule semantics.
    """
    if start_dt is None or end_dt is None:
        return 0
    if end_dt <= start_dt:
        return 0
    months = (end_dt.year - start_dt.year) * 12 + (end_dt.month - start_dt.month)
    # If we have not yet reached the anniversary day/time within the final month,
    # back off by one whole month.
    anchor = add_months(start_dt, months)
    if anchor > end_dt:
        months -= 1
    if months < 0:
        months = 0
    return months
