"""In-memory store.  Python dicts only -- nothing is ever written to disk and
NOTHING is seeded: every collection below starts empty on every boot and every
row is created only by a declared endpoint."""

import random
import threading

import timeutil

_LOCK = threading.RLock()


class _Ids:
    """Deterministic, monotonically ascending, UUID-shaped identifiers.

    The PRD makes `id` a load-bearing list tie-break while the logical clock
    puts many rows at one created_at, so random UUIDs would make same-instant
    ordering nondeterministic.  A 48-bit creation counter occupies the high
    bits, so ids sort in creation order; the remaining bits are random and the
    string is a syntactically valid version-4 UUID.
    """

    def __init__(self):
        self._counter = 0

    def reset(self):
        self._counter = 0

    def mint(self):
        self._counter += 1
        high = "%012x" % (self._counter & 0xFFFFFFFFFFFF)
        rand_a = "%03x" % random.getrandbits(12)
        variant = random.choice("89ab")
        rand_b = "%03x" % random.getrandbits(12)
        rand_c = "%012x" % random.getrandbits(48)
        return "%s-%s-4%s-%s%s-%s" % (
            high[:8],
            high[8:12],
            rand_a,
            variant,
            rand_b,
            rand_c,
        )


IDS = _Ids()

COLLECTIONS = (
    "clients",
    "state_rules",
    "legal_entities",
    "beneficial_owners",
    "name_clearances",
    "registrations",
    "certificates",
    "appointments",
    "obligations",
    "reminders",
    "filings",
    "payments",
    "allocations",
    "sop_documents",
    "sop_events",
    "boi_reports",
    "reinstatement_cases",
)


class Store:
    def __init__(self):
        self._seq = 0
        for name in COLLECTIONS:
            setattr(self, name, {})

    def reset(self):
        self._seq = 0
        for name in COLLECTIONS:
            setattr(self, name, {})

    def next_seq(self):
        self._seq += 1
        return self._seq


DB = Store()


def lock():
    return _LOCK


def new_row(collection, fields, versioned=True):
    """Create a row with its system-managed identity / audit fields.

    `created_at` and `updated_at` are stamped from the logical clock; `version`
    starts at 1.  The three lean types (GoodStandingCertificate,
    PaymentAllocation, SopEscalationEvent) pass versioned=False and get only
    `id` and `created_at` (PRD 2.4).
    """
    instant = timeutil.now()
    row = dict(fields)
    row["id"] = IDS.mint()
    row["created_at"] = instant
    row["_seq"] = DB.next_seq()
    if versioned:
        row["updated_at"] = instant
        row["version"] = 1
    collection[row["id"]] = row
    return row


def touch(row):
    """Refresh updated_at and bump version by exactly 1 (PRD 2.4 / 2.12)."""
    row["updated_at"] = timeutil.now()
    row["version"] = row.get("version", 1) + 1
    return row


def ordered(rows):
    """Default list ordering: ascending created_at, then insertion order.

    ADJUDICATION OF FRICTION 2 -- list tie-break.  PRD 2.3 states that "rows
    sharing the same created_at value are returned in the order they were
    created -- insertion order".  Reading: INSERTION ORDER, carried by the
    monotone `_seq` counter.  Because ids are minted in ascending creation
    order too, the insertion-order reading and the by-id reading coincide, so
    no declared behaviour is lost either way.
    """
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
