"""In-memory data store and the server-side logical clock.

The store starts EMPTY on every boot. Nothing is seeded, preloaded or
hardcoded here; every entity is created through the declared API surface.
"""
import itertools
import uuid
from datetime import datetime, timezone

# ---------------------------------------------------------------- collections
state_rules = {}
audit_projects = {}
job_families = {}
positions = {}
duty_statements = {}
interviews = {}
exemption_analyses = {}
reclassification_cases = {}
back_wage_estimates = {}
voluntary_corrections = {}
contractor_reviews = {}
job_change_triggers = {}

_seq = itertools.count(1)

# ------------------------------------------------------------- logical clock
# PRD 2.5: before any operator sets it, the logical clock reads
# 2026-08-01T00:00:00Z.
_clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def clock_now():
    return _clock


def set_clock(dt):
    global _clock
    _clock = dt


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
        dt.microsecond // 1000,
    )


def now_iso():
    """The logical clock rendered as an API timestamp."""
    return fmt_dt(_clock)


def clock_date():
    return _clock.astimezone(timezone.utc).date()


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq)


def make_row(versioned=True, **fields):
    row = {"id": new_id(), "_seq": next_seq()}
    row.update(fields)
    row["created_at"] = now_iso()
    if versioned:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    return row


def touch(row):
    """Record a mutation of a row: refresh updated_at, bump version."""
    if "version" in row:
        row["updated_at"] = now_iso()
        row["version"] = row["version"] + 1


def ordered(rows):
    """List ordering: created_at ASC, insertion order as the stable fallback."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
