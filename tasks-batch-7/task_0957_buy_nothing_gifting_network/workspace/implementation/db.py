from datetime import datetime, timezone

# The logical clock starts at exactly 2026-05-01T00:00:00Z and never falls
# back to wall-clock time; it moves only via POST /v1/_clock/set_current_utc.
CLOCK_START = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    """In-memory store. A fresh process boots with every collection empty —
    no seeding of any entity at startup."""

    def __init__(self):
        self.clock = CLOCK_START
        self.members = {}
        self.groups = {}
        self.memberships = {}
        self.posts = {}
        self.claims = {}
        self.plans = {}
        self.wishlists = {}
        self.alerts = {}
        self.reports = {}
        self.actions = {}
        self.events = {}
        self.seq = 0  # global insertion counter, stabilizes list ordering

    def next_seq(self):
        self.seq += 1
        return self.seq


store = Store()


def now():
    return store.clock
