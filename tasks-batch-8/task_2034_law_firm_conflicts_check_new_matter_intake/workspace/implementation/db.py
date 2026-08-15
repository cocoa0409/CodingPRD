"""In-memory data store + logical clock.

Storage is process-local dictionaries keyed by id. The store starts EMPTY on
every boot -- no seeding, no preload, no external persistence. The harness
re-launches the server (start.sh) before every test, so each test sees a
fresh store and the logical clock default of 2026-08-01T00:00:00Z (PRD 2.5).
"""

import uuid
from datetime import datetime, timezone

CLOCK_STARTUP_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        # Entity tables: dict keyed by id; dicts preserve insertion order,
        # which doubles as the deterministic tiebreak for equal timestamps.
        self.parties = {}
        self.attorneys = {}
        self.matters = {}
        self.matter_parties = {}
        self.conflict_checks = {}
        self.conflict_hits = {}
        self.ethical_walls = {}
        self.waiver_requests = {}
        self.engagement_letters = {}
        self.credit_assessments = {}
        self.retainer_deposits = {}
        # System-wide matter number counter (countersign completion order).
        self.matter_number_counter = 0
        # Logical clock (PRD 2.5): never falls back to wall-clock.
        self.clock = CLOCK_STARTUP_DEFAULT


store = Store()


def new_id():
    """Server-minted UUID with no type prefix (PRD 2.4)."""
    return str(uuid.uuid4())


def now():
    return store.clock


def format_ts(dt):
    """ISO 8601 UTC with three fractional digits (PRD 2.4)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def format_clock(dt):
    """Clock reading format: seconds precision when sub-second is zero,
    matching the PRD's own notation '2026-08-01T00:00:00Z'; otherwise the
    canonical three-fractional-digit form."""
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return format_ts(dt)


def now_iso():
    return format_ts(store.clock)


def parse_ts(s):
    """Parse a canonical stored timestamp ('...sssZ') back to datetime."""
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)


def parse_input_ts(s):
    """Parse an arbitrary ISO 8601 input (clock endpoint). Naive -> UTC."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if t.endswith("Z") or t.endswith("z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def stamp_new(row):
    """Common fields (PRD 2.4) for a freshly created row."""
    row["id"] = new_id()
    row["created_at"] = now_iso()
    row["updated_at"] = row["created_at"]
    row["version"] = 1
    return row


def bump(row):
    """Every mutation of a row: version +1 and updated_at refreshed."""
    row["version"] += 1
    row["updated_at"] = now_iso()
    return row


def next_matter_number():
    store.matter_number_counter += 1
    return "M" + str(store.matter_number_counter).zfill(6)
