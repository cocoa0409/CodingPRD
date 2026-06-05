from __future__ import annotations

"""In-memory data store. Starts empty on every boot."""
from datetime import datetime, timezone
from threading import Lock
import itertools
import secrets
import string
import uuid


# Entity tables - one dict per entity, keyed by id.
chapters: dict = {}
pnms: dict = {}
rounds: dict = {}
parties: dict = {}
invitations: dict = {}
preferences: dict = {}
bid_matches: dict = {}
dues_ledger_entries: dict = {}
risk_incidents: dict = {}

# Monotonic insertion counters to break created_at ties in deterministic order.
_insertion_counter = itertools.count(1)

# Logical clock - the server's observed "now". Can be pinned by the test-clock endpoint.
_clock_pinned_at: datetime | None = None

_lock = Lock()


def reset() -> None:
    """Wipe all in-memory state. Called on test isolation boundaries if ever needed."""
    global _insertion_counter, _clock_pinned_at
    chapters.clear()
    pnms.clear()
    rounds.clear()
    parties.clear()
    invitations.clear()
    preferences.clear()
    bid_matches.clear()
    dues_ledger_entries.clear()
    risk_incidents.clear()
    _insertion_counter = itertools.count(1)
    _clock_pinned_at = None


def now_utc() -> datetime:
    """Return the current UTC instant. Honors a pinned logical clock when set."""
    if _clock_pinned_at is not None:
        return _clock_pinned_at
    return datetime.now(timezone.utc)


def set_clock(dt: datetime) -> None:
    global _clock_pinned_at
    _clock_pinned_at = dt


def next_insertion_seq() -> int:
    return next(_insertion_counter)


def new_id() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    rand = "".join(
        secrets.choice(string.ascii_uppercase + string.digits) for _ in range(20)
    )
    return f"req_{rand}"


def format_ts(dt: datetime) -> str:
    """ISO 8601 UTC with three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    s = dt.strftime("%Y-%m-%dT%H:%M:%S")
    millis = f"{dt.microsecond // 1000:03d}"
    return f"{s}.{millis}Z"


def parse_iso8601(value: str) -> datetime:
    """Parse an ISO 8601 string into a tz-aware UTC datetime.

    Accepts trailing 'Z' as UTC.
    """
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"invalid iso8601: {value}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt
