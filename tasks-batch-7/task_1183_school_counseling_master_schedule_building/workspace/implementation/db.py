"""In-memory data store. Starts completely empty on every boot — no seeding."""

from util import CLOCK_DEFAULT

# Entity tables: id -> record dict
terms = {}
students = {}
counselors = {}
teachers = {}
qualifications = {}
rooms = {}
courses = {}
course_requests = {}
sections = {}
schedule_entries = {}
change_requests = {}
appointments = {}
credit_audits = {}
recovery_placements = {}
rebalance_runs = {}


class LogicalClock:
    """Server-side logical clock for time-dependent rules (no-show lookback).

    Startup default is exactly 2026-05-01T00:00:00Z; once set it never falls
    back to wall-clock time.
    """

    def __init__(self):
        self.current_iso = CLOCK_DEFAULT

    def set(self, iso_string):
        self.current_iso = iso_string

    def now(self):
        from util import parse_iso
        return parse_iso(self.current_iso)


clock = LogicalClock()
