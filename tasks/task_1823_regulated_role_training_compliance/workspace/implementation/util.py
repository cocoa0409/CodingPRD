"""Time, decimal, and calendar helpers. All timestamps are logical-clock UTC."""
from calendar import monthrange
from datetime import datetime, timedelta, timezone

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

UTC = timezone.utc
DAY = 86400  # seconds


def parse_dt(value):
    """Parse an ISO-8601 string into an aware UTC datetime; None on failure."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def fmt_dt(dt):
    """Format an aware UTC datetime as ISO-8601 with exactly 3 fractional digits and Z."""
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % ms


def add_months(dt, months):
    """Add calendar months, clamping the day-of-month to the target month's last day."""
    total = dt.year * 12 + (dt.month - 1) + months
    y, mo = divmod(total, 12)
    mo += 1
    last = monthrange(y, mo)[1]
    return dt.replace(year=y, month=mo, day=min(dt.day, last))


def add_years(dt, years):
    return add_months(dt, years * 12)


def add_business_days(d0, n):
    """Count n Mon..Fri days starting the day AFTER date(d0); result carries d0's UTC time-of-day."""
    d = d0.date()
    count = 0
    while count < n:
        d += timedelta(days=1)
        if d.weekday() < 5:  # Monday=0 .. Friday=4
            count += 1
    return datetime(d.year, d.month, d.day, d0.hour, d0.minute, d0.second,
                    d0.microsecond, tzinfo=UTC)


def parse_decimal(value, min_v=None, max_v=None, max_dp=None):
    """Parse a JSON number into Decimal with range/decimal-place checks. None on failure."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        d = Decimal(str(value).strip() if isinstance(value, str) else str(value))
    except (InvalidOperation, ValueError):
        return None
    if d.is_nan() or d.is_infinite():
        return None
    if max_dp is not None:
        q = Decimal(1).scaleb(-max_dp)
        try:
            if d != d.quantize(q, rounding=ROUND_HALF_UP):
                return None
        except InvalidOperation:
            return None
    if min_v is not None and d < Decimal(str(min_v)):
        return None
    if max_v is not None and d > Decimal(str(max_v)):
        return None
    return d


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def round2(d):
    """Round a Decimal half-up to 2 decimal places."""
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def pct2(numerator, denominator):
    """100 * num / den rounded half-up to 2dp; 0.00 when den == 0."""
    if not denominator:
        return Decimal("0.00")
    return round2(Decimal(100) * Decimal(numerator) / Decimal(denominator))
