"""In-memory data store + logical clock.

Storage is in-memory only: plain dicts keyed by UUID. The store starts empty
on every boot (no seeding whatsoever). The logical clock starts at exactly
2026-08-01T00:00:00Z and is advanced only via POST /parking/_clock/set_current_utc.
"""
import uuid
from datetime import datetime, timezone

# Entity tables: id -> dict record
patrons = {}
lots = {}
allocations = {}
waitlist_entries = {}
permits = {}
citations = {}
closures = {}
shuttle_routes = {}
incentive_accounts = {}
funds = {}

# Ridership logs are an append-only sub-record per route (no separate entity in
# the scaffold table, they only feed ridership_total) — we keep raw logs too.
ridership_logs = []

# Sequential creation counter to make created_at ordering deterministic even
# when two records are created within the same logical instant.
_creation_seq = [0]

# Logical clock — starts exactly at 2026-08-01T00:00:00Z
_clock_state = {"now": datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)}


def now() -> datetime:
    """Current logical time (never wall-clock)."""
    return _clock_state["now"]


def set_now(dt: datetime) -> None:
    _clock_state["now"] = dt


def new_id() -> str:
    return str(uuid.uuid4())


def next_creation_seq() -> int:
    _creation_seq[0] += 1
    return _creation_seq[0]


def iso_now() -> str:
    return fmt_ts(now())


def fmt_ts(dt: datetime) -> str:
    """Format datetime as ISO 8601 UTC with three fractional digits and Z suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    s = dt.strftime("%Y-%m-%dT%H:%M:%S.")
    s += f"{dt.microsecond // 1000:03d}Z"
    return s
