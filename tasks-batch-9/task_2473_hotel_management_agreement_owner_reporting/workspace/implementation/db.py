"""In-memory data store.

Every collection is a plain dict keyed by the row's server-minted UUID.  The
store starts EMPTY on every boot: no entity is ever seeded, preloaded or
hardcoded here.  Tests build all state through the declared API surface.

Rows carry an internal ``_seq`` insertion counter.  PRD §2.3 and §2.7 define
every ordering and accumulation rule in terms of ``created_at`` ascending; since
``created_at`` is stamped from the logical clock (which does not move between
requests), ``_seq`` is the tie-break that makes "created_at ascending" mean
insertion order deterministically.
"""

import itertools
import uuid

from flask import g

from timeutil import DEFAULT_CLOCK_ISO, fmt_iso, parse_iso

COLLECTIONS = (
    "agreements",
    "budgets",
    "variance_requests",
    "report_packages",
    "benchmarks",
    "charges",
    "fee_accruals",
    "distributions",
    "reserve_entries",
    "working_capital_calls",
    "performance_tests",
    "brand_disputes",
    "employment_claims",
)


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock_iso = DEFAULT_CLOCK_ISO
        self._counter = itertools.count(1)

    def next_seq(self):
        return next(self._counter)

    # -- logical clock -----------------------------------------------------
    @property
    def now_iso(self):
        return self.clock_iso

    @property
    def now(self):
        return parse_iso(self.clock_iso)

    def set_clock(self, moment):
        """Accept either a canonical ISO string or an aware datetime."""
        if isinstance(moment, str):
            self.clock_iso = fmt_iso(parse_iso(moment))
        else:
            self.clock_iso = fmt_iso(moment)


store = Store()


def new_id():
    return str(uuid.uuid4())


def touched_ids():
    ids = getattr(g, "_hm_touched", None)
    if ids is None:
        ids = set()
        g._hm_touched = ids
    return ids


def new_row(fields, common=True):
    """Create a row with its audit fields.

    A freshly created row is registered as already touched for this request, so
    that a cascade running later in the same request cannot bump a brand-new
    row past version 1.
    """
    row = {"id": new_id()}
    row.update(fields)
    row["created_at"] = store.now_iso
    if common:
        row["updated_at"] = store.now_iso
        row["version"] = 1
    row["_seq"] = store.next_seq()
    touched_ids().add(row["id"])
    return row


def touch(row):
    """Refresh updated_at and increment version -- once per row per request.

    PRD §2.7: every row a cascade mutates has its ``updated_at`` refreshed and
    its ``version`` incremented exactly as a direct write would, including rows
    the client never named.  A direct write bumps once per request, so a row
    mutated by several hops of one request still bumps once.
    """
    if row is None:
        return row
    ids = touched_ids()
    if row["id"] in ids:
        return row
    ids.add(row["id"])
    if "version" in row:
        row["version"] = row["version"] + 1
        row["updated_at"] = store.now_iso
    return row


def by_seq(rows):
    return sorted(rows, key=lambda r: r["_seq"])


def serialize(row):
    if row is None:
        return None
    return {k: v for k, v in row.items() if not k.startswith("_")}


def serialize_many(rows):
    return [serialize(r) for r in rows]
