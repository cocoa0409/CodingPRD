"""In-memory data store for the Engagement Survey API.

The store starts empty on every boot. No entity is seeded, preloaded, or
hardcoded at startup — every entity is constructed via the declared API
surface. The logical clock starts at exactly 2026-08-01T00:00:00Z and never
falls back to wall-clock time.
"""

import itertools
import uuid
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Entity stores: dicts keyed by id. Insertion order is preserved (creation
# order), which doubles as the created_at-ascending default sort.
# ---------------------------------------------------------------------------

class Store:
    def __init__(self):
        self.item_banks = {}
        self.survey_items = {}
        self.org_units = {}
        self.employees = {}
        self.survey_cycles = {}
        self.cycle_items = {}
        self.survey_invites = {}
        self.survey_responses = {}       # keyed by response id
        self.responses_by_invite = {}    # invite_id -> response id
        self.report_snapshots = {}
        self.benchmark_sets = {}
        self.action_plans = {}
        self.action_items = {}
        self.outcome_linkages = {}
        self.reminder_events = {}

        # Monotonic creation sequence used for deterministic tie-breaking
        # (e.g. pulse sampling ties on hired_at break by created_at order).
        self.seq = itertools.count(1)

        # Logical clock: startup default is exactly 2026-08-01T00:00:00Z.
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


db = Store()


def new_id():
    return str(uuid.uuid4())


def format_ts(dt):
    """Format a datetime as ISO 8601 UTC with exactly 3 fractional digits, 'Z' suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    ms = dt.microsecond // 1000
    return f"{base}.{ms:03d}Z"


def now_iso():
    """Current logical-clock timestamp as ISO 8601 UTC with 3 fractional digits."""
    return format_ts(db.clock)


def parse_ts(value):
    """Parse an ISO 8601 timestamp string into an aware datetime (UTC).

    Accepts 'Z' suffix and explicit offsets. Raises ValueError when malformed.
    """
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    s = value.strip()
    if not s:
        raise ValueError("timestamp must be non-empty")
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# System-field helpers
# ---------------------------------------------------------------------------

def stamp_new(entity):
    """Populate id/created_at/updated_at/version on a freshly created entity."""
    entity["id"] = new_id()
    entity["_created_seq"] = next(db.seq)
    entity["created_at"] = now_iso()
    entity["updated_at"] = entity["created_at"]
    entity["version"] = 1
    return entity


def stamp_new_immutable(entity):
    """Immutable record types (SurveyResponse, OutcomeLinkage, ReminderEvent)
    carry only id and created_at — no updated_at, no version."""
    entity["id"] = new_id()
    entity["_created_seq"] = next(db.seq)
    entity["created_at"] = now_iso()
    return entity


def touch(entity):
    """Refresh updated_at and increment version on a mutated entity."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 1) + 1


def clock_now():
    return db.clock


def advance_clock(to_dt):
    db.clock = to_dt


# ---------------------------------------------------------------------------
# Serialization: strip internal helper fields (those prefixed with "_").
# ---------------------------------------------------------------------------

def public(entity):
    """Return the wire view of an entity: all fields except internal helpers."""
    return {k: v for k, v in entity.items() if not k.startswith("_")}
