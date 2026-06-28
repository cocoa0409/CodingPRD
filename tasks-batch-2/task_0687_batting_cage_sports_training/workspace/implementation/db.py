"""In-memory data store (PRD-wide: in-memory only, starts empty on every boot).

NO seeding. Every dict starts empty. Tests build all state via the API surface.
Keyed by id (server-minted UUID, no prefix).
"""
import uuid
from datetime import timezone


def new_id():
    return str(uuid.uuid4())


def iso_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.4)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class Store:
    def __init__(self):
        self.facilities = {}
        self.lanes = {}
        self.machines = {}
        self.maintenance = {}
        self.members = {}
        self.waivers = {}
        self.instructors = {}
        self.bookings = {}
        self.programs = {}
        self.enrollments = {}
        self._seq = 0  # monotonic insertion counter for stable created_at tie-break

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()
