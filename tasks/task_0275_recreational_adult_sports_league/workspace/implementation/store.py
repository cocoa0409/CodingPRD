"""In-memory data store. Wiped on every process boot (no persistence)."""
import itertools
import uuid
from datetime import datetime, timezone


def now_iso():
    """ISO 8601 UTC timestamp with three fractional digits and trailing Z."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_id():
    return str(uuid.uuid4())


class Store:
    def __init__(self):
        # Each collection: id -> record dict.
        self.seasons = {}
        self.divisions = {}
        self.teams = {}
        self.players = {}
        self.roster_entries = {}
        self.venues = {}
        self.referees = {}
        self.games = {}
        self.referee_assignments = {}
        self.payments = {}
        self.conduct_reports = {}
        # Monotonic counter to give every record a stable insertion order
        # for created_at-ascending tie-breaks (created_at strings can collide).
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = Store()
