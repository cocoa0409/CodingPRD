"""In-memory store. Nothing is persisted and nothing is seeded at startup."""

import threading
import uuid
from datetime import datetime, timezone

# PRD 2.5: before any /_clock/set_current_utc call the logical clock reads
# exactly this instant, and it never falls back to wall-clock time.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

KINDS = (
    "DraftCycle",
    "Club",
    "Prospect",
    "EligibilityWaiver",
    "MedicalStation",
    "InterviewRoom",
    "CombineBooking",
    "MedicalEvaluation",
    "MedicalRecordShare",
    "DraftPick",
    "PickTrade",
    "CompensatoryClaim",
    "PlayerContract",
)


class DB(object):
    def __init__(self):
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        self.draft_cycles = {}
        self.clubs = {}
        self.prospects = {}
        self.eligibility_waivers = {}
        self.medical_stations = {}
        self.interview_rooms = {}
        self.combine_bookings = {}
        self.medical_evaluations = {}
        self.medical_record_shares = {}
        self.draft_picks = {}
        self.pick_trades = {}
        self.compensatory_claims = {}
        self.player_contracts = {}
        self.now = DEFAULT_CLOCK
        self._seq = 0

    def stores(self):
        return (
            self.draft_cycles,
            self.clubs,
            self.prospects,
            self.eligibility_waivers,
            self.medical_stations,
            self.interview_rooms,
            self.combine_bookings,
            self.medical_evaluations,
            self.medical_record_shares,
            self.draft_picks,
            self.pick_trades,
            self.compensatory_claims,
            self.player_contracts,
        )

    def next_seq(self):
        self._seq += 1
        return self._seq

    def insert(self, store, kind, fields):
        rec = dict(fields)
        rec["id"] = str(uuid.uuid4())
        rec["_kind"] = kind
        rec["_seq"] = self.next_seq()
        rec["created_at"] = self.now
        rec["updated_at"] = self.now
        rec["version"] = 1
        store[rec["id"]] = rec
        return rec


db = DB()


def sort_key(rec):
    """created_at ASC with a deterministic tie-break on insertion order."""
    return (rec["created_at"], rec["_seq"])


def by_created(records):
    return sorted(records, key=sort_key)
