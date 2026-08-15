"""Shared utilities: time parsing, date arithmetic, UUID generation."""
import re
import uuid
from datetime import datetime, timezone, timedelta


def new_uuid():
    return str(uuid.uuid4())


_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$"
)


def parse_iso(s):
    """Parse an ISO-8601 datetime string to an aware UTC datetime.

    Returns None on parse failure.
    """
    if not isinstance(s, str):
        return None
    m = _ISO_RE.match(s.strip())
    if not m:
        return None
    try:
        year, month, day, hh, mm, ss = (
            int(m.group(1)),
            int(m.group(2)),
            int(m.group(3)),
            int(m.group(4)),
            int(m.group(5)),
            int(m.group(6)),
        )
        frac = m.group(7) or ""
        micro = 0
        if frac:
            digits = frac[1:]
            digits = (digits + "000000")[:6]
            micro = int(digits)
        tzoff = m.group(8) or "Z"
        if tzoff == "Z" or tzoff == "":
            tz = timezone.utc
        else:
            sign = 1 if tzoff[0] == "+" else -1
            rest = tzoff[1:].replace(":", "")
            oh = int(rest[:2])
            om = int(rest[2:4]) if len(rest) >= 4 else 0
            tz = timezone(sign * timedelta(hours=oh, minutes=om))
        dt = datetime(year, month, day, hh, mm, ss, micro, tzinfo=tz)
        return dt.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None


def to_iso_ms(dt):
    """Format an aware UTC datetime as ISO-8601 with three fractional digits and Z."""
    s = dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    ms = dt.microsecond // 1000
    return f"{s}.{ms:03d}Z"


def add_months(dt, months):
    """Add an integer number of months to a datetime (calendar-aware)."""
    month_index = dt.month - 1 + months
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    # Clamp day to days-in-month
    day = dt.day
    while True:
        try:
            return dt.replace(year=year, month=month, day=day)
        except ValueError:
            day -= 1
            if day < 1:
                raise


def add_days(dt, days):
    return dt + timedelta(days=days)


def ceil_sqrt(n):
    """Ceiling of integer square root."""
    if n < 0:
        raise ValueError("n must be non-negative")
    r = int(n ** 0.5)
    # Correct for floating point error on large n
    while (r + 1) * (r + 1) <= n:
        r += 1
    while r * r > n:
        r -= 1
    if r * r == n:
        return r
    return r + 1
