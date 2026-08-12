"""In-memory storage (plain dicts), the logical clock, and id minting.

NOTHING is seeded here.  Every dict below starts empty on every boot; every
entity a client needs is created through a declared endpoint.
"""

import random

from .constants import LOGICAL_CLOCK_DEFAULT_UTC
from . import timeutil as T

# --------------------------------------------------------------------------
# id minting.  Ids are valid UUID strings whose HIGH bits carry a monotonic
# creation counter, so ascending `id` == creation order.  This is a formatting
# choice only - no data is seeded and no id is hardcoded.
# --------------------------------------------------------------------------
_counter = 0


def _next_seq():
    global _counter
    _counter += 1
    return _counter


def mint_id():
    seq = _next_seq()
    hi = seq & 0xFFFFFFFF
    mid = (seq >> 32) & 0xFFFF
    r3 = random.getrandbits(12)
    r4 = random.getrandbits(12)
    r5 = random.getrandbits(48)
    variant = random.choice("89ab")
    return "%08x-%04x-4%03x-%s%03x-%012x" % (hi, mid, r3, variant, r4, r5)


# --------------------------------------------------------------------------
# logical clock
# --------------------------------------------------------------------------
class _Clock:
    def __init__(self):
        self.reset()

    def reset(self):
        self.ts = T.echoed(LOGICAL_CLOCK_DEFAULT_UTC)

    def now(self):
        """The current logical instant (aware UTC datetime)."""
        return self.ts.dt

    def raw(self):
        """The exact string POST /_clock/set_current_utc must echo back."""
        return self.ts.raw

    def set(self, raw_value):
        self.ts = T.echoed(raw_value)

    def stamp(self):
        """A freshly minted server timestamp at the logical clock."""
        return T.minted(self.ts.dt)


clock = _Clock()


# --------------------------------------------------------------------------
# tables
# --------------------------------------------------------------------------
TABLES = [
    "riders", "condition_policies", "medical_releases", "assessments", "horses",
    "volunteers", "volunteer_qualifications", "instructors", "sessions",
    "crew_assignments", "goals", "progress_notes", "grants", "scholarship_awards",
    "charges", "funding_allocations", "incidents", "period_reports",
]

db = {name: {} for name in TABLES}


def reset_all():
    for name in TABLES:
        db[name].clear()
    clock.reset()


def new_row(table, versioned=True):
    """Allocate a row with the scaffold's common fields."""
    stamp = clock.stamp()
    row = {"id": mint_id(), "created_at": stamp, "_seq": _counter}
    if versioned:
        row["updated_at"] = stamp
        row["version"] = 1
    db[table][row["id"]] = row
    return row


def touch(row):
    """§2.4 - one mutation bumps version by exactly 1 and refreshes updated_at."""
    if "version" in row:
        row["version"] += 1
        row["updated_at"] = clock.stamp()
    return row


def get(table, row_id):
    if not isinstance(row_id, str):
        return None
    return db[table].get(row_id)


def all_rows(table):
    """Every row of a table in created_at ascending order (§2.3).

    The tie-break is the monotonic creation sequence, which under a coarse
    logical clock is the only thing that distinguishes rows minted at the same
    instant.  It agrees with ascending `id` by construction.
    """
    return sorted(db[table].values(), key=lambda r: (r["created_at"].dt, r["_seq"]))
