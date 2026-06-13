"""In-memory data store. Every byte of state lives here and is wiped on each
fresh process boot. No seeding, no disk persistence, no preloaded entities."""

import uuid
from datetime import datetime, timezone


class Clock:
    """Server's notion of 'now'. Defaults to real UTC; the test-driving
    endpoint POST /v1/_clock/set_current_utc can pin it to a supplied instant."""

    def __init__(self):
        self._fixed = None  # datetime (aware UTC) when pinned, else None

    def now(self):
        if self._fixed is not None:
            return self._fixed
        return datetime.now(timezone.utc)

    def set(self, dt):
        self._fixed = dt


class DB:
    """A bag of dicts, one per entity collection, each keyed by id."""

    def __init__(self):
        self.programs = {}
        self.state_rules = {}
        self.campaigns = {}
        self.customers = {}
        self.cards = {}
        self.ledger_entries = {}
        self.holds = {}
        self.redemptions = {}
        self.redemption_legs = {}
        self.bulk_orders = {}
        self.replacements = {}
        self.refunds = {}
        self.dormancy_waivers = {}
        self.clock = Clock()


# Singleton store + clock for the process lifetime.
db = DB()


def new_id():
    """Server-minted UUID with no type prefix."""
    return str(uuid.uuid4())


def now_iso(dt=None):
    """ISO 8601 UTC timestamp with exactly three fractional digits."""
    if dt is None:
        dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
