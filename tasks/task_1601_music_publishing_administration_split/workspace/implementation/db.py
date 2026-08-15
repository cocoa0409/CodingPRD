"""In-memory data store, logical clock, and timestamp utilities.

State lives only in module-level dicts; every process boot starts empty.
"""
import uuid
from datetime import datetime, timezone, timedelta

STORE = {
    "writers": {},
    "works": {},
    "societies": {},
    "society_registrations": {},
    "split_sets": {},
    "split_lines": {},
    "sub_publishers": {},
    "sub_publishing_agreements": {},
    "licensees": {},
    "royalty_statements": {},
    "statement_lines": {},
    "allocation_lines": {},
    "advances": {},
    "distribution_runs": {},
    "licensee_audits": {},
    "termination_claims": {},
}

# Internal (never serialized) recoupment application ledger.
RECOUP_LEDGER = []
_ledger_seq = [0]
_work_code_seq = [0]

# Logical clock: startup default is exactly 2026-08-01T00:00:00Z.
_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_last_ts = None


def clock_now():
    return _CLOCK


def set_clock(dt):
    global _CLOCK
    _CLOCK = dt


def tick():
    """Strictly increasing timestamp anchored to (never behind) the clock."""
    global _last_ts
    if _last_ts is None or _CLOCK > _last_ts:
        _last_ts = _CLOCK
    else:
        _last_ts = _last_ts + timedelta(milliseconds=1)
    return _last_ts


def iso(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_dt(value):
    """Parse ISO-8601 (Z or offset, date-only allowed) into aware UTC dt."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_years(dt, years):
    """Calendar-year arithmetic; Feb 29 clamps to Feb 28 in non-leap years."""
    try:
        return dt.replace(year=dt.year + years)
    except ValueError:
        return dt.replace(year=dt.year + years, day=28)


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + uuid.uuid4().hex[:24]


def next_work_code():
    _work_code_seq[0] += 1
    return "W-%06d" % _work_code_seq[0]


def next_ledger_seq():
    _ledger_seq[0] += 1
    return _ledger_seq[0]
