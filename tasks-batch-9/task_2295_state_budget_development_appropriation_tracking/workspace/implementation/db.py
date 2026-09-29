"""In-memory store.

Every collection is a plain dict keyed by the server-minted UUID.  The store is
empty on every boot: nothing is seeded, preloaded or hardcoded.  Tests build all
preconditions through the declared API surface.
"""

import itertools
import uuid

import clock

# --------------------------------------------------------------------------
# collections
# --------------------------------------------------------------------------
agencies = {}
budget_cycles = {}
revenue_forecasts = {}
agency_requests = {}
decision_packages = {}
performance_measures = {}
executive_recommendations = {}
reduction_scenarios = {}
appropriations = {}
committee_actions = {}
allotments = {}
budget_transfers = {}
expenditures = {}
federal_grants = {}
match_commitments = {}

_seq = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq)


# --------------------------------------------------------------------------
# row lifecycle
# --------------------------------------------------------------------------

def new_row(audited=True):
    """Create the common field prefix of a row.

    `audited` rows carry the full audit set (id/created_at/updated_at/version).
    The three thin record types (PerformanceMeasure, ReductionScenario,
    CommitteeAction) carry only id and created_at.
    """
    stamp = clock.now_iso()
    row = {"id": new_id(), "created_at": stamp}
    if audited:
        row["updated_at"] = stamp
        row["version"] = 1
    row["_seq"] = next_seq()
    return row


def touch(row):
    """Refresh updated_at and increment version by exactly 1."""
    if "updated_at" in row:
        row["updated_at"] = clock.now_iso()
    if "version" in row:
        row["version"] = row["version"] + 1


def apply_changes(row, updates):
    """Write `updates` onto `row`, counting as one mutation when anything moved."""
    changed = False
    for key, value in updates.items():
        if row.get(key) != value:
            changed = True
            break
    if not changed:
        return False
    row.update(updates)
    touch(row)
    return True


def serialize(row):
    """Public representation: every stored field except the private ones."""
    return {k: v for k, v in row.items() if not k.startswith("_")}


def sort_rows(rows):
    """Default listing order: created_at ascending, insertion order as tie-break."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
