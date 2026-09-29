"""In-memory data store, id minting and the logical program clock (PRD 2.4, 2.5).

The store is EMPTY on every boot.  No entity is ever seeded, preloaded or
hardcoded: every row is created through a declared endpoint.
"""

import itertools
import re
import uuid
from datetime import datetime, timedelta, timezone

from flask import g

# PRD 2.5 -- the logical clock starts here on every service startup.
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

TABLES = (
    "households",
    "applications",
    "income_sources",
    "resource_items",
    "cases",
    "time_limit_months",
    "extensions",
    "work_assignments",
    "participation_reports",
    "compliance_episodes",
    "supportive_auths",
    "diversion_grants",
    "overpayments",
    "recovery_transactions",
    "reporting_periods",
)


class _Db:
    def __init__(self):
        self.reset()

    def reset(self):
        self.current_utc = CLOCK_EPOCH
        self._seq = itertools.count(1)
        self._case_no = itertools.count(1)
        for name in TABLES:
            setattr(self, name, {})

    def next_seq(self):
        return next(self._seq)

    def next_case_number(self):
        return "CASE-%06d" % next(self._case_no)


db = _Db()


def new_id():
    return str(uuid.uuid4())


def fmt_ts(moment):
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        "%03dZ" % (moment.microsecond // 1000)


def now_iso():
    """Timestamps come from the logical clock -- nothing reads the wall clock."""
    return fmt_ts(db.current_utc)


def clock_date():
    return db.current_utc.strftime("%Y-%m-%d")


def clock_month():
    return db.current_utc.strftime("%Y-%m")


def clock_fiscal_year():
    """Federal fiscal year of the logical clock (Oct-Dec belong to the next FY)."""
    if db.current_utc.month >= 10:
        return db.current_utc.year + 1
    return db.current_utc.year


_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2}):(\d{2})(\.\d{1,6})?"
    r"(Z|z|[+-]\d{2}:\d{2})?$")


def parse_iso8601(value):
    """Parse an ISO-8601 instant; returns None when malformed."""
    if not isinstance(value, str):
        return None
    if not _ISO_RE.match(value.strip()):
        return None
    text = value.strip()
    if text[-1] in "Zz":
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def set_clock(moment):
    db.current_utc = moment
    return fmt_ts(moment)


# ---------------------------------------------------------------------------
# Record helpers
# ---------------------------------------------------------------------------

def _touched():
    try:
        marks = g.get("_touched_rows", None)
    except RuntimeError:
        return None
    if marks is None:
        marks = set()
        g._touched_rows = marks
    return marks


def new_record(fields, audited=True):
    """Create a record.  Audited rows carry id/created_at/updated_at/version;
    append-only ledger rows carry only id and created_at (PRD 2.4)."""
    stamp = now_iso()
    record = {"id": new_id(), "created_at": stamp}
    if audited:
        record["updated_at"] = stamp
        record["version"] = 1
    record.update(fields)
    record["_seq"] = db.next_seq()
    return record


def touch(record):
    """Refresh updated_at and bump version -- at most once per request per row."""
    if record is None or "version" not in record:
        return record
    marks = _touched()
    if marks is not None:
        key = id(record)
        if key in marks:
            return record
        marks.add(key)
    record["version"] = record["version"] + 1
    record["updated_at"] = now_iso()
    return record


def apply_computed(record, values):
    """Write recomputed derived values; a real change is a mutation (PRD 2.4)."""
    changed = False
    for key, value in values.items():
        if record.get(key) != value:
            record[key] = value
            changed = True
    if changed:
        touch(record)
    return changed


def serialize(record):
    return {k: v for k, v in record.items() if not k.startswith("_")}


def ordered(rows):
    """Creation order (PRD 2.3 default ascending sort)."""
    return sorted(rows, key=lambda r: r["_seq"])


def add_days(date_str, days):
    base = datetime.strptime(date_str, "%Y-%m-%d")
    return (base + timedelta(days=days)).strftime("%Y-%m-%d")
