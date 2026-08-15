"""In-memory data store (PRD §2.4 logical clock, §2.5 common fields).

The store starts EMPTY on every boot. No seeding of any entity.
The logical clock starts at exactly 2026-08-01T00:00:00Z and only moves
through POST /_clock/set_current_utc (PRD §2.4).
"""
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.segments = {}        # id -> StreetSegment
        self.residents = {}       # id -> Resident
        self.requests = {}        # id -> TrafficCalmingRequest
        self.signatures = {}      # id -> PetitionSignature (live only; retracted are removed)
        self.studies = {}         # id -> SpeedStudy
        self.observations = {}    # id -> StudyObservation
        self.cycles = {}          # id -> FundingCycle
        self.plans = {}           # id -> TreatmentPlan
        self.ballots = {}         # id -> Ballot
        self.votes = {}           # id -> BallotVote
        self.work_orders = {}     # id -> InstallationWorkOrder
        self.removals = {}        # id -> RemovalRequest
        self.seq = 0              # global insertion counter for stable ordering
        # PRD §2.4: startup default is exactly 2026-08-01T00:00:00Z
        self.now = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

    def next_seq(self):
        self.seq += 1
        return self.seq

    def new_id(self):
        return str(uuid.uuid4())


store = Store()


def touch(entity):
    """PRD §2.8: every mutation refreshes updated_at and increments version."""
    entity["updated_at"] = store.now
    entity["version"] += 1
