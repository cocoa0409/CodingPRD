"""In-memory data store. Starts empty on every boot — no seeding."""

from datetime import datetime, timezone, timedelta

# ---- logical clock ----
_DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_logical_clock = _DEFAULT_CLOCK


def get_clock() -> datetime:
    return _logical_clock


def set_clock(dt: datetime) -> None:
    global _logical_clock
    _logical_clock = dt


def now_iso() -> str:
    """Current logical clock as ISO-8601 UTC with 3 fractional digits."""
    return to_iso(_logical_clock)


def to_iso(dt: datetime) -> str:
    if dt is None:
        return None
    s = dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.")
    s += f"{dt.astimezone(timezone.utc).microsecond // 1000:03d}Z"
    return s


def parse_iso(s: str) -> datetime:
    """Parse an ISO-8601 string into an aware UTC datetime."""
    if s is None:
        return None
    s = s.strip()
    # Handle trailing Z
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---- stores (dicts keyed by id) ----
watch_groups: dict = {}
blocks: dict = {}
members: dict = {}
captain_assignments: dict = {}
incident_reports: dict = {}
alerts: dict = {}
liaison_officers: dict = {}
liaison_meetings: dict = {}
data_share_agreements: dict = {}
training_sessions: dict = {}
community_events: dict = {}
certification_reviews: dict = {}

# ack tracking: alert_id -> set of member_ids
alert_acks: dict = {}
