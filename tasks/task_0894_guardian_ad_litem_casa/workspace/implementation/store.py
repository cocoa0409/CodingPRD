"""In-memory data store, logical clock, and shared helpers.

The store starts EMPTY on every process boot. No seeding is performed.
"""
import uuid
import random
import string
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

UTC = timezone.utc
CLOCK_DEFAULT = datetime(2026, 5, 1, 0, 0, 0, tzinfo=UTC)

# ---------------------------------------------------------------------------
# Data collections (keyed by id)
# ---------------------------------------------------------------------------
volunteers = {}
supervisors = {}
cases = {}
assignments = {}
visits = {}
hearings = {}
court_reports = {}
review_notes = {}
background_checks = {}
training_records = {}
expense_claims = {}

_seq = 0
_clock = CLOCK_DEFAULT


def reset():
    global volunteers, supervisors, cases, assignments, visits, hearings
    global court_reports, review_notes, background_checks, training_records
    global expense_claims, _seq, _clock
    volunteers = {}
    supervisors = {}
    cases = {}
    assignments = {}
    visits = {}
    hearings = {}
    court_reports = {}
    review_notes = {}
    background_checks = {}
    training_records = {}
    expense_claims = {}
    _seq = 0
    _clock = CLOCK_DEFAULT


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
def now():
    return _clock


def set_now(dt):
    global _clock
    _clock = dt.astimezone(UTC)


# ---------------------------------------------------------------------------
# Id / sequence / timestamp helpers
# ---------------------------------------------------------------------------
def next_seq():
    global _seq
    _seq += 1
    return _seq


def new_id():
    return str(uuid.uuid4())


def gen_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def fmt_dt(dt):
    """Render a datetime as ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def wall_now_iso():
    return fmt_dt(datetime.now(UTC))


def parse_dt(s):
    """Parse an ISO 8601 datetime string into an aware UTC datetime."""
    if not isinstance(s, str) or not s:
        raise ValueError("not a datetime string")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def add_days(dt, days):
    return dt + timedelta(days=days)


def rhu(value, places):
    """Round-half-up to the given number of decimal places (returns Decimal)."""
    quant = Decimal(10) ** (-places)
    return Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Common field helpers
# ---------------------------------------------------------------------------
def stamp_common(rec):
    """Attach id/created_at/updated_at/version + sequence to a full resource."""
    t = now()
    rec["id"] = new_id()
    rec["created_at"] = t
    rec["updated_at"] = t
    rec["version"] = 1
    rec["_seq"] = next_seq()
    return rec


def stamp_audit(rec):
    """Attach id/created_at + sequence to an immutable audit resource."""
    rec["id"] = new_id()
    rec["created_at"] = now()
    rec["_seq"] = next_seq()
    return rec


def touch(rec):
    rec["updated_at"] = now()
    rec["version"] = rec.get("version", 1) + 1
