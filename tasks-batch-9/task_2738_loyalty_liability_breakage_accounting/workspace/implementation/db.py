"""In-memory data store.

Every table is a plain dict keyed by the resource id.  The store starts empty on
every boot: nothing is seeded, preloaded or hardcoded here.  A monotonic
insertion counter (`_seq`) is kept on every row because the logical clock does
not advance on its own, so `created_at` ties are the norm and every list
ordering the PRD pins on `created_at` needs a deterministic tie-break.
"""
import threading
import uuid

from util import clock

lock = threading.RLock()


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.programs = {}
        self.state_expiry_rules = {}
        self.cohorts = {}
        self.members = {}
        self.periods = {}
        self.partner_agreements = {}
        self.point_lots = {}
        self.redemption_events = {}
        self.allocations = {}
        self.breakage_estimates = {}
        self.settlement_statements = {}
        self.change_orders = {}
        self.counter = 0


store = Store()


def next_seq():
    store.counter += 1
    return store.counter


def new_id():
    return str(uuid.uuid4())


def new_record(table, fields):
    """Create a row carrying the full common-field set and register it."""
    now = clock.now()
    rec = dict(fields)
    rec["id"] = new_id()
    rec["created_at"] = now
    rec["updated_at"] = now
    rec["version"] = 1
    rec["_seq"] = next_seq()
    table[rec["id"]] = rec
    return rec


def new_allocation(fields):
    """RedemptionAllocation rows are append-only: no updated_at, no version."""
    rec = dict(fields)
    rec["id"] = new_id()
    rec["created_at"] = clock.now()
    rec["_seq"] = next_seq()
    store.allocations[rec["id"]] = rec
    return rec


def touch(rec):
    """Record a mutation: refresh updated_at and increment version by one."""
    rec["updated_at"] = clock.now()
    rec["version"] = rec["version"] + 1


def creation_order(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def rows(table, predicate=None):
    """All rows of a table in created_at ascending (insertion tie-broken) order."""
    out = [r for r in table.values() if predicate is None or predicate(r)]
    return creation_order(out)


def issuance_order(lots):
    """FIFO lot order: issued_at ascending, then created_at ascending."""
    return sorted(lots, key=lambda r: (r["issued_at"], r["created_at"], r["_seq"]))


def cohort_order(cohorts):
    """Cohort cascade order: enrollment_start_date then created_at ascending."""
    return sorted(
        cohorts,
        key=lambda r: (r["enrollment_start_date"], r["created_at"], r["_seq"]),
    )


def allocation_order(allocs):
    """Journal order: allocation_seq ascending, then created_at ascending."""
    return sorted(allocs, key=lambda r: (r["allocation_seq"], r["created_at"], r["_seq"]))


# --- typed lookups ----------------------------------------------------------

def program_lots(program_id):
    """Every PointLot whose holder belongs to this programme."""
    out = []
    for lot in store.point_lots.values():
        member = store.members.get(lot["member_id"])
        if member is not None and member["program_id"] == program_id:
            out.append(lot)
    return creation_order(out)


def member_lots(member_id):
    return rows(store.point_lots, lambda l: l["member_id"] == member_id)


def program_periods(program_id):
    return rows(store.periods, lambda p: p["program_id"] == program_id)


def program_cohorts(program_id):
    return rows(store.cohorts, lambda c: c["program_id"] == program_id)


def program_of_member(member):
    return store.programs.get(member["program_id"])
