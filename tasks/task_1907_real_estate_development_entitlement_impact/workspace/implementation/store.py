"""In-memory data store, logical clock, and identity/timestamp helpers.

Storage is process-local dicts keyed by id. The store starts empty on every
boot; nothing is seeded. All domain timestamps come from the logical clock
(PRD section 2.8), never from wall-clock time.
"""

import uuid
from datetime import datetime, timezone

# --- logical clock ---------------------------------------------------------
_DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"


def _parse_iso(value):
    """Parse an ISO-8601 datetime; naive values are treated as UTC."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
    else:
        raise ValueError("not an ISO-8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


class Clock:
    """Server-side logical clock. Starts at the PRD-pinned default."""

    def __init__(self):
        self._now = _parse_iso(_DEFAULT_CLOCK_ISO)

    def now(self) -> datetime:
        return self._now

    def set(self, iso_value: str) -> datetime:
        self._now = _parse_iso(iso_value)
        return self._now


CLOCK = Clock()


def parse_dt(value) -> datetime:
    """Public parser for client-supplied datetimes (raises ValueError)."""
    return _parse_iso(value)


def fmt_dt(dt: datetime) -> str:
    """Format a datetime as ISO-8601 UTC with exactly three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    return f"{base}.{dt.microsecond // 1000:03d}Z"


def new_id() -> str:
    """Server-minted UUID with no type prefix."""
    return str(uuid.uuid4())


def request_id() -> str:
    """Envelope api_request_id: 'req_' + random alphanumeric."""
    return "req_" + uuid.uuid4().hex[:24]


# --- entity stores ---------------------------------------------------------
# Every one of the seventeen resource types gets its own dict keyed by id.
STORES = {
    "fee_schedules": {},
    "applicants": {},
    "staff_reviewers": {},
    "decision_authorities": {},
    "projects": {},
    "applications": {},
    "review_comments": {},
    "outreach_events": {},
    "hearings": {},
    "conditions": {},
    "assessments": {},
    "payments": {},
    "development_agreements": {},
    "petitions": {},
    "appeals": {},
    "decisions": {},
    "permit_sequences": {},
}


def new_record(store_name: str) -> dict:
    """Create a bare record with the four system-managed common fields."""
    now = fmt_dt(CLOCK.now())
    rec = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    STORES[store_name][rec["id"]] = rec
    return rec


def touch(rec: dict) -> None:
    """Mark a record modified: refreshed updated_at, incremented version."""
    rec["updated_at"] = fmt_dt(CLOCK.now())
    rec["version"] = int(rec.get("version", 1)) + 1


def get(store_name: str, rec_id: str):
    return STORES[store_name].get(rec_id)


def all_records(store_name: str):
    """All records in insertion order (stable tiebreak for created_at sort)."""
    return list(STORES[store_name].values())
