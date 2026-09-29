"""In-memory data store.

Storage is process-local Python dicts keyed by entity id. Nothing is persisted
and NOTHING is seeded: every boot starts completely empty, and all state is
created through the declared endpoints.
"""

import datetime
import threading
import uuid

from flask import g

from constants import CLOCK_DEFAULT

# ---------------------------------------------------------------------------
# Stores (id -> record dict)
# ---------------------------------------------------------------------------
survivors = {}
recovery_cases = {}
damage_items = {}
assistance_records = {}
assessments = {}
member_orgs = {}
table_sessions = {}
presentations = {}
commitments = {}
funding_sources = {}
disbursements = {}
projects = {}
volunteer_groups = {}
deployments = {}
lodging_sites = {}
housing_assignments = {}
follow_ups = {}

# One global request lock: the Flask dev server is threaded and every request
# mutates shared dicts.
REQUEST_LOCK = threading.RLock()

_seq_counter = [0]

# ---------------------------------------------------------------------------
# Logical clock (PRD 2.4) -- never falls back to the host wall clock.
# ---------------------------------------------------------------------------
_clock = [datetime.datetime(2026, 8, 1, 0, 0, 0)]


def _fmt(dt):
    """ISO 8601 UTC with exactly three fractional-second digits."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def clock_now():
    return _clock[0]


def clock_iso():
    return _fmt(_clock[0])


def clock_date():
    return _clock[0].date()


def set_clock(dt):
    _clock[0] = dt


def reset_clock():
    _clock[0] = datetime.datetime(2026, 8, 1, 0, 0, 0)


def stamp_iso():
    """Timestamp used for created_at / updated_at / envelope metadata.

    PRD 2.4: "Time is not read from the host." Every timestamp the server mints
    therefore resolves against the logical clock.
    """
    return _fmt(_clock[0])


# ---------------------------------------------------------------------------
# Record helpers
# ---------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def next_seq():
    _seq_counter[0] += 1
    return _seq_counter[0]


def base_record(with_version=True):
    """Common system fields (PRD 2.4)."""
    now = stamp_iso()
    rec = {"id": new_id(), "created_at": now}
    if with_version:
        rec["updated_at"] = now
        rec["version"] = 1
    rec["_seq"] = next_seq()
    fresh = getattr(g, "new_records", None)
    if fresh is None:
        fresh = []
        g.new_records = fresh
    fresh.append(rec)
    return rec


def mark(rec):
    """Flag a record as mutated by this request (version bumped once at flush).

    A record created during the same request stays at version 1: roll-ups that
    touch it are part of its creation, not a later mutation.
    """
    if rec is None or "version" not in rec:
        return
    for fresh in getattr(g, "new_records", None) or ():
        if fresh is rec:
            return
    lst = getattr(g, "dirty_records", None)
    if lst is None:
        lst = []
        g.dirty_records = lst
    for existing in lst:
        if existing is rec:
            return
    lst.append(rec)


def set_field(rec, key, value):
    """Assign and mark dirty only when the value actually changes."""
    if rec.get(key) != value:
        rec[key] = value
        mark(rec)
        return True
    return False


def flush():
    """Apply one version increment + updated_at refresh per mutated record."""
    lst = getattr(g, "dirty_records", None)
    if not lst:
        return
    now = stamp_iso()
    for rec in lst:
        rec["version"] = rec.get("version", 1) + 1
        rec["updated_at"] = now
    g.dirty_records = []


def public(rec):
    """Strip internal bookkeeping keys before serialization."""
    if isinstance(rec, dict):
        return {k: v for k, v in rec.items() if not k.startswith("_")}
    return rec


def sorted_records(records):
    """Default ordering: created_at ascending (insertion order breaks ties)."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
