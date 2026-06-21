"""In-memory data store + logical clock.

All state lives in module-level dicts keyed by id. The store starts EMPTY on
every boot — nothing is seeded, preloaded, or hardcoded. Each start.sh
re-invocation imports a fresh module and therefore a fresh, empty store.

The logical clock (PRD §3.3): at server startup it reads exactly
2026-01-01T00:00:00Z and never falls back to wall-clock time.
"""
import uuid
from datetime import datetime, timezone


CLOCK_DEFAULT = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.creators = {}
        self.tiers = {}
        self.patrons = {}
        self.pledges = {}
        self.charges = {}
        self.posts = {}
        self.post_accesses = {}
        self.conversations = {}
        self.messages = {}
        self.payouts = {}
        self.win_back_offers = {}
        # Monotonic counter to keep created_at ordering deterministic and stable
        # even when many records are created within the same millisecond.
        self._seq = 0
        # Logical clock.
        self.clock = CLOCK_DEFAULT

    def next_seq(self):
        self._seq += 1
        return self._seq

    def now(self):
        """Logical clock instant (used for cycle_anchor_date, grace, etc.)."""
        return self.clock


db = Store()


def new_id():
    # Server-minted UUID with no type prefix (PRD §2.4).
    return str(uuid.uuid4())


def iso_millis(dt):
    """Render a datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def wall_now():
    """Real-world UTC instant — used only for created_at/updated_at audit fields."""
    return datetime.now(timezone.utc)
