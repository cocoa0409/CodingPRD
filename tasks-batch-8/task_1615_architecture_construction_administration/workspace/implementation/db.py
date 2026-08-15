"""In-memory data store for the CA API.

The store starts empty on every boot; no entity is ever seeded at startup.
All entities are constructed exclusively through the declared API surface.
"""

import uuid
from datetime import datetime, timezone, timedelta


class LogicalClock:
    """Server-held logical clock; never falls back to wall-clock time."""

    DEFAULT_ISO = "2026-08-01T00:00:00Z"

    def __init__(self):
        self._current = self._parse(self.DEFAULT_ISO)

    @staticmethod
    def _parse(iso: str) -> datetime:
        s = iso.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    def now(self) -> datetime:
        return self._current

    def set(self, iso: str) -> datetime:
        self._current = self._parse(iso)
        return self._current

    @staticmethod
    def fmt(dt: datetime) -> str:
        """Render as ISO 8601 UTC with exactly three fractional digits."""
        dt = dt.astimezone(timezone.utc)
        base = dt.strftime("%Y-%m-%dT%H:%M:%S")
        ms = dt.microsecond // 1000
        return f"{base}.{ms:03d}Z"

    @staticmethod
    def date_of(dt: datetime) -> str:
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%d")


clock = LogicalClock()


def new_id() -> str:
    return str(uuid.uuid4())


def now_iso() -> str:
    return clock.fmt(clock.now())


def today() -> str:
    return clock.date_of(clock.now())


def parse_date(s: str):
    return datetime.strptime(s, "%Y-%m-%d").date()


def add_days(date_str: str, days: int) -> str:
    d = parse_date(date_str) + timedelta(days=days)
    return d.strftime("%Y-%m-%d")


def add_days_to_dt(iso_ts: str, days: int) -> str:
    dt = LogicalClock._parse(iso_ts) + timedelta(days=days)
    return LogicalClock.fmt(dt)


# ---- entity stores: dict keyed by id ----

projects = {}
submittals = {}
site_visits = {}
field_reports = {}
rfis = {}
clarification_drawings = {}
payment_applications = {}
change_orders = {}
punch_list_items = {}
record_documents = {}
invoices = {}


STORES = {
    "project": projects,
    "submittal": submittals,
    "site_visit": site_visits,
    "field_report": field_reports,
    "rfi": rfis,
    "clarification_drawing": clarification_drawings,
    "payment_application": payment_applications,
    "change_order": change_orders,
    "punch_list_item": punch_list_items,
    "record_document": record_documents,
    "invoice": invoices,
}
