"""In-memory store, logical clock and temporal helpers.

Storage is process-local Python dicts only. Nothing is seeded, preloaded or
persisted to disk; a fresh process starts with a completely empty store and the
logical clock at its declared default.
"""
import re
import uuid
from datetime import datetime, date, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import g

DEFAULT_CLOCK_UTC = datetime(2026, 5, 1, 0, 0, 0, 0, tzinfo=timezone.utc)

TABLES = (
    "patients",
    "facilities",
    "payers",
    "navigators",
    "referrals",
    "episodes",
    "risk_assessments",
    "contact_attempts",
    "visits",
    "med_reconciliations",
    "discrepancies",
    "barriers",
    "red_flags",
    "readmissions",
    "claims",
    "handoffs",
)

DB = {name: {} for name in TABLES}

STATE = {
    "current_utc": DEFAULT_CLOCK_UTC,
    "holiday_dates": [],
    "seq": 0,
}


# --------------------------------------------------------------------------
# logical clock
# --------------------------------------------------------------------------
def now():
    return STATE["current_utc"]


def set_clock(dt):
    STATE["current_utc"] = dt


def holidays():
    return STATE["holiday_dates"]


def set_holidays(values):
    STATE["holiday_dates"] = list(values)


def next_seq():
    STATE["seq"] += 1
    return STATE["seq"]


def new_id():
    return str(uuid.uuid4())


# --------------------------------------------------------------------------
# instant / date formatting.
#
# PRD 2.4 + 2.5: every instant this API renders carries exactly three
# fractional-second digits and a trailing Z. Calendar dates are plain
# YYYY-MM-DD strings.
# --------------------------------------------------------------------------
_INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(\.\d{1,6})?(Z|z|[+-]\d{2}:?\d{2})$"
)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def fmt_instant(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
        dt.microsecond // 1000,
    )


def parse_instant(value):
    """Parse an ISO 8601 instant. Returns None when the value is not one."""
    if not isinstance(value, str):
        return None
    m = _INSTANT_RE.match(value.strip())
    if not m:
        return None
    frac = m.group(7) or ".0"
    micro = int(round(float(frac) * 1000000))
    tz = m.group(8)
    try:
        base = datetime(
            int(m.group(1)),
            int(m.group(2)),
            int(m.group(3)),
            int(m.group(4)),
            int(m.group(5)),
            int(m.group(6)),
            micro,
            tzinfo=timezone.utc,
        )
    except ValueError:
        return None
    if tz not in ("Z", "z"):
        sign = 1 if tz[0] == "+" else -1
        body = tz[1:].replace(":", "")
        offset = timedelta(hours=int(body[:2]), minutes=int(body[2:]))
        base = base - sign * offset
    return base


def parse_date(value):
    if not isinstance(value, str) or not _DATE_RE.match(value.strip()):
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def fmt_date(d):
    if d is None:
        return None
    return d.isoformat()


def end_of_day(date_str):
    """The instant a date-valued deadline expires: that date at T23:59:59.999Z."""
    d = date_str if isinstance(date_str, date) else parse_date(date_str)
    return datetime(d.year, d.month, d.day, 23, 59, 59, 999000, tzinfo=timezone.utc)


def add_days(date_str, days):
    d = date_str if isinstance(date_str, date) else parse_date(date_str)
    return (d + timedelta(days=days)).isoformat()


def day_diff(later_str, earlier_str):
    a = parse_date(later_str)
    b = parse_date(earlier_str)
    return (a - b).days


def current_date_str():
    return now().astimezone(timezone.utc).date().isoformat()


# --------------------------------------------------------------------------
# business-day arithmetic
# --------------------------------------------------------------------------
def is_business_day(d):
    """Monday..Friday and not in the programme-wide holiday set."""
    if d.weekday() > 4:
        return False
    return d.isoformat() not in STATE["holiday_dates"]


def walk_business_days(start_date_str, n):
    """Walk forward from start_date one calendar day at a time.

    The start date itself is day 0 and never counts.
    """
    d = parse_date(start_date_str)
    remaining = n
    while remaining > 0:
        d = d + timedelta(days=1)
        if is_business_day(d):
            remaining -= 1
    return d.isoformat()


# --------------------------------------------------------------------------
# rounding
# --------------------------------------------------------------------------
def round_half_up(value):
    """Round a Decimal/number half up (away from zero) to a whole number."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def dec(value):
    return Decimal(str(value))


# --------------------------------------------------------------------------
# row lifecycle
# --------------------------------------------------------------------------
def new_row(table, fields):
    row = {"id": new_id()}
    row.update(fields)
    row["created_at"] = now()
    row["updated_at"] = now()
    row["version"] = 1
    row["_seq"] = next_seq()
    DB[table][row["id"]] = row
    # A row created by this request is already at version 1; further writes to
    # it inside the same request must not advance it past 1.
    try:
        seen = getattr(g, "_touched", None)
        if seen is None:
            seen = set()
            g._touched = seen
        seen.add(row["id"])
    except RuntimeError:
        pass
    return row


def touch(row):
    """Bump updated_at and version once per row per request.

    PRD 2.5: version increments by exactly 1 on every mutation of the row. A
    single request is a single mutation, so a row touched several times while
    one request runs advances its version by exactly one.
    """
    try:
        seen = g._touched
    except (AttributeError, RuntimeError):
        seen = None
    if seen is None:
        seen = set()
        try:
            g._touched = seen
        except RuntimeError:
            pass
    key = row["id"]
    if key not in seen:
        row["version"] = row.get("version", 1) + 1
        seen.add(key)
    row["updated_at"] = now()
    return row


def serialize(row):
    """Public projection of a stored row: private keys dropped, instants formatted."""
    out = {}
    for key, value in row.items():
        if key.startswith("_"):
            continue
        out[key] = fmt_instant(value) if isinstance(value, datetime) else value
    return out


def sorted_rows(table, predicate=None):
    """List rows ordered by created_at ascending, insertion order breaking ties."""
    rows = [r for r in DB[table].values() if predicate is None or predicate(r)]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rows
