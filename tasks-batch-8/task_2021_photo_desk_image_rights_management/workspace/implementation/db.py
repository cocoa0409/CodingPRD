"""In-memory data store for the Photo Desk & Image Rights Management API.

All data lives in plain Python dicts keyed by resource id. The store starts
empty on every process boot (no seeding, no persistence).
"""

import uuid
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

_DEFAULT_NOW = "2026-08-01T00:00:00Z"

_logical_now: datetime = None  # set in init()


def init_clock() -> None:
    global _logical_now
    _logical_now = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def logical_now() -> datetime:
    return _logical_now


def set_logical_now(dt: datetime) -> None:
    global _logical_now
    _logical_now = dt


def now_iso() -> str:
    """Current logical time as ISO 8601 UTC with three fractional digits."""
    return _logical_now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{_logical_now.microsecond // 1000:03d}Z"


def iso_now_str(dt: datetime) -> str:
    """Format an arbitrary datetime as ISO 8601 UTC with three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(s: str):
    """Parse an ISO 8601 string to a timezone-aware datetime (UTC).

    Returns None on failure.
    """
    if s is None:
        return None
    if not isinstance(s, str):
        return None
    try:
        # Handle trailing Z
        cleaned = s.strip()
        if cleaned.endswith("Z"):
            cleaned = cleaned[:-1] + "+00:00"
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Stores — one dict per entity type, keyed by id (UUID string, no prefix)
# ---------------------------------------------------------------------------

photographers: dict = {}
story_requests: dict = {}
assignments: dict = {}
images: dict = {}
licenses: dict = {}
releases: dict = {}
usage_runs: dict = {}
claims: dict = {}
payment_runs: dict = {}


def new_id() -> str:
    return str(uuid.uuid4())


def init_store() -> None:
    """Reset all stores to empty. Called once at startup."""
    photographers.clear()
    story_requests.clear()
    assignments.clear()
    images.clear()
    licenses.clear()
    releases.clear()
    usage_runs.clear()
    claims.clear()
    payment_runs.clear()
    init_clock()
