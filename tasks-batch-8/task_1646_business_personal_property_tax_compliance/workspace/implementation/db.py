"""In-memory data store. All state lives in module-level dicts on a Store
instance; app.py constructs one Store() per process. Because the harness
restarts the server via start.sh before every test, each boot yields a
completely fresh, empty store. Nothing is persisted to disk."""

import uuid
from datetime import datetime, timezone, timedelta


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        # Entity tables, keyed by id
        self.clients = {}
        self.operators = {}
        self.jurisdictions = {}
        self.class_rules = {}
        self.assets = {}
        self.disposals = {}
        self.renditions = {}
        self.extensions = {}
        self.notices = {}
        self.appeals = {}
        self.bills = {}
        self.exemptions = {}
        self.abatements = {}
        self.forecasts = {}
        self.audit_events = {}

        # The logical clock — never wall-clock time
        self.clock = CLOCK_START

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def new_id():
        return str(uuid.uuid4())

    @staticmethod
    def now_iso():
        """Wall-clock timestamp for created_at/updated_at metadata (ISO 8601
        UTC, three fractional digits). Note: this is a *record* timestamp,
        not the business logical clock."""
        dt = datetime.now(timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"

    def clock_date(self):
        """Date part of the current logical clock."""
        return self.clock.date()

    def clock_iso(self):
        """Current logical clock as ISO 8601 UTC with three fractional digits."""
        dt = self.clock
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
