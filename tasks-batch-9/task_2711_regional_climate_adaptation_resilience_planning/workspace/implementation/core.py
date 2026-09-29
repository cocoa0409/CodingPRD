"""Logical clock, decimal discipline and identity helpers (PRD 2.4 and 2.6)."""

import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR, getcontext

# Money is integer cents and shares are basis points, but the intermediate
# arithmetic (annuity factors, consequence scores) needs plenty of headroom.
getcontext().prec = 60

EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

ONE = Decimal(1)
ZERO = Decimal(0)
TEN_K = Decimal(10000)


class LogicalClock:
    """The clock starts at 2026-08-01T00:00:00Z and never advances on its own."""

    def __init__(self):
        self._now = EPOCH

    def now(self):
        return self._now

    def set(self, moment):
        self._now = moment
        return self._now

    def reset(self):
        self._now = EPOCH


clock = LogicalClock()


def new_id():
    """Server-minted UUID with no type prefix and no embedded semantics."""
    return str(uuid.uuid4())


_ALNUM = string.ascii_uppercase + string.digits


def new_request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def iso(moment):
    """ISO 8601 UTC instant with exactly three fractional digits."""
    if moment is None:
        return None
    moment = moment.astimezone(timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (moment.microsecond // 1000)


def parse_iso(text):
    """Parse an ISO 8601 instant; returns None when the value is unusable."""
    if not isinstance(text, str):
        return None
    raw = text.strip()
    if not raw:
        return None
    if raw.endswith(("Z", "z")):
        raw = raw[:-1] + "+00:00"
    try:
        moment = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def hours(count):
    return timedelta(hours=count)


# ---------------------------------------------------------------------------
# Decimal discipline (PRD 2.6)
# ---------------------------------------------------------------------------

def dec(value):
    """Exact Decimal from an int / Decimal / float-shaped JSON number."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


_QUANT = {
    0: Decimal("1"),
    2: Decimal("0.01"),
    4: Decimal("0.0001"),
}


def round_half_up(value, places=0):
    """Magnitudes round half up: exactly halfway rounds away from zero."""
    quant = _QUANT.get(places)
    if quant is None:
        quant = Decimal(1).scaleb(-places)
    return dec(value).quantize(quant, rounding=ROUND_HALF_UP)


def cents(value):
    """Money computed from a rate is rounded half up to whole cents."""
    return int(round_half_up(value, 0))


def floor_int(value):
    """Shares in basis points are always floored, never rounded up."""
    return int(dec(value).to_integral_value(rounding=ROUND_FLOOR))


def bps_share(numerator, denominator):
    """floor(10000 * numerator / denominator), 0 when the denominator is 0."""
    if denominator is None or denominator == 0:
        return 0
    return floor_int(TEN_K * dec(numerator) / dec(denominator))


def as_number(value):
    """JSON rendering for Decimal-valued fields."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value
