"""In-memory store.  Plain dicts keyed by id; nothing is ever persisted to disk
and nothing is seeded at import time - every row is built by a declared endpoint.

Rows are plain dicts.  Fields whose names start with ``_`` are internal
(parsed datetimes, creation sequence) and are never serialized.

Version discipline (PRD 2.5): every resource carries ``version`` starting at 1
at creation; each mutation refreshes ``updated_at`` and increments ``version``.
A row touched several times within one API request (e.g. by a cascade) is
bumped exactly once per request.
"""

import uuid

from clock import clock, render_server

# ------------------------------------------------------------------ collections
organizations = {}
rooms = {}
terms = {}
academic_blocks = {}
scheduling_runs = {}
event_reservations = {}
service_orders = {}
service_crews = {}
invoices = {}
access_grants = {}

ALL_COLLECTIONS = (
    organizations,
    rooms,
    terms,
    academic_blocks,
    scheduling_runs,
    event_reservations,
    service_orders,
    service_crews,
    invoices,
    access_grants,
)

_seq = [0]


def next_seq():
    _seq[0] += 1
    return _seq[0]


def new_id():
    return str(uuid.uuid4())


# --------------------------------------------------------- per-request context
_fallback_state = {}


def _state():
    try:
        from flask import g, has_request_context

        if has_request_context():
            if not hasattr(g, "_campus_state"):
                g._campus_state = {"bumped": set(), "created": set()}
            return g._campus_state
    except Exception:
        pass
    if not _fallback_state:
        _fallback_state.update({"bumped": set(), "created": set()})
    return _fallback_state


def begin_request():
    st = _state()
    st["bumped"] = set()
    st["created"] = set()


def _mark_created(row):
    _state()["created"].add(id(row))


def touch(row):
    """Refresh ``updated_at`` and increment ``version`` exactly once per request
    per row; a row created by this request stays at version 1."""
    if row is None or "version" not in row:
        return
    st = _state()
    key = id(row)
    row["updated_at"] = clock.now_server_string()
    if key in st["created"] or key in st["bumped"]:
        return
    row["version"] += 1
    st["bumped"].add(key)


def set_fields(row, **fields):
    """Assign fields and touch only when a persisted value actually changed."""
    changed = False
    for name, value in fields.items():
        if row.get(name) != value:
            row[name] = value
            changed = True
    if changed:
        touch(row)


def new_row(collection, **fields):
    row = {"id": new_id()}
    now = clock.now
    row["created_at"] = render_server(now)
    row["updated_at"] = render_server(now)
    row["version"] = 1
    row["_created_dt"] = now
    row["_seq"] = next_seq()
    row.update(fields)
    collection[row["id"]] = row
    _mark_created(row)
    return row


def order_key(row):
    """PRD 2.3 global ordering: created_at ascending, ties broken by creation
    order (never by comparing ids)."""
    return (row["_created_dt"], row["_seq"])


def ordered(rows):
    return sorted(rows, key=order_key)


def all_of(collection):
    return ordered(collection.values())
