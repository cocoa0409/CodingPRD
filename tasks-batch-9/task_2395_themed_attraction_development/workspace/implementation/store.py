"""In-memory data store and the server's logical clock.

Storage is process-local Python dicts keyed by id.  Every dict below starts
EMPTY on every boot: nothing is seeded, preloaded or hardcoded.  Tests build all
preconditions through the declared API surface.
"""

import itertools
import uuid
from datetime import datetime, timedelta, timezone

from flask import g

# ---------------------------------------------------------------- collections
projects = {}
ride_systems = {}
queue_segments = {}
show_scenes = {}
effect_cues = {}
design_packages = {}
safety_reviews = {}
safety_findings = {}
ve_items = {}
ve_ballots = {}
rehearsal_runs = {}
maintenance_items = {}
ledger_entries = {}

_ALL = (
    projects,
    ride_systems,
    queue_segments,
    show_scenes,
    effect_cues,
    design_packages,
    safety_reviews,
    safety_findings,
    ve_items,
    ve_ballots,
    rehearsal_runs,
    maintenance_items,
    ledger_entries,
)

_insertion_counter = itertools.count(1)

# ------------------------------------------------------------- logical clock
# PRD section 3.1: before it is ever repositioned the logical clock reads
# exactly 2026-08-01T00:00:00Z and it must never fall back to real time.
LOGICAL_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = {"now": LOGICAL_EPOCH}


def now():
    return _clock["now"]


def set_now(dt):
    _clock["now"] = dt.astimezone(timezone.utc)


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-08-01T00:00:00.000Z"""
    if dt is None:
        return None
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
    return iso(now())


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_insertion_counter)


# ----------------------------------------------------------------- row helpers
def base_row(with_audit=True):
    """id / created_at (/ updated_at / version) plus the private ordering key."""
    row = {"id": new_id()}
    row["_seq"] = next_seq()
    row["created_at"] = now_iso()
    if with_audit:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    return row


def touch(row):
    """Advance a row's revision counter at most once per request."""
    if row is None or "version" not in row:
        return
    touched = getattr(g, "touched", None)
    if touched is None:
        touched = set()
        g.touched = touched
    if row["id"] not in touched:
        row["version"] += 1
        touched.add(row["id"])
    row["updated_at"] = now_iso()


def public(row):
    return {k: v for k, v in row.items() if not k.startswith("_")}


def public_list(rows):
    return [public(r) for r in rows]


def sorted_rows(rows):
    """Default list order: created_at ascending (stable on insertion order)."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def parse_dt(text):
    """Parse an ISO 8601 instant; returns None when unparseable."""
    if not isinstance(text, str) or not text.strip():
        return None
    raw = text.strip()
    candidate = raw
    if candidate.endswith("Z") or candidate.endswith("z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


CHANGEOVER = timedelta(minutes=120)


def reset_all():  # pragma: no cover - defensive helper, never called at boot
    for collection in _ALL:
        collection.clear()
    _clock["now"] = LOGICAL_EPOCH
