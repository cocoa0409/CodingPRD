"""In-memory data store and logical clock. Wiped on every process start."""
from util import parse_dt, new_uuid, render_system_ts

DEFAULT_CLOCK = "2026-05-01T00:00:00Z"


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.boards = {}
        self.seats = {}
        self.vacancies = {}
        self.applicants = {}
        self.applications = {}
        self.appointments = {}
        self.terms = {}
        self.meetings = {}
        self.attendance = {}
        self.disclosures = {}
        self.removals = {}
        self.reappointments = {}
        self._clock = parse_dt(DEFAULT_CLOCK)
        self._seq = 0

    def now(self):
        return self._clock

    def set_clock(self, dt):
        self._clock = dt

    def next_seq(self):
        self._seq += 1
        return self._seq

    def new_record(self, common=True):
        """Create a base record dict with system fields set from the logical clock."""
        ts = render_system_ts(self._clock)
        rec = {
            "id": new_uuid(),
            "created_at": ts,
            "_seq": self.next_seq(),
        }
        if common:
            rec["updated_at"] = ts
            rec["version"] = 1
        return rec

    def touch(self, rec):
        """Mark a mutation: refresh updated_at, bump version."""
        rec["updated_at"] = render_system_ts(self._clock)
        rec["version"] = rec.get("version", 1) + 1


store = Store()
