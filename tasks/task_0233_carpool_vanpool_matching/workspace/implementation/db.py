"""In-memory data store. Wiped on every process boot — no persistence."""
import itertools
import uuid
from datetime import datetime, timezone

# Monotonic sequence used to break created_at ties deterministically and to
# order append-only ledgers/events by true insertion order.
_seq = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq)


class Store:
    """Holds every entity collection keyed by id, plus the simulation clock."""

    def __init__(self):
        self.employer_programs = {}
        self.members = {}
        self.vehicles = {}
        self.pools = {}
        self.match_requests = {}
        self.memberships = {}
        self.trips = {}
        self.reservations = {}
        self.grh_claims = {}
        self.subsidy_ledger_entries = {}
        self.reliability_events = {}
        # Simulation clock: defaults to wall-clock now until /_clock/set is called.
        self.clock_now = datetime.now(timezone.utc)

    # ---- match-request exclusion sets (rejected pools) --------------------
    # Stored out-of-band so they never appear in the serialized resource.
    _exclusions = None

    def exclusion_set(self, match_request_id):
        if self._exclusions is None:
            self._exclusions = {}
        return self._exclusions.setdefault(match_request_id, set())


db = Store()
