"""Logical clock, timestamps, ids, date/decimal helpers.

All temporal rules in the PRD are evaluated against a server-maintained logical
clock (PRD 2.4). The clock starts at exactly 2026-05-01T00:00:00Z and never
falls back to wall-clock time. Resource timestamps (created_at/updated_at) are
also stamped from the logical clock so desk behavior is deterministic; a global
monotonic sequence number breaks ties for creation-order sorting.
"""

import itertools
import random
import string
import uuid
from datetime import date, datetime, timedelta, timezone

from decimal import Decimal, ROUND_DOWN, ROUND_FLOOR, ROUND_HALF_UP, ROUND_UP, getcontext

getcontext().prec = 60

# ---------------------------------------------------------------------------
# logical clock
# ---------------------------------------------------------------------------

DEFAULT_CLOCK_ISO = "2026-05-01T00:00:00Z"
_clock_state = {"clock": None}


def parse_datetime_iso(s):
    """Parse an ISO-8601 datetime string into an aware UTC datetime."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date_iso(s):
    """Parse an ISO-8601 date string (YYYY-MM-DD) into a datetime.date."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    return date.fromisoformat(s.strip())


def _init_clock():
    _clock_state["clock"] = parse_datetime_iso(DEFAULT_CLOCK_ISO)


_init_clock()


def now_dt():
    return _clock_state["clock"]


def set_clock(dt):
    _clock_state["clock"] = dt


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-05-01T09:15:00.123Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def fmt_clock(dt):
    """Clock echo format: ISO 8601 UTC, trailing Z, no forced fractional part."""
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def now_iso():
    return fmt_ts(now_dt())


# ---------------------------------------------------------------------------
# ids / request ids
# ---------------------------------------------------------------------------

_seq_counter = itertools.count(1)


def next_seq():
    return next(_seq_counter)


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


# ---------------------------------------------------------------------------
# decimal helpers
# ---------------------------------------------------------------------------

D4 = Decimal("0.0001")
D1 = Decimal("1")


def D(x):
    """Decimal from an int/float/str without binary float noise."""
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


def round4_half_up(x):
    return D(x).quantize(D4, rounding=ROUND_HALF_UP)


def floor4(x):
    return D(x).quantize(D4, rounding=ROUND_FLOOR)


def floor_int(x):
    return int(D(x).to_integral_value(rounding=ROUND_FLOOR))


def round_half_up_cents(x):
    return int(D(x).quantize(D1, rounding=ROUND_HALF_UP))


def policy_round_cents(amount, policy):
    """Round a Decimal cent amount per the event fractional_policy (PRD 2.6)."""
    amount = D(amount)
    if policy == "ROUND_HALF_UP":
        return int(amount.quantize(D1, rounding=ROUND_HALF_UP))
    if policy == "ROUND_DOWN":
        return int(amount.quantize(D1, rounding=ROUND_DOWN))
    if policy == "ROUND_UP":
        return int(amount.quantize(D1, rounding=ROUND_UP))
    return int(amount.quantize(D1, rounding=ROUND_HALF_UP))


def q4(x):
    """Quantize a quantity to 4dp half-up and return it as a float for JSON/storage."""
    return float(round4_half_up(x))


def dec_of(x):
    """Decimal view of a stored quantity (float/int/Decimal)."""
    return D(x)


def date_plus_days(d, n):
    return d + timedelta(days=n)


def date_minus_days(d, n):
    return d - timedelta(days=n)


def midnight_utc(d):
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
