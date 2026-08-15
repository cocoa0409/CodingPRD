"""Parsing, datetime, quarter, and decimal helpers (PRD 2.9).

All monetary values use Decimal arithmetic rounded to 2 places round-half-up;
concentration fractions use 4 places; IRR percentages use 2 places.
"""

import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

_QUARTER_RE = re.compile(r"^(\d{4})-Q([1-4])$")


def parse_datetime(s):
    """Parse an ISO 8601 datetime (Z or numeric offset); None when malformed."""
    if not isinstance(s, str):
        return None
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def dec(v):
    """Exact Decimal from a JSON number."""
    return Decimal(str(v))


def money2(v):
    """Round half up to 2 decimals, returned as float for JSON."""
    return float(dec(v).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def money2_dec(v):
    return dec(v).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def frac4(v):
    """Round half up to 4 decimals, returned as float for JSON."""
    return float(dec(v).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def pct2(v):
    return float(dec(v).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Quarter helpers: labels are "YYYY-Qn".
# ---------------------------------------------------------------------------

def parse_quarter(s):
    """Parse a YYYY-Qn quarter label -> (year, q); None when malformed."""
    if not isinstance(s, str):
        return None
    m = _QUARTER_RE.match(s)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def quarter_start(y, q):
    """UTC instant at the start of quarter q of year y."""
    month = (q - 1) * 3 + 1
    return datetime(y, month, 1, tzinfo=timezone.utc)


def quarter_end(y, q):
    """UTC instant at the start of the NEXT quarter (exclusive end)."""
    if q == 4:
        return datetime(y + 1, 1, 1, tzinfo=timezone.utc)
    return datetime(y, q * 3 + 1, 1, tzinfo=timezone.utc)


def quarter_label(dt):
    q = (dt.month - 1) // 3 + 1
    return "%04d-Q%d" % (dt.year, q)


def quarter_index(y, q):
    return y * 4 + (q - 1)


def quarters_held(vintage_year, report_y, report_q):
    """Whole quarters from the vehicle's vintage-year Q1 through the report
    quarter inclusive (2026-Q1 vintage reported at 2026-Q3 => 3)."""
    return quarter_index(report_y, report_q) - quarter_index(vintage_year, 1) + 1


def add_quarters(y, q, n):
    idx = quarter_index(y, q) + n
    return idx // 4, idx % 4 + 1
