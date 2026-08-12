"""In-memory data store and logical clock.

The store starts empty on every boot — no entity seeding of any kind.
"""

import uuid
from datetime import datetime, timezone


def parse_datetime(value):
    """Parse an ISO 8601 datetime string. Returns aware datetime (UTC if naive assumed)."""
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        raise ValueError("not a datetime string")
    s = value.strip()
    # Normalize Z suffix
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ValueError(f"malformed datetime: {value}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def format_datetime(dt: datetime) -> str:
    """ISO 8601 UTC with three fractional digits, Z suffix.

    Used for `created_at` / `updated_at`, which PRD §2.4 explicitly specifies
    as "an ISO 8601 UTC timestamp with three fractional digits"."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    ms = dt.microsecond // 1000
    return f"{base}.{ms:03d}Z"


def format_instant(dt: datetime) -> str:
    """Serialize a logical-clock instant exactly in the clock's own form.

    PRD §2.6 pins the clock's startup value to exactly `2026-05-01T00:00:00Z`
    (no fractional digits) and states that every recorded timestamp is taken
    from this clock, so clock-stamped fields (dispensed_at, loaned_at, due_at,
    period_end, past_due_since, ...) render without fractional digits unless
    the instant actually carries sub-second precision."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    if dt.microsecond:
        return f"{base}.{dt.microsecond // 1000:03d}Z"
    return f"{base}Z"


def whole_days_between(start: datetime, end: datetime) -> int:
    """Whole days between two instants (floor of total seconds / 86400)."""
    delta = end - start
    return int(delta.total_seconds() // 86400)


def new_id() -> str:
    return str(uuid.uuid4())


class Store:
    def __init__(self):
        self.clients = {}
        self.referrals = {}
        self.evaluations = {}
        self.device_models = {}
        self.device_units = {}
        self.device_orders = {}
        self.loan_agreements = {}
        self.training_plans = {}
        self.training_sessions = {}
        self.funding_authorizations = {}
        self.claims = {}
        self.repair_tickets = {}
        self.subscriptions = {}
        self.outcome_assessments = {}


class LogicalClock:
    """Logical clock. Startup default is exactly 2026-05-01T00:00:00Z.
    Never falls back to wall-clock time."""

    DEFAULT = "2026-05-01T00:00:00Z"

    def __init__(self):
        self._now = parse_datetime(self.DEFAULT)

    def now(self) -> datetime:
        return self._now

    def set(self, dt: datetime):
        self._now = dt

    def now_iso(self) -> str:
        return format_instant(self._now)


store = Store()
clock = LogicalClock()


def new_entity(common=True):
    """Return the common system fields for a fresh entity."""
    now_iso = format_datetime(clock.now())
    return {
        "id": new_id(),
        "created_at": now_iso,
        "updated_at": now_iso,
        "version": 1,
    }


def touch(entity: dict):
    """Refresh updated_at and bump version on a mutation."""
    entity["updated_at"] = format_datetime(clock.now())
    entity["version"] += 1
