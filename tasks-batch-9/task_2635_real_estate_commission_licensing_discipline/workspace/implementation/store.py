"""In-memory data store, logical clock, id/version bookkeeping.

Every byte of state lives in module-level dicts, so a fresh process starts
completely empty (apart from the RecoveryFund singleton the PRD mandates at
system initialisation).
"""
import random
import string
import uuid
from datetime import datetime, timezone, timedelta, date
from decimal import Decimal, ROUND_HALF_UP

from flask import g

# ---------------------------------------------------------------- logical clock
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_state = {"clock": CLOCK_DEFAULT, "seq": 0}

KINDS = [
    "licensee", "brokerage", "trust_account", "ledger_entry", "trust_audit",
    "complaint", "consent_agreement", "hearing", "sanction_order",
    "recovery_fund", "recovery_claim", "education_provider", "instructor",
    "course_completion", "advertising_name",
]

db = {k: {} for k in KINDS}
counters = {"SALESPERSON": 0, "BROKER": 0, "COMPLAINT": 0}


def now():
    return _state["clock"]


def set_clock(dt):
    _state["clock"] = dt


# ------------------------------------------------------------------ formatting
def fmt_audit(dt):
    """`created_at` / `updated_at` / `api_request_timestamp`: three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def fmt_dt(dt):
    """A domain instant: exactly the instant the logical clock reads."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond:
        return fmt_audit(dt)
    return "%04d-%02d-%02dT%02d:%02d:%02dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
    )


def fmt_date(d):
    if d is None:
        return None
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


def parse_datetime(value):
    """Parse an ISO 8601 instant. Raises ValueError when unparseable."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if not text:
        raise ValueError("empty")
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Parse an ISO 8601 calendar date. Raises ValueError when unparseable."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if not text:
        raise ValueError("empty")
    if "T" in text or "t" in text:
        return parse_datetime(text).date()
    return date.fromisoformat(text)


def dt_of(iso_text):
    """Stored ISO text -> aware datetime (None passes through)."""
    if iso_text is None:
        return None
    return parse_datetime(iso_text)


def date_of(iso_text):
    if iso_text is None:
        return None
    return parse_date(iso_text)


def plus_seconds(dt, seconds):
    return dt + timedelta(seconds=seconds)


def round_half_up(value):
    """Decimal ROUND_HALF_UP to a whole number of cents."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ------------------------------------------------------------------- id / meta
def new_id():
    return str(uuid.uuid4())


def request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def _next_seq():
    _state["seq"] += 1
    return _state["seq"]


def _touched_set():
    marks = getattr(g, "_touched", None)
    if marks is None:
        marks = set()
        g._touched = marks
    return marks


def touch(row):
    """Refresh updated_at and advance version at most once per request."""
    if row is None:
        return row
    marks = _touched_set()
    if "updated_at" in row:
        row["updated_at"] = fmt_audit(now())
    if row["id"] not in marks:
        marks.add(row["id"])
        if "version" in row:
            row["version"] = row["version"] + 1
    return row


def insert(kind, fields, audited=True):
    """Create a row with the system-managed common fields."""
    stamp = fmt_audit(now())
    row = {"id": new_id()}
    row.update(fields)
    row["created_at"] = stamp
    if audited:
        row["updated_at"] = stamp
        row["version"] = 1
    row["_seq"] = _next_seq()
    db[kind][row["id"]] = row
    try:
        _touched_set().add(row["id"])
    except RuntimeError:
        pass
    return row


def get(kind, row_id):
    if not isinstance(row_id, str):
        return None
    return db[kind].get(row_id)


def all_rows(kind):
    return sorted(db[kind].values(), key=lambda r: r["_seq"])


def next_license_number(person_type):
    counters[person_type] += 1
    prefix = "SP-" if person_type == "SALESPERSON" else "BR-"
    return prefix + "%06d" % counters[person_type]


def next_case_number():
    counters["COMPLAINT"] += 1
    return "CMP-%06d" % counters["COMPLAINT"]


def bootstrap():
    """System initialisation: the RecoveryFund singleton (PRD 2.4)."""
    if db["recovery_fund"]:
        return
    insert("recovery_fund", {
        "balance_cents": 0,
        "appropriated_cents": 0,
        "fine_credits_cents": 0,
        "awarded_cents": 0,
        "assessment_cents": 0,
        "clawed_back_cents": 0,
    })


def fund():
    rows = all_rows("recovery_fund")
    return rows[0] if rows else None
