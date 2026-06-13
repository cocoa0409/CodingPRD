"""In-memory data store. Starts EMPTY on every boot. No seeding, no disk.

Every collection is a plain dict keyed by the entity's UUID id. A monotonic
`_seq` is stamped on each record so that list ordering and FIFO tie-breaks are
deterministic. The logical business clock (`current_clock`) drives all
time-dependent logic (lot expiry, blackout/promotion windows, birthday, tier
trailing window); it defaults to real wall time until a test sets it.
"""
import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        # one dict per entity collection, keyed by id
        self.programs = {}
        self.tiers = {}
        self.members = {}
        self.lots = {}
        self.transactions = {}
        self.promotions = {}
        self.rewards = {}
        self.redemptions = {}
        self.redemption_lines = {}
        self.referrals = {}
        self.partners = {}
        self.blackouts = {}
        self.transfers = {}
        self.purchase_events = {}

        # monotonically increasing sequence used as deterministic creation
        # order (so equal created_at timestamps still sort by insertion order,
        # and FIFO burn tie-breaks fall back to lot id only when truly equal).
        self._seq = 0

        # logical UTC clock. Defaults to real wall clock until explicitly set
        # by the test-driving /_clock endpoints.
        self.current_clock = datetime.now(timezone.utc)

    def next_seq(self):
        self._seq += 1
        return self._seq

    def new_id(self):
        return str(uuid.uuid4())

    def clock_iso(self):
        """Current logical clock as ISO 8601 UTC with three fractional digits.

        Resource created_at / updated_at and all derived time fields
        (lot expires_at, etc.) are stamped from the logical clock so that
        time-machine driven tests (set/advance + sweep) reason consistently:
        a lot minted "now" and expired after N months tracks the same clock
        the sweep checks against.
        """
        dt = self.current_clock.astimezone(timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"

    def stamp_create(self, rec, common_fields=True):
        """Populate system fields on create.

        common_fields=True  -> id, created_at, updated_at, version (=1), _seq
        common_fields=False -> id, created_at, _seq only (append-only / line records)
        """
        rec["id"] = self.new_id()
        rec["_seq"] = self.next_seq()
        ts = self.clock_iso()
        rec["created_at"] = ts
        if common_fields:
            rec["updated_at"] = ts
            rec["version"] = 1
        return rec

    def touch(self, rec):
        """Refresh updated_at and bump version on mutation."""
        if "version" in rec:
            rec["version"] += 1
        if "updated_at" in rec:
            rec["updated_at"] = self.clock_iso()
        return rec


db = Store()
