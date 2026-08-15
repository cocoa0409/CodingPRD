"""Shared helpers: ids, timestamps, the logical clock, decimal rounding."""
import random
import string
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, localcontext


def new_id() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return "req_" + suffix


def _fmt_ms(dt: datetime) -> str:
    """ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_ts() -> str:
    """Wall-clock timestamp for meta.api_request_timestamp (not the logical clock)."""
    return _fmt_ms(datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Logical clock (PRD 2.4): starts at exactly 2026-08-01T00:00:00Z and advances
# only via POST /_clock/set_current_utc. All server-stamped entity timestamps
# read this clock.
# ---------------------------------------------------------------------------

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"


def parse_dt(s: str) -> datetime:
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class LogicalClock:
    def __init__(self):
        self._dt = parse_dt(DEFAULT_CLOCK)

    def now(self) -> datetime:
        return self._dt

    def now_iso(self) -> str:
        return _fmt_ms(self._dt)

    def today(self) -> date:
        return self._dt.date()

    def set(self, to_iso8601: str) -> datetime:
        new_dt = parse_dt(to_iso8601)
        if new_dt < self._dt:
            from errors import raise_error, ERR_INVALID_REQUEST
            raise_error(ERR_INVALID_REQUEST,
                        "to_iso8601 is before the current logical time; the clock only advances")
        self._dt = new_dt
        return self._dt


CLOCK = LogicalClock()


def parse_date(s: str) -> date:
    return date.fromisoformat(s.strip())


# ---------------------------------------------------------------------------
# Decimal rounding helpers (PRD 2.6 — round-half-up everywhere; never banker's)
# ---------------------------------------------------------------------------

def to_decimal(v) -> Decimal:
    """Exact decimal view of a JSON number (floats recover their literal)."""
    if isinstance(v, Decimal):
        return v
    if isinstance(v, bool):
        raise TypeError("bool is not numeric")
    if isinstance(v, int):
        return Decimal(v)
    return Decimal(str(v))


def round_half_up(value, places: int) -> Decimal:
    q = Decimal(1).scaleb(-places)  # 10^-places
    with localcontext() as ctx:
        ctx.prec = 50
        return to_decimal(value).quantize(q, rounding=ROUND_HALF_UP)


def ratio_round_half_up(numer, denom, places: int) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = 50
        return (Decimal(numer) / Decimal(denom)).quantize(
            Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def round_to_half_step(value) -> Decimal:
    """Round to the nearest 0.5 step, round-half-up (11.26 -> 11.5, 11.24 -> 11.0)."""
    with localcontext() as ctx:
        ctx.prec = 50
        doubled = (to_decimal(value) * 2).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        return doubled / 2


def num(v: Decimal) -> float:
    """Store a Decimal result as a plain JSON float."""
    return float(v)
