"""In-memory store, the logical clock, and the arithmetic helpers of PRD 2.10.

Storage is process memory only.  Nothing is persisted anywhere; a fresh process
starts with every collection empty.
"""

import datetime as _dt
import itertools
import random
import string
import uuid
from decimal import Decimal, ROUND_HALF_UP

# ---------------------------------------------------------------- collections

COLLECTIONS = (
    "providers",
    "payers",
    "patients",
    "sleep_studies",
    "referrals",
    "written_orders",
    "prior_auths",
    "lab_orders",
    "appliance_lots",
    "appliances",
    "titration_visits",
    "adherence_downloads",
    "efficacy_reports",
    "claims",
    "repair_orders",
    "audit_holds",
)

DB = {name: {} for name in COLLECTIONS}

_seq_counter = itertools.count(1)

# The logical clock.  Before the first set it reads exactly 2026-05-01T00:00:00Z
# and it never falls back to wall-clock time thereafter (PRD 2.4).
CLOCK = {"current": _dt.datetime(2026, 5, 1, 0, 0, 0, tzinfo=_dt.timezone.utc)}


def reset():
    for name in COLLECTIONS:
        DB[name] = {}
    CLOCK["current"] = _dt.datetime(2026, 5, 1, 0, 0, 0, tzinfo=_dt.timezone.utc)


def next_seq():
    return next(_seq_counter)


def new_id():
    return str(uuid.uuid4())


def request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


# ------------------------------------------------------------------ instants

def render_instant(value):
    """One uniform rendering rule: ISO 8601 UTC, exactly 3 fractional digits, Z."""
    if value is None:
        return None
    if value.tzinfo is not None:
        value = value.astimezone(_dt.timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        value.year, value.month, value.day,
        value.hour, value.minute, value.second,
        value.microsecond // 1000,
    )


def now_instant():
    """Real server time — created_at / updated_at are wall-clock instants."""
    return _dt.datetime.now(_dt.timezone.utc)


def now_iso():
    return render_instant(now_instant())


def parse_instant(text):
    """Parse a caller supplied instant.  Returns None when unparseable."""
    if not isinstance(text, str):
        return None
    raw = text.strip()
    if not raw:
        return None
    if raw.endswith("Z") or raw.endswith("z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = _dt.datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_dt.timezone.utc)
    return parsed.astimezone(_dt.timezone.utc)


def clock_now():
    return CLOCK["current"]


def clock_date():
    """The UTC calendar date of the logical clock."""
    return CLOCK["current"].date()


def set_clock(instant):
    CLOCK["current"] = instant


# --------------------------------------------------------------------- dates

def parse_date(text):
    """Strict YYYY-MM-DD.  Returns None when the value is not a calendar date."""
    if not isinstance(text, str) or len(text) != 10:
        return None
    if text[4] != "-" or text[7] != "-":
        return None
    try:
        return _dt.date(int(text[0:4]), int(text[5:7]), int(text[8:10]))
    except ValueError:
        return None


def render_date(value):
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return value.isoformat()


def add_days(day, days):
    return day + _dt.timedelta(days=days)


def add_months(day, months):
    """Keeps the day-of-month, clamping to the last day of a shorter month."""
    total = day.month - 1 + int(months)
    year = day.year + total // 12
    month = total % 12 + 1
    if month == 12:
        last = 31
    else:
        last = (_dt.date(year + (month // 12), month % 12 + 1, 1) - _dt.timedelta(days=1)).day
    return _dt.date(year, month, min(day.day, last))


def day_span(start, end):
    return (end - start).days


# ---------------------------------------------------------------- arithmetic

def round_half_up(value, places=0):
    """Round half up at the stated precision (PRD 2.10)."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    quant = Decimal(1).scaleb(-places)
    return value.quantize(quant, rounding=ROUND_HALF_UP)


def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def num(value, places):
    """Render a Decimal as a JSON number carried to `places` decimals."""
    if value is None:
        return None
    return float(round_half_up(dec(value), places))
