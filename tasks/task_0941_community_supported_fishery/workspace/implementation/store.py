"""In-memory data store.

Storage is Python dicts keyed by id and nothing else: no sqlite file, no JSON
dump, no pickle, no /tmp cache, no external persistence.  Re-invoking start.sh
wipes every byte of state.  Nothing is seeded, preloaded or hardcoded at
startup -- every entity a test needs is built through a declared endpoint.
"""
import threading

import clock
import ids

KINDS = (
    "Season", "SharePlan", "DeliveryZone", "PickupHub", "PickupWindow",
    "Member", "Subscription", "Vessel", "QuotaLedger", "Trip", "LandingLot",
    "SubLot", "ShareDelivery", "SubstitutionEvent", "ColdChainEvent",
    "SkipRequest", "SettlementStatement", "ShareTransfer", "RecallNotice",
)

# Cold-chain legs are append-only observations: PRD 2.4 gives them id and
# created_at and neither updated_at nor version.
NO_COMMON_FIELDS = {"ColdChainEvent"}

_lock = threading.Lock()
tables = {k: {} for k in KINDS}
_seq = [0]

# Per-request bookkeeping.  Flask serves one request at a time under the
# single-threaded dev server this app runs, and the lock keeps the counters
# honest anyway.
_pending = {"touched": [], "created": set()}


def reset():
    with _lock:
        for k in KINDS:
            tables[k].clear()
        _seq[0] = 0
        _pending["touched"] = []
        _pending["created"] = set()
    ids.reset()
    clock.CLOCK.reset()


def begin_request():
    _pending["touched"] = []
    _pending["created"] = set()


def _next_seq():
    _seq[0] += 1
    return _seq[0]


def create(kind, fields):
    """Insert a record.  version starts at 1 (PRD 2.4)."""
    now = clock.now()
    rec = dict(fields)
    rec["_kind"] = kind
    rec["_seq"] = _next_seq()
    rec["id"] = ids.new_id()
    rec["created_at"] = now
    if kind not in NO_COMMON_FIELDS:
        rec["updated_at"] = now
        rec["version"] = 1
    tables[kind][rec["id"]] = rec
    _pending["created"].add(rec["id"])
    return rec


def touch(rec):
    """Mark a record mutated by this request.

    PRD 2.4: version "increases by exactly 1 on every mutation of that
    resource" and the three optimistic-concurrency sentences in PRD 2.7 each
    say a successful call "increments the ... version by 1".  A resource is
    therefore bumped once per request no matter how many steps of a cascade
    touched it, and a resource created in this request is not bumped at all --
    it is already at version 1.
    """
    if rec is None:
        return rec
    if rec["_kind"] in NO_COMMON_FIELDS:
        return rec
    if rec["id"] in _pending["created"]:
        return rec
    if rec.get("_touched"):
        return rec
    rec["_touched"] = True
    _pending["touched"].append(rec)
    return rec


def commit():
    """Apply the version bump and updated_at refresh for this request.

    Called immediately before a response is serialised so that no serializer
    ever projects a record ahead of its own version bump.
    """
    if not _pending["touched"]:
        return
    now = clock.now()
    for rec in _pending["touched"]:
        rec["version"] = rec.get("version", 1) + 1
        rec["updated_at"] = now
        rec.pop("_touched", None)
    _pending["touched"] = []


def get(kind, rec_id):
    if not isinstance(rec_id, str):
        return None
    return tables[kind].get(rec_id)


def all_of(kind):
    return list(tables[kind].values())


def ordered(kind, predicate=None):
    """Rows in created_at ascending order (PRD 2.3).

    The logical clock makes created_at ties routine, so the monotonic insertion
    sequence is the deterministic tie-break; it is exactly creation order and
    therefore also the order the monotonic id strings carry.
    """
    rows = [r for r in tables[kind].values() if predicate is None or predicate(r)]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rows


def find(kind, predicate):
    for r in ordered(kind):
        if predicate(r):
            return r
    return None
