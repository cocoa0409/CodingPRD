"""In-memory data store, logical clock and shared primitives.

Storage is process-local (plain dicts keyed by id).  Nothing is seeded: every
entity is created by API callers through the declared endpoints.
"""
import itertools
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

# PRD 2.5: before any client sets it the logical clock reads exactly this
# instant, and the server never falls back to wall-clock time.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.clock = DEFAULT_CLOCK
        self.publications = {}
        self.qualification_rules = {}
        self.subscribers = {}
        self.source_documents = {}
        self.qualification_requests = {}
        self.statements = {}
        self.engagements = {}
        self.findings = {}
        self.contracts = {}
        self.make_goods = {}
        self.snapshots = {}
        self.hygiene_runs = {}
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = Store()


def new_id():
    return str(uuid.uuid4())


def now():
    return db.clock


def set_clock(dt):
    db.clock = dt


def request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


# --------------------------------------------------------------------------
# temporal helpers
# --------------------------------------------------------------------------

def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional-second digits and a Z."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_dt(value):
    """Parse an ISO-8601 UTC timestamp.  Returns None when unparseable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _days_in_month(year, month):
    if month == 12:
        nxt = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        nxt = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return (nxt - datetime(year, month, 1, tzinfo=timezone.utc)).days


def add_months(dt, months):
    """Calendar-month addition with day clamping (Jan 31 + 1 month = Feb 28)."""
    total = dt.month - 1 + int(months)
    year = dt.year + total // 12
    month = total % 12 + 1
    day = min(dt.day, _days_in_month(year, month))
    return dt.replace(year=year, month=month, day=day)


def complete_months(start, end):
    """Number of COMPLETE calendar months from start to end (floor)."""
    if end < start:
        return 0
    guess = (end.year - start.year) * 12 + (end.month - start.month)
    if guess < 0:
        guess = 0
    while guess > 0 and add_months(start, guess) > end:
        guess -= 1
    while add_months(start, guess + 1) <= end:
        guess += 1
    return guess


def add_days(dt, days):
    return dt + timedelta(days=int(days))


# --------------------------------------------------------------------------
# numeric helpers
# --------------------------------------------------------------------------

def round_half_up(value, places=2):
    """Decimal round-half-up to `places` decimal places."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    exp = Decimal(1).scaleb(-places)
    return value.quantize(exp, rounding=ROUND_HALF_UP)


def pct2(value):
    return round_half_up(Decimal(str(value)), 2)


def ratio_pct(numerator, denominator):
    """round_half_up(numerator * 100 / denominator, 2); 0.00 when denom == 0."""
    if not denominator:
        return Decimal("0.00")
    return round_half_up(Decimal(numerator) * 100 / Decimal(denominator), 2)


def floor_div_decimal(value):
    """Truncate a Decimal quotient down to a whole number (toward -inf >= 0)."""
    return int(value.to_integral_value(rounding="ROUND_FLOOR"))


# --------------------------------------------------------------------------
# record helpers
# --------------------------------------------------------------------------

def base_record(with_version=True):
    stamp = now()
    rec = {"id": new_id(), "created_at": stamp}
    if with_version:
        rec["updated_at"] = stamp
        rec["version"] = 1
    rec["_seq"] = db.next_seq()
    return rec


def touch(rec):
    """Refresh updated_at and advance version by exactly 1."""
    rec["updated_at"] = now()
    rec["version"] = rec.get("version", 0) + 1


def serialize(rec):
    out = {}
    for key, value in rec.items():
        if key.startswith("_"):
            continue
        if isinstance(value, datetime):
            out[key] = fmt_dt(value)
        elif isinstance(value, Decimal):
            out[key] = float(value)
        else:
            out[key] = value
    return out


def sort_key(rec):
    return (rec["created_at"], rec["_seq"])


def collection_sorted(values, newest_first=False):
    ordered = sorted(values, key=sort_key)
    if newest_first:
        ordered.reverse()
    return ordered
