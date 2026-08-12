"""In-memory data store and logical clock for the Trade Secret & Confidentiality
Program API.

Storage is process-local only. The store starts EMPTY on every boot — no seed
data of any kind. Every entity any caller needs is constructed through the
declared API surface.

Time is logical, not wall-clock (PRD §2.5): before any operator touches it the
clock reads exactly 2026-05-01T00:00:00Z, and every deadline/expiry/window rule
evaluates against it.
"""

import uuid
from calendar import monthrange
from datetime import datetime, timedelta, timezone

INITIAL_CLOCK_STR = "2026-05-01T00:00:00Z"

# ---------------------------------------------------------------------------
# Stores: one dict per entity type (16 peer entities, flat topology).
# ---------------------------------------------------------------------------
db = {
    "assets": {},
    "measures": {},
    "counterparties": {},
    "ndas": {},
    "obligations": {},
    "employees": {},
    "acknowledgments": {},
    "exit_interviews": {},
    "grants": {},
    "disclosures": {},
    "forensic_reviews": {},
    "demand_letters": {},
    "preservation_notices": {},
    "evidence_items": {},
    "training_assignments": {},
    "clean_desk_audits": {},
}

# Program-level mutable state (PRD §2.5): policy version starts at "v1".
program = {"current_policy_version": "v1"}

# Logical clock: parsed datetime for comparisons plus the raw string form for
# echoing (the clock read returns exactly what was set; the initial value reads
# exactly 2026-05-01T00:00:00Z).
clock = {
    "dt": datetime(2026, 5, 1, tzinfo=timezone.utc),
    "raw": INITIAL_CLOCK_STR,
}


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def now():
    """Current logical clock as an aware datetime."""
    return clock["dt"]


def now_raw():
    """Current logical clock in its echoable string form."""
    return clock["raw"]


def set_clock(dt, raw):
    clock["dt"] = dt
    clock["raw"] = raw


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD §2.4)."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value):
    """Parse an ISO 8601 string into an aware UTC datetime, truncated to second
    precision (PRD §2.11). Returns None when unparseable."""
    if not isinstance(value, str) or not value.strip():
        return None
    s = value.strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0)


def add_months(dt, months):
    """Calendar-month addition with day clamping (PRD §2.11)."""
    total = dt.month - 1 + months
    year = dt.year + total // 12
    month = total % 12 + 1
    day = min(dt.day, monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def add_days(dt, days):
    return dt + timedelta(days=days)


# ---------------------------------------------------------------------------
# Entity helpers
# ---------------------------------------------------------------------------
def new_id():
    """Server-minted UUID with no type prefix (PRD §2.4)."""
    return str(uuid.uuid4())


def new_record(store_name, fields):
    """Create a record with the four common system fields: id, created_at,
    updated_at, version. `version` starts at 1 and increments on every direct
    mutation of the resource."""
    n = now()
    rec = {
        "id": new_id(),
        "created_at": fmt_ts(n),
        "updated_at": fmt_ts(n),
        "version": 1,
        "_created_dt": n,
        "_updated_dt": n,
    }
    rec.update(fields)
    db[store_name][rec["id"]] = rec
    return rec


def touch(rec):
    """Mark a direct mutation: bump version and refresh updated_at (PRD §2.4)."""
    n = now()
    rec["version"] += 1
    rec["updated_at"] = fmt_ts(n)
    rec["_updated_dt"] = n


def stamp(rec, field, dt=None):
    """Set a system timestamp field (both display and comparison forms)."""
    n = dt if dt is not None else now()
    rec[field] = fmt_ts(n)
    rec["_" + field + "_dt"] = n


def serialize(rec):
    """Public view of a record: strip internal comparison helpers."""
    if rec is None:
        return None
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def by_id(store_name, rid):
    return db[store_name].get(rid)


def all_rows(store_name):
    return list(db[store_name].values())


def created_asc(rows):
    """Sort by created_at ascending; stable sort keeps insertion order on ties
    (cascade processing order rule, SCAFFOLD §1.2)."""
    return sorted(rows, key=lambda r: (r["_created_dt"],))
