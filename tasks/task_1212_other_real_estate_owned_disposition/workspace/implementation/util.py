import random
import string
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

import db

CENT = Decimal("0.01")
FOUR_DP = Decimal("0.0001")


def new_id():
    return str(uuid.uuid4())


def req_id(n=20):
    return "req_" + "".join(random.choice(string.ascii_letters + string.digits) for _ in range(n))


def iso3(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    """Server timestamps follow the logical clock (platform never uses wall-clock)."""
    return iso3(db.clock)


def q2(x):
    return Decimal(x).quantize(CENT, rounding=ROUND_HALF_UP)


def q4(x):
    return Decimal(x).quantize(FOUR_DP, rounding=ROUND_HALF_UP)


def to_decimal(v):
    if isinstance(v, bool):
        raise ValueError("boolean is not a number")
    if isinstance(v, (int, float)):
        return Decimal(str(v))
    if isinstance(v, Decimal):
        return v
    raise ValueError("not a number")


def money_out(x):
    return float(x) if x is not None else None


def parse_date(s):
    """Parse an ISO 8601 date or datetime. Returns (aware UTC datetime, date_only flag)."""
    if not isinstance(s, str):
        raise ValueError("date must be a string")
    t = s.strip()
    if len(t) == 10 and t[4] == "-" and t[7] == "-":
        d = datetime.strptime(t, "%Y-%m-%d")
        return d.replace(tzinfo=timezone.utc), True
    iso = t[:-1] + "+00:00" if t.endswith("Z") else t
    d = datetime.fromisoformat(iso)
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc), False


def pdate(s):
    return parse_date(s)[0]


def is_date_only(s):
    return parse_date(s)[1]


def render_derived(dt, date_only):
    """Render a computed date mirroring the granularity of its source input."""
    if date_only:
        return dt.strftime("%Y-%m-%d")
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
