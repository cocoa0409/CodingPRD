"""In-memory data store and the logical clock.

All state is process-local and wiped on every fresh boot. No seeding.
"""
import itertools
import uuid
from datetime import datetime, timezone

UTC = timezone.utc
DEFAULT_CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=UTC)
DEFAULT_CLOCK_ECHO = "2026-05-01T00:00:00Z"


class _State:
    def __init__(self):
        self.reset()

    def reset(self):
        self.clock = DEFAULT_CLOCK
        self.clock_echo = DEFAULT_CLOCK_ECHO
        self._seq = itertools.count(1)
        self.hosts = {}
        self.houses = {}
        self.rooms = {}
        self.members = {}
        self.applications = {}
        self.screening_reports = {}
        self.memberships = {}
        self.invoices = {}
        self.payments = {}
        self.incidents = {}
        self.tickets = {}
        self.payouts = {}

    def next_seq(self):
        return next(self._seq)


S = _State()


def new_id():
    return str(uuid.uuid4())


def clock_dt():
    return S.clock


def clock_date():
    return S.clock.date()
