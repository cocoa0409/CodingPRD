"""Body/field validation helpers and date/time arithmetic.

All ERR_INVALID_REQUEST (422) faults for well-formedness flow through here.
"""
from datetime import date, datetime, timedelta, timezone

from errors import err

# Days are whole-day date arithmetic; years are calendar-year offsets that
# preserve month/day (Feb 29 -> Feb 28 fallback).


def bad_request(message):
    return err("ERR_INVALID_REQUEST", message)


def require_dict(body):
    if not isinstance(body, dict):
        raise bad_request("Request body must be a JSON object.")
    return body


def get_required(body, field):
    if field not in body or body[field] is None:
        raise bad_request(f"Missing required field: {field}.")
    return body[field]


def as_int(value, field, minimum=None, maximum=None):
    # Reject bools (they are int subclass) and non-integers.
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad_request(f"Field {field} must be an integer.")
    if minimum is not None and value < minimum:
        raise bad_request(f"Field {field} must be >= {minimum}.")
    if maximum is not None and value > maximum:
        raise bad_request(f"Field {field} must be <= {maximum}.")
    return value


def as_str(value, field, non_empty=False):
    if not isinstance(value, str):
        raise bad_request(f"Field {field} must be a string.")
    if non_empty and value.strip() == "":
        raise bad_request(f"Field {field} must be non-empty.")
    return value


def as_bool(value, field):
    if not isinstance(value, bool):
        raise bad_request(f"Field {field} must be a boolean.")
    return value


def as_enum(value, field, allowed):
    if value not in allowed:
        raise bad_request(f"Field {field} must be one of {sorted(allowed)}.")
    return value


def parse_date(value, field, must_be_past=False):
    s = as_str(value, field)
    try:
        d = date.fromisoformat(s)
    except (ValueError, TypeError):
        raise bad_request(f"Field {field} must be a valid ISO 8601 date (YYYY-MM-DD).")
    if must_be_past and d >= datetime.now(timezone.utc).date():
        raise bad_request(f"Field {field} must be a date in the past.")
    return d


def parse_datetime(value, field):
    s = as_str(value, field)
    text = s
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except (ValueError, TypeError):
        raise bad_request(f"Field {field} must be a valid ISO 8601 datetime.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---- date arithmetic helpers ----

def add_days(d, days):
    return d + timedelta(days=days)


def add_years(d, years):
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        # Feb 29 -> Feb 28 on a non-leap target year.
        return d.replace(year=d.year + years, day=28)


def add_months(d, months):
    total = (d.month - 1) + months
    year = d.year + total // 12
    month = total % 12 + 1
    # Clamp day to month length.
    day = d.day
    while True:
        try:
            return date(year, month, day)
        except ValueError:
            day -= 1


def iso_date(d):
    return d.isoformat()
