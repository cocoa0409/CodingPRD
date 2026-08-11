"""In-memory data store. All state lives here; wiped on every process restart."""
import uuid
from datetime import datetime, timezone

# Entity stores keyed by id
ceremonies = {}
venues = {}
graduates = {}
eligibility_audits = {}
ticket_allocations = {}
regalia_orders = {}
seat_assignments = {}
reader_cards = {}
print_batches = {}
diplomas = {}
rehearsal_sessions = {}
rehearsal_attendances = {}
accommodation_requests = {}
vendor_contracts = {}

# Logical clock — fixed default, never wall-clock
_DEFAULT_CLOCK = "2026-05-01T00:00:00Z"
_clock_state = {"current_utc": _DEFAULT_CLOCK}


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """Current logical clock instant as ISO 8601 UTC with three fractional digits."""
    return _clock_state["current_utc"]


def now_dt():
    return parse_dt(_clock_state["current_utc"])


def set_clock(to_iso8601):
    _clock_state["current_utc"] = to_iso8601


def get_clock():
    return _clock_state["current_utc"]


def wall_timestamp():
    """Server wall-clock timestamp for meta.api_request_timestamp (ISO 8601 UTC, 3 fractional digits)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(s):
    """Parse an ISO 8601 datetime string to an aware datetime. Accepts trailing Z."""
    if s is None:
        return None
    if isinstance(s, datetime):
        return s
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def touch(entity):
    """Refresh updated_at on mutation (does NOT bump version; callers do that explicitly)."""
    entity["updated_at"] = now_iso()
