"""In-memory store: plain dicts, empty on every boot.

No seeding, no preloading, no persistence of any kind. `bash start.sh` starts a
fresh process whose store is empty; every entity a test needs is built through
the declared API surface.
"""

import threading

from constants import CLOCK_EPOCH
from util import new_id, fmt_dt, parse_dt

LOCK = threading.RLock()

COLLECTIONS = [
    "clients",
    "engagements",
    "portal_parties",
    "authority_records",
    "destination_residences",
    "destination_rooms",
    "inventory_items",
    "family_holds",
    "sort_plans",
    "move_day_plans",
    "crew_members",
    "crew_assignments",
    "time_entries",
    "vendors",
    "vendor_assignments",
    "consignment_lots",
    "invoices",
    "invoice_lines",
    "milestones",
    "unpack_sessions",
    "punch_list_items",
]

DB = {name: {} for name in COLLECTIONS}

_clock = {"now": CLOCK_EPOCH}
_seq = {"n": 0}


def now_iso():
    """Current logical-clock instant, canonical three-fractional-digit form."""
    return _clock["now"]


def now_dt():
    return parse_dt(_clock["now"])


def set_clock(iso_instant):
    _clock["now"] = fmt_dt(parse_dt(iso_instant))
    return _clock["now"]


def next_seq():
    _seq["n"] += 1
    return _seq["n"]


def insert(collection, record):
    DB[collection][record["id"]] = record
    return record


def get(collection, record_id):
    if not isinstance(record_id, str):
        return None
    return DB[collection].get(record_id)


def all_of(collection):
    """Every record of a collection in creation order."""
    return sorted(DB[collection].values(), key=lambda r: r["_seq"])


def where(collection, **filters):
    out = []
    for record in all_of(collection):
        if all(record.get(k) == v for k, v in filters.items()):
            out.append(record)
    return out


def base_record(versioned=True):
    stamp = now_iso()
    record = {"id": new_id(), "created_at": stamp, "_seq": next_seq()}
    if versioned:
        record["updated_at"] = stamp
        record["version"] = 1
    return record


# ---------------------------------------------------------------------------
# version discipline
#
# PRD 2.4: `version` starts at 1 and "increments by exactly 1 on each mutation
# of that record". A request is one mutation, so `touch` is idempotent within a
# request: a record whose stored fields are changed by several steps of the same
# request still advances exactly one version.  `touch` is always called INLINE,
# before the response is serialised, so a mutation response always carries the
# NEW version and a client can immediately reuse it in an OCC field.
# ---------------------------------------------------------------------------

_touched = threading.local()


def begin_request():
    _touched.ids = set()


def touch(record):
    if record is None:
        return record
    seen = getattr(_touched, "ids", None)
    if seen is None:
        seen = set()
        _touched.ids = seen
    record["updated_at"] = now_iso()
    if record["id"] not in seen:
        seen.add(record["id"])
        if "version" in record:
            record["version"] = record["version"] + 1
    return record
