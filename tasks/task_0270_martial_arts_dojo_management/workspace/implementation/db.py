"""In-memory data store.

Dicts keyed by id. Starts EMPTY on every process boot — NO seeding, NO
preloaded entities. Every entity is created by tests through the declared API
surface.

A logical clock (PRD §3.8) backs overdue sweeps and tournament-date gating. It
is driven by POST /dojo/_clock/advance; until set it tracks real wall-clock UTC.
"""
import uuid
from datetime import datetime, timezone


class DB:
    def __init__(self):
        # One dict per entity collection, keyed by id.
        self.programs = {}
        self.belt_ranks = {}
        self.families = {}
        self.members = {}
        self.instructors = {}
        self.enrollments = {}
        self.class_sessions = {}
        self.attendances = {}
        self.promotion_tests = {}
        self.contracts = {}
        self.invoices = {}
        self.private_lessons = {}
        self.tournament_registrations = {}
        self.pro_shop_orders = {}
        # Logical clock: None means follow real wall-clock UTC.
        self._clock = None

    # ---- ids & timestamps -------------------------------------------------
    @staticmethod
    def new_id():
        return str(uuid.uuid4())

    def now(self):
        """Current logical UTC instant (timezone-aware datetime)."""
        if self._clock is not None:
            return self._clock
        return datetime.now(timezone.utc)

    def now_iso(self):
        dt = self.now()
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"

    def set_clock(self, dt):
        self._clock = dt


db = DB()
