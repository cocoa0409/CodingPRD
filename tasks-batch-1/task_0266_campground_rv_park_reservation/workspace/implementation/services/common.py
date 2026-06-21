"""Shared helpers: rounding, date parsing, common system-field management."""
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from db import now_iso_ms, store
import errors

WEEK_NIGHTS = 7
MONTH_NIGHTS = 28


def round_half_up(value):
    """Round a numeric value to the nearest whole cent, half-up (PRD §2.5)."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def parse_date(s):
    """Parse a YYYY-MM-DD date string; raise ERR_INVALID_REQUEST on failure."""
    if not isinstance(s, str):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Date must be a string")
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Unparseable date: %r" % s)


def clock_date():
    """Current clock date (UTC) from the deterministic test clock."""
    return store.clock.astimezone(timezone.utc).date()


def touch(rec):
    """Refresh updated_at and bump version on a mutated common-fields record."""
    rec["updated_at"] = now_iso_ms()
    rec["version"] = rec.get("version", 1) + 1


def stamp_common(rec):
    """Set created_at/updated_at/version on a freshly created common-fields record."""
    ts = now_iso_ms()
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    rec["_seq"] = store.next_seq()
    return rec
