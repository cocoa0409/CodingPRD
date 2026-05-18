"""Thread-safe in-memory data store and logical-clock singleton."""
import threading
import uuid
from datetime import datetime, timezone


def new_id() -> str:
    return str(uuid.uuid4())


def fmt_ts(dt: datetime) -> str:
    """Format a datetime as ISO 8601 UTC with milliseconds and trailing Z."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(s):
    """Parse an ISO 8601 timestamp; tolerate 'Z' suffix and date-only input."""
    if s is None:
        return None
    if not isinstance(s, str):
        return None
    txt = s.strip()
    if not txt:
        return None
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        # Allow plain dates (YYYY-MM-DD).
        try:
            dt = datetime.strptime(txt, "%Y-%m-%d")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


# ---- per-process singletons ---------------------------------------------

_lock = threading.RLock()


def lock():
    """Coarse-grained lock for "first-writer-wins" guarantees."""
    return _lock


# Tables; each maps id -> dict.
cases = {}
parties = {}
disclosures = {}
parenting_plans = {}
mediation_sessions = {}
support_orders = {}
temp_orders = {}
final_judgments = {}


# Logical clock — initialised lazily to "now" the first time it is read.
class _Clock:
    def __init__(self):
        self._now = datetime.now(timezone.utc).replace(microsecond=0)

    @property
    def now(self) -> datetime:
        return self._now

    def advance_to(self, target: datetime) -> datetime:
        # Caller must ensure target is timezone-aware UTC.
        self._now = target
        return self._now


clock = _Clock()


def now() -> datetime:
    return clock.now


def docket_for(year: int, seq: int) -> str:
    return f"FC-{year:04d}-{seq:06d}"


# Monotonic case sequence for docket numbers.
_docket_seq = 0


def next_docket(year: int) -> str:
    global _docket_seq
    _docket_seq += 1
    return docket_for(year, _docket_seq)
