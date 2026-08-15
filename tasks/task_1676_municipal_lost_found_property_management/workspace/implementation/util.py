"""Shared helpers: ids, timestamps, logical clock, decimal rounding (PRD 2.4/2.5/2.10)."""
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP


def new_id() -> str:
    """UUID with no type prefix (PRD 2.4)."""
    return str(uuid.uuid4())


def new_request_id() -> str:
    return "req_" + "".join(random.choices(string.ascii_uppercase + string.digits, k=20))


DEFAULT_CLOCK = "2026-08-01T00:00:00Z"


def parse_dt(s) -> datetime:
    """Parse an ISO 8601 datetime string; naive values are treated as UTC."""
    txt = str(s).strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_ms(dt) -> str:
    """ISO 8601 UTC with three fractional digits (PRD 2.2/2.4 timestamps)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def fmt_sec(dt) -> str:
    """ISO 8601 UTC at second precision (retention / SLA deadlines)."""
    dt = dt.astimezone(timezone.utc).replace(microsecond=0)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def fmt_auto(dt) -> str:
    """Normalized echo for client-supplied datetimes (found_at, starts_at, ...)."""
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return fmt_ms(dt)


class LogicalClock:
    """Server logical clock (PRD 2.5). Starts at 2026-08-01T00:00:00Z and never
    falls back to wall-clock time. Drives created_at/updated_at/released_at and
    every time-gated rule."""

    def __init__(self):
        self._dt = parse_dt(DEFAULT_CLOCK)

    def now(self) -> datetime:
        return self._dt

    def set(self, to_iso8601: str) -> datetime:
        self._dt = parse_dt(to_iso8601)
        return self._dt


CLOCK = LogicalClock()


def now_ms() -> str:
    """Server-stamped timestamp from the logical clock, three fractional digits."""
    return fmt_ms(CLOCK.now())


def round_half_up_cents(amount_cents: int, rate: str) -> int:
    """round_half_up(amount * rate) to whole cents using exact decimal math (PRD 2.10)."""
    return int(
        (Decimal(int(amount_cents)) * Decimal(rate)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )
