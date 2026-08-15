"""Dates, timestamps, decimals, ids. All timestamps derive from the logical clock."""
import re
import uuid
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

import db

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def new_id():
    return str(uuid.uuid4())


def now_dt():
    """Current logical-clock instant (aware UTC)."""
    return db.get_clock()


def now_iso():
    """ISO 8601 UTC timestamp with three fractional digits, from the logical clock."""
    return iso_ms(now_dt())


def iso_ms(dt):
    dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % ms


def iso_instant(dt):
    """Clock echo format: whole-second instants print without a fractional part."""
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return iso_ms(dt)


def today():
    """Current logical date (UTC date part of the clock instant)."""
    return now_dt().astimezone(timezone.utc).date()


def today_str():
    return today().isoformat()


def parse_date(value):
    """Strict YYYY-MM-DD -> date, or None."""
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def is_date_str(value):
    return parse_date(value) is not None


def parse_instant(value):
    """ISO 8601 instant -> aware UTC datetime, or None. Date-only = midnight UTC."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    try:
        if _DATE_RE.match(text):
            return datetime.combine(
                datetime.strptime(text, "%Y-%m-%d").date(), time(0, 0), timezone.utc
            )
        dt = datetime.fromisoformat(text.replace("Z", "+00:00").replace("z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def midnight_utc(date_str):
    """Midnight UTC instant of an ISO date string (assumed valid)."""
    d = parse_date(date_str)
    return datetime.combine(d, time(0, 0), timezone.utc)


def logical_after(date_str):
    """True when the current logical instant is 'after' the given ISO date.

    PRD §2.9: a logical instant after midnight of a date counts as after that date.
    """
    return now_dt() > midnight_utc(date_str)


def add_days_str(date_str, days):
    """ISO date + N days -> ISO date string."""
    d = parse_date(date_str)
    return (d + timedelta(days=days)).isoformat()


def age_days(placed_date_str):
    """Whole days between placed_date and the current logical date."""
    return (today() - parse_date(placed_date_str)).days


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


# ------------------------------------------------------------------ decimals
def d4(value):
    """Stored 4dp JSON number -> exact Decimal."""
    if value is None:
        return None
    return Decimal(str(value))


def q4(value):
    """Quantize a Decimal to 4 decimal places, round-half-up."""
    return value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def round4_div(numer, denom):
    """round(numer/denom, 4) half-up -> Decimal."""
    return q4(Decimal(numer) / Decimal(denom))


def num4(value):
    """Serialize a 4dp Decimal as a JSON number."""
    return float(q4(value))


def round_cents(value):
    """Round a Decimal amount to whole cents, half-up -> int."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ------------------------------------------------------------------ records
def make_record(fields):
    """Attach the common system fields (PRD §2.4) to a new record."""
    ts = now_iso()
    rec = dict(fields)
    rec["id"] = new_id()
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    rec["_seq"] = db.next_seq()
    return rec


def pub(rec):
    """Public view of a record (internal keys stripped)."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def created_order(records):
    """created_at ascending, insertion order breaking ties (PRD §2.3)."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
