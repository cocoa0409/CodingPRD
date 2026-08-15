"""In-memory data store. The store starts empty on every boot — no seeding.

A fresh process (per-test-server isolation) therefore always begins with no
entities and the logical clock at its startup default.
"""

import itertools
import uuid
from datetime import datetime, timezone

_seq_counter = itertools.count(1)


def next_seq():
    return next(_seq_counter)


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """Wall-clock UTC timestamp, ISO 8601 with three fractional digits."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


STORE = {
    "departments": {},
    "terms": {},
    "courses": {},
    "proposals": {},
    "decision_records": [],
    "requisite_links": {},
    "cross_listings": {},
    "teach_out_plans": {},
    "catalog_editions": {},
    "catalog_entries": {},
}


# --- Logical clock -----------------------------------------------------------
# Startup default is exactly 2026-08-01T00:00:00Z; never falls back to
# wall-clock time. Advanced only via POST /curriculum/_clock/set_current_utc.
_DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
CLOCK = {"dt": None}


def clock_now():
    return CLOCK["dt"] if CLOCK["dt"] is not None else _DEFAULT_CLOCK


def logical_iso():
    return clock_now().astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


# --- Record helpers ----------------------------------------------------------

def new_record():
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(rec):
    """Every mutation bumps version and updated_at (PRD section 2.4)."""
    rec["version"] += 1
    rec["updated_at"] = now_iso()


def pub(rec):
    """Public view of a record: strip internal bookkeeping keys."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}
