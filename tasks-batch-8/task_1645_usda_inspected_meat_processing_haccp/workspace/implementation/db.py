"""In-memory data store. Starts empty on every boot — no seeding."""

import uuid
from datetime import datetime, timezone


class Store:
    def __init__(self):
        # Logical clock: starts exactly at 2026-08-01T00:00:00Z
        self.logical_clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

        self.plants = {}
        self.haccp_plans = {}
        self.ccps = {}
        self.observations = {}
        self.deviations = {}
        self.inspector_shifts = {}
        self.production_days = {}
        self.carcass_lots = {}
        self.cut_records = {}
        self.pathogen_samples = {}
        self.label_approvals = {}
        self.finished_lots = {}
        self.humane_audits = {}
        self.noncompliance_records = {}
        self.recall_exercises = {}

        # Monotonic insertion counter used to break created_at ties
        self._seq_counter = 0

    def next_seq(self):
        self._seq_counter += 1
        return self._seq_counter

    def now(self):
        return self.logical_clock

    def now_iso(self):
        return iso_format(self.logical_clock)


def new_id():
    return str(uuid.uuid4())


def iso_format(dt):
    """ISO 8601 UTC with three fractional digits, e.g. 2026-08-01T00:00:00.000Z"""
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(s):
    """Parse an ISO 8601 timestamp into an aware datetime (UTC)."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# The single global store instance.
store = Store()
