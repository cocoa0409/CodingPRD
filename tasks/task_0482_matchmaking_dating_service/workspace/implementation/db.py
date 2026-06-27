"""In-memory data store. Every byte of state is wiped on process restart.

NO seeding, preloading, or hardcoding of entities. All collections start empty;
tests build state via the API.
"""
import itertools
import uuid
from datetime import datetime, timezone


class DB:
    def __init__(self):
        self.reset()

    def reset(self):
        self.membership_plans = {}
        self.members = {}
        self.screenings = {}
        self.preferences = {}          # keyed by preference id
        self.memberships = {}
        self.freezes = {}
        self.introductions = {}
        self.feedback = {}
        self.date_events = {}
        self.coaching_sessions = {}
        self.background_checks = {}
        # monotonically increasing sequence to preserve creation order for sort
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = DB()


def new_id():
    return str(uuid.uuid4())


def iso_now_ms(dt=None):
    """Format a datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
