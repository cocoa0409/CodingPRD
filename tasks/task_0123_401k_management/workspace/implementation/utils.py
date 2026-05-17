"""Small utilities: time helpers, rounding, OCC bumping."""

import threading
import uuid
from datetime import datetime, timezone, date, timedelta
from decimal import Decimal, ROUND_HALF_UP


_LOCK = threading.RLock()


def lock():
    return _LOCK


def new_id() -> str:
    return str(uuid.uuid4())


def now_iso() -> str:
    now = datetime.now(timezone.utc)
    millis = now.microsecond // 1000
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{millis:03d}Z"


def today_utc_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def parse_date(s):
    """Parse YYYY-MM-DD into a date. Returns None if invalid."""
    if not isinstance(s, str):
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def date_to_str(d: date) -> str:
    return d.strftime("%Y-%m-%d")


def days_between(start_str: str, end_str: str) -> int:
    a = parse_date(start_str)
    b = parse_date(end_str)
    if a is None or b is None:
        return 0
    return (b - a).days


def add_days(date_str: str, days: int) -> str:
    d = parse_date(date_str)
    if d is None:
        return date_str
    return date_to_str(d + timedelta(days=days))


def round_half_up(value) -> int:
    """Round a Decimal/number to the nearest integer using ROUND_HALF_UP."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_to_decimal(value, places: int) -> Decimal:
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    q = Decimal("1").scaleb(-places)
    return value.quantize(q, rounding=ROUND_HALF_UP)


def bump_version(record: dict) -> None:
    """Increment version + refresh updated_at."""
    record["version"] = int(record.get("version", 0)) + 1
    record["updated_at"] = now_iso()


def stamp_create(record: dict) -> None:
    """Stamp id/created_at/updated_at/version on a new common-fields resource."""
    ts = now_iso()
    record.setdefault("id", new_id())
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1


def stamp_ledger_create(record: dict) -> None:
    """Stamp id/created_at for ledger-style (immutable) resources."""
    record.setdefault("id", new_id())
    record["created_at"] = now_iso()
