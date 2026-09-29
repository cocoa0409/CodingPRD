"""In-memory data store, logical clock and identifier minting.

Storage is process-local Python dicts only.  Nothing is persisted and nothing
is seeded: every row in here is created by an API call.
"""

import itertools
import uuid
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------- logical clock
# The server holds its own clock.  It starts at exactly 2026-08-01T00:00:00Z on
# every boot and only ever moves when POST /udrp/_clock advances it.  Nothing in
# this system reads wall-clock time.
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_clock = {"now": CLOCK_EPOCH}


def now():
    return _clock["now"]


def set_now(value):
    _clock["now"] = value


def fmt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_str():
    return fmt(now())


def parse_dt(raw):
    """Parse an ISO 8601 instant.  Raises ValueError when unparseable."""
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("not a timestamp")
    text = raw.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def add_days(dt, days):
    return dt + timedelta(days=days)


def add_hours(dt, hours):
    return dt + timedelta(hours=hours)


# ------------------------------------------------------------------ identifiers
_seq_counter = itertools.count(1)


def new_id():
    """Server-minted UUID with no type prefix."""
    return str(uuid.uuid4())


def next_seq():
    """Monotonic insertion sequence, used only as a stable sort tiebreaker."""
    return next(_seq_counter)


_case_counter = {"n": 0}


def next_case_number():
    _case_counter["n"] += 1
    return "D-2026-%06d" % _case_counter["n"]


# ----------------------------------------------------------------------- tables
registrars = {}
domains = {}
complainants = {}
cases = {}
grounds = {}
notices = {}
verifications = {}
notifications = {}
responses = {}
panelists = {}
appointments = {}
decisions = {}
votes = {}
challenges = {}
precedents = {}
fees = {}

TABLES = {
    "registrar": registrars,
    "domain": domains,
    "complainant": complainants,
    "case": cases,
    "ground": grounds,
    "notice": notices,
    "verification": verifications,
    "notification": notifications,
    "response": responses,
    "panelist": panelists,
    "appointment": appointments,
    "decision": decisions,
    "vote": votes,
    "challenge": challenges,
    "precedent": precedents,
    "fee": fees,
}


def base_row(**fields):
    """A row carrying the four common fields plus the supplied payload."""
    stamp = now_str()
    row = {"id": new_id()}
    row.update(fields)
    row["created_at"] = stamp
    row["updated_at"] = stamp
    row["version"] = 1
    row["_seq"] = next_seq()
    return row


def event_row(**fields):
    """A row carrying only id and created_at (ledger and ballot rows)."""
    row = {"id": new_id()}
    row.update(fields)
    row["created_at"] = now_str()
    row["_seq"] = next_seq()
    return row


def touch(row):
    """Recording a mutation -- including recomputing a derived field -- refreshes
    updated_at and increments version."""
    row["updated_at"] = now_str()
    row["version"] = row.get("version", 1) + 1
    return row


def public(row):
    """Strip internal bookkeeping keys from a row before serialisation."""
    if row is None:
        return None
    return {k: v for k, v in row.items() if not k.startswith("_")}


def ordered(table, predicate=None):
    """Rows in creation order (created_at ascending, insertion order for ties)."""
    rows = [r for r in table.values() if predicate is None or predicate(r)]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rows
