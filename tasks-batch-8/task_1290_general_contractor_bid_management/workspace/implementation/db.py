"""In-memory data store. The store starts EMPTY on every boot — no seeding."""
import uuid
from datetime import datetime, timezone, timedelta


def new_id() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
class LogicalClock:
    """Single time source for the whole system. Starts at 2026-08-01T00:00:00Z."""

    INITIAL = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

    def __init__(self) -> None:
        self._now = self.INITIAL

    def now(self) -> datetime:
        return self._now

    def set_to(self, target: datetime) -> datetime:
        # clock moves only forward
        if target > self._now:
            self._now = target
        return self._now


CLOCK = LogicalClock()


def iso_now() -> str:
    """Logical now formatted as ISO8601 UTC with 3 fractional digits."""
    return format_ts(CLOCK.now())


def format_ts(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    # 3 fractional digits
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{ms:03d}Z"


def parse_iso(value):
    """Parse an ISO-8601 datetime string into an aware datetime in UTC."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Entity stores: dicts keyed by id
# ---------------------------------------------------------------------------
class Store:
    def __init__(self) -> None:
        self.bid_packages = {}
        self.subcontractors = {}
        self.prequal_applications = {}
        self.invitations = {}
        self.addendums = {}
        self.acks = {}          # AddendumAcknowledgment
        self.bids = {}
        self.bid_revisions = {}  # keyed by id; each has bid_id
        self.leveling_adjustments = {}
        self.interviews = {}
        self.recommendations = {}
        self.feedbacks = {}

    def reset(self) -> None:
        self.__init__()


DB = Store()


def touch(record: dict) -> None:
    """Refresh updated_at and bump version (only when record carries one)."""
    record["updated_at"] = iso_now()
    if "version" in record:
        record["version"] += 1


def stamp_new(record: dict, with_version: bool = True) -> None:
    now = iso_now()
    record["created_at"] = now
    if with_version:
        record["updated_at"] = now
        record["version"] = 1
