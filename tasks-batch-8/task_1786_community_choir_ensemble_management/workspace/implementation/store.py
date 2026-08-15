"""In-memory store.  Plain dicts keyed by id; nothing is persisted to disk and
nothing is seeded at import time - every row is built by a declared endpoint.
The store starts empty on every boot.
"""

import uuid

from timeutil import clock, render_server

# ------------------------------------------------------------------ collections
seasons = {}
sections = {}
members = {}
auditions = {}
dues_invoices = {}
dues_payments = {}
scholarship_grants = {}
rehearsals = {}
attendance_records = {}
music_scores = {}
score_checkouts = {}
venues = {}
concerts = {}
venue_bookings = {}
program_pieces = {}
guest_contracts = {}
tours = {}
tour_registrations = {}
committees = {}
pledges = {}

_seq = [0]


def next_seq():
    _seq[0] += 1
    return _seq[0]


def new_id():
    return str(uuid.uuid4())


# --------------------------------------------------------- per-request context
# The one-bump rule (PRD 2.5): a row whose persisted state changed has its
# ``version`` incremented exactly once per API request, however many fields or
# cascade hops touched it.  A row created by this request stays at version 1.
_fallback_state = {}


def _state():
    try:
        from flask import g, has_request_context

        if has_request_context():
            if not hasattr(g, "_choir_state"):
                g._choir_state = {"bumped": set(), "created": set()}
            return g._choir_state
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
    if row is None or "version" not in row:
        return
    st = _state()
    key = id(row)
    row["updated_at"] = clock.now_server_string()
    if key in st["created"] or key in st["bumped"]:
        return
    row["version"] += 1
    st["bumped"].add(key)


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
    """PRD 2.3 ordering: created_at ascending, ties broken by creation order."""
    return (row["_created_dt"], row["_seq"])


def ordered(rows):
    return sorted(rows, key=order_key)


def all_of(collection):
    return ordered(collection.values())
