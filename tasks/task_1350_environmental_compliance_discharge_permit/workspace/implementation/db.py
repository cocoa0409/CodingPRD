"""In-memory data store. Store starts empty on every boot. No seeding."""

from datetime import datetime, timezone

# Entity stores keyed by id
permits = {}
outfalls = {}
effluent_limits = {}
sampling_events = {}
custody_records = {}
lab_results = {}
exceedances = {}
dmrs = {}
swppp_plans = {}
inspections = {}
corrective_actions = {}
renewal_applications = {}
consent_orders = {}
penalty_payments = {}
audit_entries = []  # ordered list, hash-chained

# Per-sample custody sequence counter: sampling_event_id -> next sequence_index (1-based)
custody_seq = {}

# Insertion counters used as tie-breakers for created_at ordering
_insert_counter = [0]


def next_insert_seq():
    _insert_counter[0] += 1
    return _insert_counter[0]


class LogicalClock:
    """Server-held logical clock; starts at exactly 2026-08-01T00:00:00Z."""

    def __init__(self):
        self._now = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

    def now(self):
        return self._now

    def set(self, dt):
        self._now = dt


clock = LogicalClock()
