"""In-memory data store. Empty on every boot; no persistence, no seeding."""

import uuid
from datetime import datetime, timezone


def new_id():
    return str(uuid.uuid4())


def iso_now_wall():
    """Wall-clock timestamp for meta.api_request_timestamp (3 fractional digits, UTC)."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def iso_from_dt(dt):
    """Format a datetime as ISO 8601 UTC with three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class Store:
    def __init__(self):
        self.organizations = {}
        self.facilities = {}
        self.fee_schedules = {}
        self.allocation_windows = {}
        self.permit_applications = {}
        self.permits = {}
        self.field_closures = {}
        self.invoices = {}
        self.payments = {}
        self.strike_records = {}
        self.usage_ledgers = {}
        # Monotonic insertion sequence per entity id. The logical clock freezes
        # created_at for entities created in the same instant, so submission
        # order (the scaffold's explicit tie-break) is tracked here instead of
        # leaking a synthetic field into API payloads.
        self.seq_of = {}
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


store = Store()
