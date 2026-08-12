"""In-memory store.  Plain dicts keyed by id; nothing is ever persisted to disk
and nothing is seeded at import time - every row is built by a declared endpoint.
"""

import uuid

from timeutil import clock, render_server

# ------------------------------------------------------------------ collections
members = {}
households = {}
subscriptions = {}
rooms = {}
items = {}
assets = {}
category_schedules = {}
appraisers = {}
appraisals = {}
policies = {}
packages = {}
package_lines = {}
claims = {}
claim_lines = {}
estate_plans = {}
allocations = {}
share_grants = {}

ALL_COLLECTIONS = (
    members,
    households,
    subscriptions,
    rooms,
    items,
    assets,
    category_schedules,
    appraisers,
    appraisals,
    policies,
    packages,
    package_lines,
    claims,
    claim_lines,
    estate_plans,
    allocations,
    share_grants,
)

_seq = [0]


def next_seq():
    _seq[0] += 1
    return _seq[0]


def new_id():
    return str(uuid.uuid4())


def new_token():
    return uuid.uuid4().hex


# --------------------------------------------------------- per-request context
_fallback_state = {}


def _state():
    try:
        from flask import g, has_request_context

        if has_request_context():
            if not hasattr(g, "_vault_state"):
                g._vault_state = {"bumped": set(), "created": set()}
            return g._vault_state
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
    """The one-bump rule of PRD 2.4: a row whose persisted state actually changed
    has its ``version`` incremented exactly once per API request, however many
    fields or cascade hops touched it.  A row created by this request stays at 1.
    """
    if row is None or "version" not in row:
        return
    st = _state()
    key = id(row)
    row["updated_at"] = clock.now_server_string()
    if key in st["created"] or key in st["bumped"]:
        return
    row["version"] += 1
    st["bumped"].add(key)


def new_row(collection, common_fields=True, **fields):
    """Create a row.  ``common_fields`` False = the three light entities
    (Asset, CategorySchedule, PackageLine) which carry only id and created_at.
    """
    row = {"id": new_id()}
    now = clock.now
    row["created_at"] = render_server(now)
    if common_fields:
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
    order (the append order of the collection), never by comparing ids."""
    return (row["_created_dt"], row["_seq"])


def ordered(rows):
    return sorted(rows, key=order_key)


def all_of(collection):
    return ordered(collection.values())
