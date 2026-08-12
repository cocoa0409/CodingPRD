"""In-memory data store, logical clock, id/timestamp helpers.

The store starts empty on every boot. No seeding anywhere.
"""
import uuid
from datetime import datetime, timezone

from util import fmt_dt

# ---- Logical clock (fixed default; never falls back to wall-clock) ----
_DEFAULT_CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = _DEFAULT_CLOCK
_clock_input_echo = "2026-05-01T00:00:00Z"

# ---- Insertion sequence (deterministic tiebreak for equal created_at) ----
_seq = 0

# ---- Entity stores (dicts keyed by id) ----
partners = {}
courses = {}
agreements = {}
equivalencies = {}
students = {}
transcripts = {}
evaluations = {}
lines = {}
petitions = {}
appeals = {}
plas = {}
applications = {}
guides = {}

STORES = {
    "partner": partners,
    "course": courses,
    "agreement": agreements,
    "equivalency": equivalencies,
    "student": students,
    "transcript": transcripts,
    "evaluation": evaluations,
    "line": lines,
    "petition": petitions,
    "appeal": appeals,
    "pla": plas,
    "application": applications,
    "guide": guides,
}


def now():
    return _clock


def now_iso():
    return fmt_dt(_clock)


def set_clock(dt, echo):
    global _clock, _clock_input_echo
    _clock = dt
    _clock_input_echo = echo


def clock_echo():
    return _clock_input_echo


def next_seq():
    global _seq
    _seq += 1
    return _seq


def new_id():
    return str(uuid.uuid4())


def create_rec(store, fields):
    """Insert a new record with standard system-managed fields (version=1)."""
    rec = dict(fields)
    ts = now_iso()
    rec["id"] = new_id()
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    rec["_seq"] = next_seq()
    store[rec["id"]] = rec
    return rec


def touch(rec):
    """Register a mutation: refresh updated_at and increment version."""
    rec["updated_at"] = now_iso()
    rec["version"] = int(rec.get("version", 1)) + 1


def sort_key(rec):
    """Default list ordering: created_at ASC (insertion seq as tiebreak)."""
    return (rec.get("created_at", ""), rec.get("_seq", 0))
