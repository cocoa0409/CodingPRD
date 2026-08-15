"""Date/decimal helpers (PRD §2.6)."""
import calendar
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from db import store


def new_id():
    return str(uuid.uuid4())


def round2(x):
    """Round to 2 decimal places, round-half-up. Accepts int/float/str/Decimal."""
    if not isinstance(x, Decimal):
        x = Decimal(str(x))
    return x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def round0(x):
    """Round to whole integer, round-half-up. Returns int."""
    if not isinstance(x, Decimal):
        x = Decimal(str(x))
    return int(x.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def dec(x):
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


def num_out(x):
    """Serialize a Decimal/number as a JSON number (float)."""
    if isinstance(x, Decimal):
        return float(x)
    return x


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def parse_instant(s):
    """Parse an ISO 8601 instant into an aware UTC datetime, or None."""
    if not isinstance(s, str):
        return None
    t = s.strip()
    try:
        if t.endswith("Z") or t.endswith("z"):
            t = t[:-1] + "+00:00"
        dt = datetime.fromisoformat(t)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(s):
    """Parse an ISO calendar date, or None."""
    if not isinstance(s, str):
        return None
    t = s.strip()
    try:
        return date.fromisoformat(t)
    except ValueError:
        return None


def fmt_instant_ms(dt):
    """ISO 8601 UTC with three fractional digits (created_at / updated_at)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def fmt_instant(dt):
    """Canonical instant: seconds when whole, else 3 fractional digits."""
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return fmt_instant_ms(dt)


def fmt_date(d):
    return d.isoformat()


def clock_now():
    return store.clock


def clock_date():
    return store.clock.date()


def created_now():
    return fmt_instant_ms(store.clock)


def touch(entity):
    """Version bump + updated_at refresh (PRD §2.5/§2.10)."""
    entity["version"] = entity.get("version", 1) + 1
    entity["updated_at"] = created_now()


def add_months(d, months):
    """Add months to a date; clamp the day to the target month's last day."""
    m = d.month - 1 + months
    y = d.year + m // 12
    m = m % 12 + 1
    last = calendar.monthrange(y, m)[1]
    return date(y, m, min(d.day, last))
