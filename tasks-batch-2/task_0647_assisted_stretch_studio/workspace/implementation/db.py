"""In-memory data store. All state is wiped on every fresh process boot.

There is NO seeding, preloading, or hardcoding of entities here. Tests build
every entity via the declared API surface. The store only initializes the
ClockState singleton to its startup default (2026-04-01T00:00:00Z), which the
PRD §2.8 requires to exist before any clock-set call.
"""
import uuid
from datetime import datetime, timezone

# Logical-clock startup default (PRD §2.8 / scaffold ClockState.default).
CLOCK_DEFAULT_UTC = "2026-04-01T00:00:00Z"


class Store:
    def __init__(self):
        # Each collection is a dict keyed by server-minted UUID id.
        self.locations = {}
        self.flexologists = {}
        self.tables = {}
        self.services = {}
        self.members = {}
        self.memberships = {}
        self.credit_packs = {}
        self.bookings = {}
        self.recurring_series = {}
        self.add_ons = {}
        self.no_show_events = {}
        # Monotonic sequence to provide a stable creation order tie-break for
        # entities created within the same logical-clock instant.
        self._seq = 0
        # ClockState singleton — the ONLY entity that exists at boot.
        self.clock = {
            "id": new_id(),
            "current_utc": CLOCK_DEFAULT_UTC,
            "created_at": _wall_now_iso(),
        }

    def next_seq(self):
        self._seq += 1
        return self._seq


def new_id():
    return str(uuid.uuid4())


def _wall_now_iso():
    # Wall-clock timestamp for response meta / created_at on real records.
    # Three fractional digits, UTC, 'Z' suffix (PRD §2.4).
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


# Single global store instance for this process. Fresh on every boot.
store = Store()
