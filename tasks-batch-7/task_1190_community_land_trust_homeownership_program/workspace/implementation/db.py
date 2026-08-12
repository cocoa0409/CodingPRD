"""In-memory data store and logical clock.

Storage is process-local dicts keyed by id. No disk persistence of any kind.
The store starts completely empty on every boot; nothing is seeded.
"""
from datetime import datetime, timezone

UTC = timezone.utc

# Logical clock default: 2026-05-01T00:00:00Z (PRD section 2.9). The clock
# MUST NOT fall back to real wall-clock time.
_DEFAULT_NOW = datetime(2026, 5, 1, 0, 0, 0, tzinfo=UTC)


class _Store:
    def __init__(self):
        self.programs = {}
        self.households = {}
        self.certs = {}
        self.courses = {}
        self.completions = {}
        self.units = {}
        self.leases = {}
        self.fees = {}
        self.notices = {}
        self.inspections = {}
        self.waitlist = {}
        self.listings = {}
        self.refis = {}


store = _Store()

_clock = {"now": _DEFAULT_NOW}


def get_now():
    return _clock["now"]


def set_now(dt):
    _clock["now"] = dt
