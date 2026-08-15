"""In-memory data store. Fresh process => empty store; nothing is seeded.

The logical clock starts at exactly 2026-08-01T00:00:00Z and is only ever
moved by POST /dog-park/_clock/set_current_utc. No wall-clock fallback.
"""
from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.members = {}
        self.dogs = {}
        self.memberships = {}
        self.guest_passes = {}
        self.areas = {}
        self.closures = {}
        self.visits = {}
        self.incidents = {}
        self.waste_stations = {}
        self.seq = 0  # monotonic insertion counter; stable sort tiebreak
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.last_service_run_at = None   # logical time of previous nightly run
        self.last_service_run_seq = None  # insertion seq at that run (tiebreak)

    def next_seq(self):
        self.seq += 1
        return self.seq


store = Store()
