"""Numeric and datetime helpers."""

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

_QUANTS = {
    0: Decimal("1"),
    1: Decimal("0.1"),
    2: Decimal("0.01"),
    3: Decimal("0.001"),
    5: Decimal("0.00001"),
}


def D(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(repr(value))
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def q(value, places):
    """ROUND_HALF_UP quantize to `places` decimal digits."""
    return D(value).quantize(_QUANTS[places], rounding=ROUND_HALF_UP)


def decimal_places(value):
    exp = D(value).normalize().as_tuple().exponent
    if not isinstance(exp, int):
        return 0
    return max(0, -exp)


class Instant(datetime):
    """A UTC datetime that remembers the exact ISO 8601 text it was parsed from.

    A supplied instant is echoed back verbatim: the logical clock "echoes that
    instant back", and instants stamped from the clock (executed_at, closed_at,
    released_at) or supplied by the client (the MOP and load-bank windows) carry
    that same instant. Only the system-minted created_at / updated_at stamps are
    rendered with three fractional digits.
    """

    raw = None


def _as_instant(dt, raw):
    inst = Instant(
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
        dt.microsecond,
        tzinfo=dt.tzinfo,
    )
    inst.raw = raw
    return inst


def parse_iso(raw):
    """Parse an ISO 8601 UTC instant; returns an aware UTC datetime or None."""
    if not isinstance(raw, str):
        return None
    original = raw.strip()
    text = original
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    # Only a text that is already a UTC ("...Z") rendering may be echoed back
    # verbatim; anything else is re-rendered in canonical UTC form.
    echo = original if original.endswith("Z") else None
    return _as_instant(dt.astimezone(timezone.utc), echo)
