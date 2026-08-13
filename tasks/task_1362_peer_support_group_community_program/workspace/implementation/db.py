"""In-memory data store and logical clock.

Storage is process-local only: plain dicts keyed by id. Every start.sh
re-invocation yields a completely fresh state. The logical clock starts at
the PRD-mandated default and never falls back to wall-clock time.
"""
from datetime import datetime, timezone

DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"


def _parse_default():
    return datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.programs = {}
        self.rooms = {}
        self.groups = {}
        self.sessions = {}
        self.facilitators = {}
        self.courses = {}
        self.completions = {}
        self.reviews = {}
        self.participants = {}
        self.agreements = {}
        self.enrollments = {}
        self.attendance = {}
        self.incidents = {}
        self.referrals = {}
        self.surveys = {}
        # insertion sequence for stable ordering / waitlist tiebreaks
        self.seq = 0
        # logical clock
        self._now = _parse_default()

    def next_seq(self):
        self.seq += 1
        return self.seq

    # ---- logical clock ----
    def now(self):
        return self._now

    def set_now(self, dt):
        self._now = dt


db = Store()
