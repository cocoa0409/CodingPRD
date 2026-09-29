"""In-memory data store.

Storage is plain Python dicts keyed by the row's `id`.  The store starts
completely empty on every boot: nothing is seeded, preloaded, registered or
hardcoded here.  Every row is created by a request against a declared endpoint.

Common system-managed fields (PRD §2.5):
  * `created_at` — ISO 8601 UTC timestamp with three fractional digits
  * `updated_at` — refreshed on every mutation of the row, including mutations
    that only rewrite computed fields
  * `version`    — increments by one on every mutation of the row

`AttendanceLedgerEntry` rows are append-only and therefore carry only `id` and
`created_at`; they are inserted with ``versioned=False``.

A cascade counts as a mutation (PRD §2.5): any row whose stored value actually
changes during a request is collected in a per-request dirty set and gets
exactly one `updated_at` refresh plus one `version` increment when the request
flushes — no matter how many fields changed or how deep the cascade was.
"""

import uuid
from datetime import datetime, timezone

from flask import g

TABLES = (
    "students",
    "teachers",
    "entitlement_rules",
    "cases",
    "certifications",
    "assignments",
    "safety_reviews",
    "sessions",
    "ledger_entries",
    "extension_requests",
    "transition_plans",
    "pacing_syncs",
    "sped_service_logs",
)

# The store: table name -> {row id -> row dict}.  Empty at boot, always.
store = {name: {} for name in TABLES}

_seq = 0
_last_ms = 0


def new_id():
    """A server-minted UUID with no type prefix or other decoration."""
    return str(uuid.uuid4())


def _next_seq():
    global _seq
    _seq += 1
    return _seq


def _next_ms():
    """Strictly increasing millisecond counter so `created_at` never ties."""
    global _last_ms
    ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    if ms <= _last_ms:
        ms = _last_ms + 1
    _last_ms = ms
    return ms


def _fmt(ms):
    dt = datetime.fromtimestamp(ms // 1000, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (ms % 1000)


def stamp():
    return _fmt(_next_ms())


# --------------------------------------------------------------------------
# per-request mutation bookkeeping
# --------------------------------------------------------------------------

def begin_request():
    g.dirty = {}
    g.fresh = set()


def _dirty():
    if not hasattr(g, "dirty"):
        begin_request()
    return g.dirty


def _fresh():
    if not hasattr(g, "fresh"):
        begin_request()
    return g.fresh


def touch(row):
    """Mark `row` as mutated by this request."""
    if "version" not in row:
        return  # append-only ledger rows are never updated
    if row["id"] in _fresh():
        return  # rows created by this request already carry version 1
    _dirty()[row["id"]] = row


def set_field(row, key, value):
    """Assign `value` to `row[key]`, marking the row mutated when it changed."""
    if row.get(key) != value:
        row[key] = value
        touch(row)


def flush():
    """Apply one `updated_at` refresh and one `version` increment per dirty row."""
    dirty = _dirty()
    if not dirty:
        return
    ts = stamp()
    for row in dirty.values():
        row["updated_at"] = ts
        row["version"] = row["version"] + 1
    g.dirty = {}


def insert(table, row, versioned=True):
    ts = stamp()
    row["id"] = new_id()
    row["created_at"] = ts
    if versioned:
        row["updated_at"] = ts
        row["version"] = 1
    row["_seq"] = _next_seq()
    store[table][row["id"]] = row
    if versioned:
        _fresh().add(row["id"])
    return row


def public(row):
    """Serializable projection: internal bookkeeping keys are stripped."""
    return {k: v for k, v in row.items() if not k.startswith("_")}


def rows(table):
    """All rows of `table` in `created_at` ascending order (PRD §2.3)."""
    return sorted(store[table].values(), key=lambda r: (r["created_at"], r["_seq"]))


def get(table, row_id):
    if not isinstance(row_id, str):
        return None
    return store[table].get(row_id)


def by_case(table, case_id):
    return [r for r in rows(table) if r.get("case_id") == case_id]
