"""In-memory data store and logical clock.

The store starts empty on every boot — no seeding.
"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone, timedelta

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

_STARTUP_UTC = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class LogicalClock:
    def __init__(self) -> None:
        self._now = _STARTUP_UTC
        self._lock = threading.Lock()

    def now(self) -> datetime:
        with self._lock:
            return self._now

    def set(self, new_now: datetime) -> datetime:
        with self._lock:
            self._now = new_now
            return self._now


CLOCK = LogicalClock()


def now_utc() -> datetime:
    return CLOCK.now()


def isoformat(dt: datetime) -> str:
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-08-01T00:00:00.000Z"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{ms:03d}Z"


def parse_iso(value: str) -> datetime:
    """Parse an ISO 8601 datetime string into an aware UTC datetime.

    Accepts trailing 'Z' or explicit offsets, fractional seconds optional.
    Raises ValueError on malformed input.
    """
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_month(value: str) -> tuple[int, int]:
    """Parse a YYYY-MM month string. Raises ValueError on malformed input."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    parts = value.split("-")
    if len(parts) != 2:
        raise ValueError("bad month")
    year = int(parts[0])
    month = int(parts[1])
    if not (1 <= month <= 12):
        raise ValueError("bad month")
    if len(parts[0]) != 4 or len(parts[1]) != 2:
        raise ValueError("bad month")
    return year, month


def month_start_dt(month: str) -> datetime:
    y, m = parse_month(month)
    return datetime(y, m, 1, tzinfo=timezone.utc)


def next_month(month: str) -> str:
    y, m = parse_month(month)
    if m == 12:
        return f"{y + 1:04d}-01"
    return f"{y:04d}-{m + 1:02d}"


def month_of(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return f"{dt.year:04d}-{dt.month:02d}"


def date_str(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%d")


def new_id() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    # Build a 22-char alphanumeric suffix from uuid4 bytes
    raw = uuid.uuid4().bytes
    suffix = "".join(alphabet[b % len(alphabet)] for b in raw[:22])
    return f"req_{suffix}"


# ---------------------------------------------------------------------------
# Entity store
# ---------------------------------------------------------------------------


class Store:
    """Empty-on-boot in-memory store. All collections keyed by id."""

    def __init__(self) -> None:
        self.stations: dict[str, dict] = {}
        self.compressors: dict[str, dict] = {}
        self.dispensers: dict[str, dict] = {}
        self.calibration_records: dict[str, dict] = {}
        self.pricing_policies: dict[str, dict] = {}
        self.fleet_accounts: dict[str, dict] = {}
        self.fleet_cards: dict[str, dict] = {}
        self.supply_contracts: dict[str, dict] = {}
        self.monthly_settlements: dict[str, dict] = {}
        self.fueling_sessions: dict[str, dict] = {}
        self.maintenance_windows: dict[str, dict] = {}
        self.backup_arrangements: dict[str, dict] = {}
        self.safety_inspections: dict[str, dict] = {}
        self.tax_credit_claims: dict[str, dict] = {}

    def reset(self) -> None:
        self.__init__()


STORE = Store()
