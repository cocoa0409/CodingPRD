"""Timestamp / datetime helpers.

Two clocks live in this system and they must never be confused:

* real wall-clock time — used only for the audit fields (`created_at`,
  `updated_at`) and for `meta.api_request_timestamp`;
* the logical plant clock (PRD §2.4) — used for every business decision:
  `released_at`, `held_at`, `confirmed_at`, `applied_at`, `delivered_at`,
  reservation expiry, warranty windows and the ops-run sweep.
"""

import calendar
from datetime import datetime, timedelta, timezone


def now_iso():
    """Real UTC wall-clock time, ISO 8601 with exactly three fractional digits."""
    d = datetime.now(timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (d.microsecond // 1000)


def iso_ms(d):
    """Canonical ISO 8601 UTC rendering with three fractional digits."""
    d = d.astimezone(timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (d.microsecond // 1000)


def parse_dt(value):
    """Parse an ISO 8601 instant; returns an aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def format_like(template_raw, value):
    """Render `value` using the same textual style as `template_raw`.

    Datetimes the client supplied are echoed back verbatim; datetimes derived
    from them (a deferred warranty start, a warranty end date) are rendered in
    the same style so that arithmetic stays legible to the caller.
    """
    if not isinstance(template_raw, str) or not template_raw.strip():
        return iso_ms(value)
    template = template_raw.strip()
    value = value.astimezone(timezone.utc)
    text = value.strftime("%Y-%m-%dT%H:%M:%S")
    if "." in template:
        text += ".%03d" % (value.microsecond // 1000)
    if template.endswith(("Z", "z")):
        text += "Z"
    else:
        text += "+00:00"
    return text


def add_days(value, days):
    return value + timedelta(days=int(days))


def add_months(value, months):
    """Add whole calendar months, keeping the day of month, clamping down."""
    months = int(months)
    total = value.month - 1 + months
    year = value.year + total // 12
    month = total % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)
