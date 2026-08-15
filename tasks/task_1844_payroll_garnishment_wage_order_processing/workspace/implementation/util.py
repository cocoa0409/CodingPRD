"""Time, date, and decimal helpers.

All business timestamps read from the logical clock (db.store.clock), never
from the wall clock. The wall clock is used only for the envelope's
api_request_timestamp, which drives no deadline or ordering decision.
"""

import re
import secrets
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

_ISO_INSTANT = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})"
    r"[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.(\d{1,9}))?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)
_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def new_uuid():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + secrets.token_hex(12)


def parse_instant(text):
    """Parse an ISO 8601 instant into a naive UTC datetime, or None."""
    if not isinstance(text, str):
        return None
    m = _ISO_INSTANT.match(text.strip())
    if not m:
        return None
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    offset = m.group(8)
    try:
        dt = datetime(year, month, day, hour, minute, second, micro)
    except ValueError:
        return None
    if offset and offset not in ("Z", "z"):
        sign = 1 if offset[0] == "+" else -1
        body = offset[1:].replace(":", "")
        dt = dt - timedelta(hours=int(body[:2]) * sign, minutes=int(body[2:4]) * sign)
    return dt


def parse_date(text):
    """Parse a plain YYYY-MM-DD calendar date, or None when malformed."""
    if not isinstance(text, str):
        return None
    m = _ISO_DATE.match(text.strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def render_instant(dt):
    """Canonical server instant: YYYY-MM-DDTHH:MM:SS.mmmZ (three digits)."""
    if dt is None:
        return None
    return "{:04d}-{:02d}-{:02d}T{:02d}:{:02d}:{:02d}.{:03d}Z".format(
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def render_date(d):
    if isinstance(d, str):
        return d
    if d is None:
        return None
    return "{:04d}-{:02d}-{:02d}".format(d.year, d.month, d.day)


def wall_now_iso():
    """Wall-clock timestamp for the response envelope meta only."""
    return render_instant(datetime.now(timezone.utc).replace(tzinfo=None))


def add_business_days(d, n):
    """Advance date d by n business days, skipping Saturdays and Sundays.

    n == 0 returns d unchanged, whatever weekday it is (SAME_DAY variant).
    """
    cur = d
    remaining = n
    while remaining > 0:
        cur = cur + timedelta(days=1)
        if cur.weekday() < 5:  # Monday..Friday
            remaining -= 1
    return cur


def rhu(value):
    """Round a Decimal to whole cents, half-up, exactly once."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# Federal minimum wage, cents per hour (calc constant).
FEDERAL_MINIMUM_WAGE_CENTS = 725

# Pay-frequency normalization factors for the weekly floor.
PERIOD_WEEKS = {
    "WEEKLY": Decimal("1"),
    "BIWEEKLY": Decimal("2"),
    "SEMIMONTHLY": Decimal("2.1667"),
    "MONTHLY": Decimal("4.3333"),
}

ANSWER_SLA_DAYS = 10        # business days
NOTIFICATION_SLA_DAYS = 7   # calendar days
MAX_SUSPENSIONS = 3
