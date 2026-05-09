import threading
import uuid
from datetime import datetime, timezone


_lock = threading.RLock()

# Logical clock — milliseconds since epoch as a datetime in UTC.
# Initialized to 2025-01-01T00:00:00.000Z; advanced by POST /_clock/advance.
_logical_now: datetime = datetime(2025, 1, 1, 0, 0, 0, 0, tzinfo=timezone.utc)


def now() -> datetime:
    with _lock:
        return _logical_now


def set_now(dt: datetime) -> None:
    global _logical_now
    with _lock:
        _logical_now = dt


def advance_seconds(seconds: int) -> datetime:
    global _logical_now
    with _lock:
        _logical_now = _logical_now + _seconds_delta(seconds)
        return _logical_now


def _seconds_delta(seconds: int):
    from datetime import timedelta
    return timedelta(seconds=seconds)


def gen_id() -> str:
    return str(uuid.uuid4())


def fmt_dt(dt) -> str:
    if dt is None:
        return None
    if isinstance(dt, str):
        return dt
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    s = dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    millis = dt.astimezone(timezone.utc).microsecond // 1000
    return f"{s}.{millis:03d}Z"


def parse_dt(s) -> datetime:
    if isinstance(s, datetime):
        return s if s.tzinfo else s.replace(tzinfo=timezone.utc)
    if not isinstance(s, str):
        raise ValueError("not a datetime string")
    text = s
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# In-memory stores keyed by id.
sellers: dict = {}
bidders: dict = {}
lots: dict = {}
bids: dict = {}
proxies: dict = {}
deposits: dict = {}
invoices: dict = {}
disputes: dict = {}


def lock():
    return _lock


def reset_all():
    global _logical_now
    with _lock:
        sellers.clear()
        bidders.clear()
        lots.clear()
        bids.clear()
        proxies.clear()
        deposits.clear()
        invoices.clear()
        disputes.clear()
        _logical_now = datetime(2025, 1, 1, 0, 0, 0, 0, tzinfo=timezone.utc)
