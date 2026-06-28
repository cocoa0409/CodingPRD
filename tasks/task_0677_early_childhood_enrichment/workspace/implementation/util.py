"""Shared low-level helpers: id minting, ISO time formatting/parsing, money
rounding, request-body access, calendar-month age math.

Kept dependency-light (only flask.request + errors) so other modules can import
freely without cycles.
"""
import uuid
from datetime import datetime, timezone, date
from decimal import Decimal, ROUND_HALF_UP

from flask import request

import errors


def new_id():
    """Server-minted UUID with no type prefix (PRD 2.4)."""
    return str(uuid.uuid4())


def iso_ms(dt):
    """ISO 8601 UTC timestamp with exactly three fractional digits (PRD 2.4)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_instant(value):
    """Parse an ISO 8601 UTC instant. Raises ERR_INVALID_REQUEST on failure.

    Accepts a trailing 'Z' or explicit offset. Returns a tz-aware UTC datetime.
    """
    if not isinstance(value, str) or not value:
        raise errors.err(errors.ERR_INVALID_REQUEST, "Invalid timestamp")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise errors.err(errors.ERR_INVALID_REQUEST, "Invalid timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Parse an ISO 8601 calendar date YYYY-MM-DD. Raises ERR_INVALID_REQUEST."""
    if not isinstance(value, str) or not value:
        raise errors.err(errors.ERR_INVALID_REQUEST, "Invalid date")
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        raise errors.err(errors.ERR_INVALID_REQUEST, "Invalid date")


def round_half_up(value):
    """Round a numeric/Decimal to a whole integer using round-half-up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def get_body():
    """Return the JSON body as a dict (empty dict if none/empty)."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        raise errors.err(errors.ERR_INVALID_REQUEST, "Malformed JSON body")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Request body must be an object")
    return body


def months_between(birth_d, instant_dt):
    """Whole calendar-month age at an instant (PRD 3.9 / calc child_age_months).

    Floor of the calendar-month difference between the session start instant and
    the child's birth date. The day-of-month component decides whether the final
    partial month counts: a child has reached N whole months only once the day of
    the month has rolled past (or equalled) their birth day.
    """
    instant_date = instant_dt.astimezone(timezone.utc).date()
    months = (instant_date.year - birth_d.year) * 12 + (instant_date.month - birth_d.month)
    if instant_date.day < birth_d.day:
        months -= 1
    return months
