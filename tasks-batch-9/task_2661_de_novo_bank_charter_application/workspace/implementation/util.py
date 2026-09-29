"""Time, rounding and misc helpers.  All timestamps are timezone-aware UTC."""
import random
import re
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

UTC = timezone.utc

# The logical clock's startup value, per PRD 2.4.
CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2}):(\d{2})(\.\d{1,9})?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def wall_now():
    return datetime.now(UTC)


def iso_ms(dt):
    """ISO 8601 UTC with exactly three fractional digits (audit fields)."""
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def iso_clock(dt):
    """ISO 8601 UTC for domain datetimes; fractional part only when non-zero."""
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    if dt.microsecond == 0:
        return "%04d-%02d-%02dT%02d:%02d:%02dZ" % (
            dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        )
    return iso_ms(dt)


def parse_iso(value):
    """Parse an ISO 8601 datetime string.  Returns None when unparseable."""
    if not isinstance(value, str):
        return None
    m = _ISO_RE.match(value.strip())
    if not m:
        return None
    frac = m.group(7) or ""
    micro = 0
    if frac:
        digits = (frac[1:] + "000000")[:6]
        micro = int(digits)
    tz = m.group(8)
    try:
        naive = datetime(
            int(m.group(1)), int(m.group(2)), int(m.group(3)),
            int(m.group(4)), int(m.group(5)), int(m.group(6)), micro,
        )
    except ValueError:
        return None
    if tz in (None, "", "Z", "z"):
        return naive.replace(tzinfo=UTC)
    sign = 1 if tz[0] == "+" else -1
    body = tz[1:].replace(":", "")
    offset = timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
    return (naive - sign * offset).replace(tzinfo=UTC)


def round_half_up(value, places=0):
    """Decimal ROUND_HALF_UP to `places` decimal places."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    exp = Decimal(1).scaleb(-places)
    return value.quantize(exp, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(round_half_up(value, 0))


def floor_div(numerator, denominator):
    """Floor toward negative infinity on integers."""
    return numerator // denominator


def dec2(value):
    """A 2-decimal Decimal for scores / durations."""
    return round_half_up(value, 2)
