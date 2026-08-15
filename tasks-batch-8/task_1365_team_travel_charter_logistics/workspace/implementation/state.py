"""In-memory store, logical clock, id/timestamp helpers, error type, envelope."""
import re
import uuid
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# In-memory store. Starts empty on every boot — no seeding.
# ---------------------------------------------------------------------------
STORE = {
    "teams": {},
    "seasons": {},
    "trips": {},
    "members": {},
    "contracts": {},
    "legs": {},
    "entries": {},
    "blocks": {},
    "rooms": {},
    "ledgers": {},
    "shipments": {},
    "events": {},
    "credentials": {},
}

_SEQ = {"n": 0}


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


def new_id():
    # PRD §2.4: "a server-minted UUID" — canonical RFC 4122 hyphenated form.
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Logical operations clock. Default 2026-08-01T00:00:00Z; never wall clock.
# ---------------------------------------------------------------------------
_CLOCK = {"now": datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)}


def clock_now():
    return _CLOCK["now"]


def clock_set(dt):
    _CLOCK["now"] = dt


def fmt_ts(dt):
    """ISO 8601 UTC with three fractional digits, e.g. 2026-08-01T00:00:00.000Z"""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    return fmt_ts(clock_now())


_DT_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$"
)


def parse_dt(value):
    """Parse an ISO 8601 datetime string -> aware datetime (UTC). None on failure."""
    if not isinstance(value, str) or not _DT_RE.match(value):
        return None
    s = value
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Parse an ISO date string YYYY-MM-DD -> date. None on failure."""
    if not isinstance(value, str):
        return None
    try:
        from datetime import date

        return date.fromisoformat(value)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err(error_id, http_status, message):
    return ApiError(error_id, http_status, message)


# ---------------------------------------------------------------------------
# Resource helpers
# ---------------------------------------------------------------------------
def new_resource():
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def bump(res):
    """Increment version and refresh updated_at (a mutation of the resource)."""
    res["version"] += 1
    res["updated_at"] = now_iso()


def touch(res):
    res["updated_at"] = now_iso()


def public(res):
    """Serialize a resource: strip internal underscore-prefixed keys."""
    return {k: v for k, v in res.items() if not k.startswith("_")}
