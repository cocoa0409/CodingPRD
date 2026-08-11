"""In-memory store, monotonic UUID-shaped id minting and the logical clock.

G6 -- IN-MEMORY ONLY, NEVER SEEDED.  Every collection below starts empty on
every boot and is only ever populated by a declared endpoint handler.  There
is no seed function, no sqlite, no file write, no pickle and no /tmp cache
anywhere in this codebase.

G7 -- DETERMINISTIC ID ORDERING.  PRD 2.3 sorts every list by ``created_at``
ascending, and the logical clock (PRD 2.5) is coarse: a whole test fixture is
usually created at one single instant, so ``created_at`` ties constantly and
the tie-break is what fixes the order.  Random UUID4s would make that order
nondeterministic between boots.  Ids are therefore minted as UUID-shaped
strings whose leading 48 bits are a monotonically increasing counter, so
ascending id == creation order while the string stays a syntactically valid
UUID (version nibble 4, RFC-4122 variant bits).
"""

import itertools
import os
import threading

from timeutil import UTC, render_instant, try_parse_instant
from datetime import datetime

_ID_LOCK = threading.Lock()
_ID_COUNTER = itertools.count(1)


def new_id():
    """Mint a monotonic UUID-shaped identifier (see G7 above)."""
    with _ID_LOCK:
        n = next(_ID_COUNTER)
    hi = n & 0xFFFFFFFFFFFF                      # 48-bit monotonic counter
    rnd = int.from_bytes(os.urandom(8), "big")
    b = (rnd >> 48) & 0xFFF                      # 12 random bits, node-ish
    c = (rnd >> 32) & 0x0FFF                     # 12 random bits after version
    d = (rnd >> 16) & 0x3FFF                     # 14 random bits after variant
    e = rnd & 0xFFFFFFFFFFFF
    return "%08x-%04x-4%03x-%04x-%012x" % (
        (hi >> 16) & 0xFFFFFFFF,
        hi & 0xFFFF,
        c,
        0x8000 | d,
        (e ^ (b << 36)) & 0xFFFFFFFFFFFF,
    )


def new_token():
    """A single-use activation token."""
    return "act_" + os.urandom(12).hex().upper()


# --------------------------------------------------------------------------
# The logical clock (PRD 2.5)
# --------------------------------------------------------------------------
CLOCK_DEFAULT_UTC = "2026-05-01T00:00:00Z"


class LogicalClock(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self._dt = try_parse_instant(CLOCK_DEFAULT_UTC)
        self._raw = CLOCK_DEFAULT_UTC

    def now(self):
        """The clock's current instant as an aware UTC datetime."""
        return self._dt

    def now_iso(self):
        """The clock's current instant rendered in the ONE server style."""
        return render_instant(self._dt)

    def raw(self):
        """Verbatim echo of the instant string the caller last supplied."""
        return self._raw

    def set(self, dt, raw):
        self._dt = dt
        self._raw = raw


clock = LogicalClock()


# --------------------------------------------------------------------------
# Collections -- all empty at boot, never seeded
# --------------------------------------------------------------------------
class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.households = {}
        self.household_members = {}
        self.subscription_plans = {}
        self.subscriptions = {}
        self.device_catalog = {}
        self.devices = {}
        self.tickets = {}
        self.remote_sessions = {}
        self.technicians = {}
        self.visit_slots = {}
        self.visits = {}
        self.firmware_campaigns = {}
        self.firmware_rollouts = {}
        self.addon_orders = {}
        self.rma_cases = {}
        self.satisfaction_surveys = {}
        self.service_credits = {}


db = Store()


# --------------------------------------------------------------------------
# Row helpers
# --------------------------------------------------------------------------
def new_row(versioned=True):
    """A fresh row carrying the common system fields of PRD 2.4.

    ``versioned=False`` is used for the two configuration entities --
    SubscriptionPlan and DeviceCatalogEntry -- which carry only ``id`` and
    ``created_at`` and expose neither ``updated_at`` nor ``version``.
    """
    row = {"id": new_id(), "created_at": clock.now_iso()}
    if versioned:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    return row


def sort_rows(rows):
    """PRD 2.3: list results are always sorted by created_at ascending.  Ties
    -- which the coarse logical clock produces constantly -- break on the
    monotonic id, so the order is creation order and is deterministic."""
    return sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("id") or ""))


def created_dt(row):
    return try_parse_instant(row["created_at"])
