"""In-memory data store and logical clock.

The store starts empty on every boot. No entity seeding at startup.
"""
import threading
import uuid
from datetime import datetime, timezone

_LOCK = threading.RLock()

# Logical clock — starts at exactly 2026-08-01T00:00:00Z per PRD §2.4
_CLOCK_ISO = "2026-08-01T00:00:00Z"


def now_iso() -> str:
    """Return the current logical clock as an ISO 8601 UTC string.

    Internal format keeps microsecond precision; the API-facing formatter
    trims to three fractional digits.
    """
    with _LOCK:
        return _CLOCK_ISO


def set_clock(to_iso: str) -> str:
    global _CLOCK_ISO
    with _LOCK:
        _CLOCK_ISO = to_iso
        return _CLOCK_ISO


def parse_iso(s: str) -> datetime:
    """Parse an ISO-8601 string (with optional Z suffix) into an aware datetime."""
    if s is None:
        return None
    if isinstance(s, datetime):
        return s
    txt = str(s)
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def fmt_iso(dt: datetime) -> str:
    """Format an aware datetime as ISO 8601 UTC with exactly three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{ms:03d}Z"


def now_formatted() -> str:
    return fmt_iso(parse_iso(now_iso()))


def new_id() -> str:
    return str(uuid.uuid4())


# ---- Entity stores (plain dicts keyed by id) ----

producers = {}
clients = {}
contracts = {}
cases = {}
documents = {}
analyses = {}
transfers = {}
review_decisions = []
activity_events = []


def reset_all():
    producers.clear()
    clients.clear()
    contracts.clear()
    cases.clear()
    documents.clear()
    analyses.clear()
    transfers.clear()
    review_decisions.clear()
    activity_events.clear()
