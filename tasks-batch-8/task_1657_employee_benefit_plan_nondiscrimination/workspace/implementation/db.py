"""In-memory data store and logical clock.

All storage is process-local Python dicts keyed by id. Nothing is persisted
to disk and nothing is seeded at startup: the store begins empty on every
boot and every entity is constructed via the declared API surface.
"""

from datetime import datetime, timezone


class Store:
    def __init__(self):
        self.employers = {}
        self.plans = {}
        self.plan_versions = {}
        self.plan_years = {}
        self.census_employees = {}
        self.compensation_records = {}
        self.contributions = {}
        self.regulatory_limits = {}
        self.safe_harbor_elections = {}
        self.safe_harbor_notices = {}
        self.test_runs = {}
        self.test_result_lines = {}
        self.corrections = {}


store = Store()


def _parse_clock_iso(value):
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class LogicalClock:
    """Server logical clock. Reads exactly the startup default until set.

    Keeps the verbatim ISO reading alongside the parsed instant: workflow
    stamps (a notice's distributed_at, a correction's executed_at) copy the
    clock's reading exactly, so the startup default stamps as
    "2026-08-01T00:00:00Z" — precisely what §2.5 says the clock reads.
    """

    DEFAULT_ISO = "2026-08-01T00:00:00Z"

    def __init__(self):
        self._now = _parse_clock_iso(self.DEFAULT_ISO)
        self._now_str = self.DEFAULT_ISO

    def now(self):
        return self._now

    def now_iso(self):
        return self._now_str

    def set(self, value):
        self._now = _parse_clock_iso(value)
        self._now_str = value.strip() if isinstance(value, str) else str(value)
        return self._now


clock = LogicalClock()
