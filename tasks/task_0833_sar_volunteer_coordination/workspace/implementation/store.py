"""In-memory data store, logical clock, and low-level record helpers.

Everything is process-local: a fresh interpreter (each start.sh invocation)
starts with empty collections and the clock at its default. No persistence.
"""
import uuid
from datetime import datetime, timezone

# --- Entity collections (id -> record dict) ------------------------------
incidents = {}
tasks = {}
teams = {}
members = {}
certifications = {}
callouts = {}
resources = {}
resource_assignments = {}
ground_tracks = {}
clues = {}
claims = {}
aars = {}

COLLECTIONS = {
    "Incident": incidents,
    "Task": tasks,
    "Team": teams,
    "Member": members,
    "Certification": certifications,
    "Callout": callouts,
    "Resource": resources,
    "ResourceAssignment": resource_assignments,
    "GroundTrack": ground_tracks,
    "Clue": clues,
    "ReimbursementClaim": claims,
    "AfterActionReport": aars,
}

# --- Logical clock -------------------------------------------------------
DEFAULT_CLOCK = "2026-03-01T00:00:00Z"
_clock = None  # datetime (aware, UTC)


def parse_dt(value):
    """Parse an ISO 8601 string into an aware UTC datetime. Raises ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def get_clock():
    global _clock
    if _clock is None:
        _clock = parse_dt(DEFAULT_CLOCK)
    return _clock


def set_clock(iso_string):
    global _clock
    _clock = parse_dt(iso_string)


def iso(dt):
    """Format an aware datetime as ISO 8601 UTC with 3 fractional digits + Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def clock_iso():
    return iso(get_clock())


# --- Sequence / id / timestamp helpers -----------------------------------
_seq = 0


def next_seq():
    global _seq
    _seq += 1
    return _seq


def new_id():
    return str(uuid.uuid4())


def now_iso():
    return iso(datetime.now(timezone.utc))


def base_record(rtype, common=True):
    """Build the common scaffolding for a new record."""
    ts = now_iso()
    rec = {
        "_type": rtype,
        "_seq": next_seq(),
        "id": new_id(),
        "created_at": ts,
    }
    if common:
        rec["updated_at"] = ts
        rec["version"] = 1
    return rec


def mutate(rec):
    """Register a mutation: refresh updated_at and bump version."""
    if "version" in rec:
        rec["version"] += 1
        rec["updated_at"] = now_iso()
