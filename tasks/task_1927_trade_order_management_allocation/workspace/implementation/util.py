"""Shared helpers: ids, timestamps, exact-decimal math, datetime parsing."""
import secrets
import string
import uuid
from datetime import date, datetime, timezone
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal

_ONE = Decimal("1")


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(20))


def wall_now_iso():
    """Wall-clock UTC, ISO 8601 with three fractional digits (created_at /
    updated_at / meta timestamps)."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def parse_dt(s):
    """Parse an ISO 8601 datetime string to an aware datetime; None if invalid."""
    if not isinstance(s, str):
        return None
    t = s.strip()
    if not t:
        return None
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def parse_date(s):
    """Parse an ISO calendar date string; None if invalid."""
    if not isinstance(s, str):
        return None
    t = s.strip()
    if not t:
        return None
    try:
        return date.fromisoformat(t)
    except ValueError:
        return None


def render_date(d):
    return d.isoformat()


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def rhu_int(d):
    """Round a Decimal half-up to an integer."""
    return int(d.quantize(_ONE, rounding=ROUND_HALF_UP))


def vwap_cents(pairs):
    """Volume-weighted average price in integer cents (round half up after an
    exact-decimal division). pairs: iterable of (qty, price_cents). None when
    total qty is zero."""
    pairs = list(pairs)
    total_q = sum(q for q, _ in pairs)
    if total_q <= 0:
        return None
    num = sum(Decimal(q) * Decimal(p) for q, p in pairs)
    return rhu_int(num / Decimal(total_q))


def commission_cents(qty, price_cents, rate_bp):
    """Per-line commission: round_half_up(qty * price * rate_bp / 10000)."""
    return rhu_int(Decimal(qty) * Decimal(price_cents) * Decimal(str(rate_bp)) / Decimal(10000))


def public(rec):
    """Strip internal keys (prefixed with '_') from a stored record."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}
