"""Instants and rounding.

=============================================================================
G2 / ONE RENDER FUNCTION -- the three-case timestamp policy
=============================================================================
Every instant in the system is carried as a `TS` value: an aware UTC
`datetime` plus the exact string that must be rendered for it.  `render()` is
the single render function -- it returns `ts.s` and nothing else ever formats
an instant.  A TS is minted in exactly one of three ways:

  case A -- CANONICAL SERVER-MINTED.  `ts_canonical(dt)` renders
    `YYYY-MM-DDTHH:MM:SS.mmmZ`, three fractional digits, always.  Used for
    `created_at`, `updated_at` and `meta.api_request_timestamp`, because
    PRD 2.4 mandates "ISO 8601 UTC with three fractional digits" for them.

  case B -- CALLER-SUPPLIED ECHO.  `ts_input(s)` keeps the caller's string
    byte-verbatim.  Used for every datetime that arrives in a request body
    (`opens_at`, `order_cutoff_at`, `production_date`, `handoff_date`,
    `handoff_window_end_at`, `received_at`, `expires_at`,
    `payout_period_start`) and for the logical clock's own `to_iso8601`.
    A `Z` is never normalised to `.000Z`, nor the reverse.

  case C -- DERIVED.  `ts_shift(base, delta)` renders the shifted instant in
    the *style of its source string*: the same number of fractional digits and
    the same `Z` suffix the source used.  Used for `hold_expires_at`
    (placed_at + 45m), `pickup_forfeit_at` (handoff_window_end_at + 90m),
    `skip_deadline_at` (order_cutoff_at - 24h), `review_window_closes_at`
    (fulfilled_at + 21d), `MoneyMovement.expires_at` (created_at + 365d) and
    the extended `order_cutoff_at` (now + 120m).
    Instants that ARE the logical clock -- `placed_at`, `fulfilled_at`,
    `responded_at`, `dispatched_at`, `past_due_since` -- are case C with a
    zero delta, i.e. they echo the clock's own string byte-verbatim.

Comparisons never touch the strings: `cmp_instants` compares `.dt` truncated
to whole seconds, because PRD 2.4 fixes "instant comparisons are made at
second granularity".
"""

import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(\.\d{1,9})?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


class TS:
    """An instant plus the exact string it renders as."""

    __slots__ = ("dt", "s")

    def __init__(self, dt, s):
        self.dt = dt
        self.s = s

    def __repr__(self):  # pragma: no cover - debugging aid
        return "TS(%s)" % self.s


def parse_dt(raw):
    """Parse an ISO-8601 instant string to an aware UTC datetime, or None."""
    if not isinstance(raw, str):
        return None
    m = _ISO_RE.match(raw.strip())
    if not m:
        return None
    year, month, day, hour, minute, sec, frac, off = m.groups()
    try:
        micro = 0
        if frac:
            digits = (frac[1:] + "000000")[:6]
            micro = int(digits)
        dt = datetime(
            int(year), int(month), int(day), int(hour), int(minute),
            int(sec or 0), micro, tzinfo=timezone.utc,
        )
    except ValueError:
        return None
    if off and off not in ("Z", "z"):
        sign = 1 if off[0] == "+" else -1
        body = off[1:].replace(":", "")
        oh, om = int(body[:2]), int(body[2:4])
        dt = dt - sign * timedelta(hours=oh, minutes=om)
    return dt


def _style_of(s):
    """(fractional-digit count or None) for a source instant string."""
    m = _ISO_RE.match(s.strip()) if isinstance(s, str) else None
    if not m:
        return 3
    frac = m.group(7)
    if not frac:
        return 0
    return len(frac) - 1


def _render(dt, frac_digits):
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    if frac_digits <= 0:
        return base + "Z"
    micro = "%06d" % dt.microsecond
    if frac_digits <= 6:
        return base + "." + micro[:frac_digits] + "Z"
    return base + "." + micro + "0" * (frac_digits - 6) + "Z"


def ts_canonical(dt):
    """case A -- server-minted, always three fractional digits."""
    return TS(dt, _render(dt, 3))


def ts_input(raw):
    """case B -- caller-supplied string echoed byte-verbatim (None if unparsable)."""
    dt = parse_dt(raw)
    if dt is None:
        return None
    return TS(dt, raw.strip() if isinstance(raw, str) else raw)


def ts_shift(base, delta):
    """case C -- derived instant, rendered in the style of its source string."""
    if base is None:
        return None
    dt = base.dt + delta
    return TS(dt, _render(dt, _style_of(base.s)))


def render(ts):
    """The single instant render function."""
    return None if ts is None else ts.s


def sec(dt):
    return dt.replace(microsecond=0)


def cmp_instants(a, b):
    """-1/0/1 comparing two TS (or datetimes) at second granularity."""
    da = sec(a.dt if isinstance(a, TS) else a)
    db = sec(b.dt if isinstance(b, TS) else b)
    return -1 if da < db else (1 if da > db else 0)


def lt(a, b):
    return cmp_instants(a, b) < 0


def gte(a, b):
    return cmp_instants(a, b) >= 0


# ---------------------------------------------------------------------------
# rounding
# ---------------------------------------------------------------------------

def round_half_up(value, places=0):
    """Round a Decimal/Fraction/number half up to `places` decimals."""
    if isinstance(value, Fraction):
        d = Decimal(value.numerator) / Decimal(value.denominator)
    elif isinstance(value, Decimal):
        d = value
    elif isinstance(value, int):
        d = Decimal(value)
    else:
        d = Decimal(str(value))
    q = Decimal(1).scaleb(-places)
    return d.quantize(q, rounding=ROUND_HALF_UP)


def cents(value):
    """Round half up to a whole cent and return an int."""
    return int(round_half_up(value, 0))


def num2(value):
    """Round half up to 2 decimals and return a float (oven hours, distances)."""
    return float(round_half_up(value, 2))


def dec(value):
    """Decimal from an arbitrary JSON number without float artefacts."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))
