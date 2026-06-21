"""In-memory data store. Starts empty on every boot; no seeding."""
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        # entity collections, each a dict keyed by id
        self.leagues = {}
        self.divisions = {}
        self.families = {}
        self.players = {}
        self.teams = {}
        self.draft_picks = {}
        self.fields = {}
        self.referees = {}
        self.games = {}
        self.assignments = {}
        self.volunteer_commitments = {}
        # logical clock for window checks; None means use real wall clock
        self.clock = None

    def now(self):
        if self.clock is not None:
            return self.clock
        return datetime.now(timezone.utc)


store = Store()


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """ISO 8601 UTC with exactly three fractional digits."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
