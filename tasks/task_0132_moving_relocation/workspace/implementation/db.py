"""In-memory data store.

ALL state lives in module-level dicts keyed by id. There is NO seeding,
preloading, or hardcoding of entities — the store starts empty on every boot
(per INSTRUCTION + skill contract; the test harness restarts start.sh before
every test and relies on a clean store).

Common system fields (PRD §2.4):
  - id:        UUID string, no type prefix
  - created_at: ISO 8601 UTC, three fractional digits
  - updated_at: refreshed on every mutation
  - version:   integer, starts at 1, +1 on every mutation

SurveyItem and ClaimItem are append-only line items: id + created_at only
(no updated_at, no version) — PRD §2.4.
"""
import uuid
from datetime import datetime, timezone

# Each entity type -> { id: record_dict }
customers = {}
move_jobs = {}
surveys = {}
survey_items = {}
estimates = {}
packing_orders = {}
trucks = {}
crews = {}
dispatches = {}
storage_lots = {}
damage_claims = {}
claim_items = {}

# Monotonic sequence to provide a stable creation order for sorting, since
# multiple records can share the same millisecond timestamp.
_seq = 0


def next_seq():
    global _seq
    _seq += 1
    return _seq


def new_id():
    return str(uuid.uuid4())


def now_iso():
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def new_common(record):
    """Attach standard system fields for a full (versioned) entity."""
    ts = now_iso()
    record["id"] = new_id()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    record["_seq"] = next_seq()
    return record


def new_line_item(record):
    """Attach the minimal system fields for an append-only line item."""
    record["id"] = new_id()
    record["created_at"] = now_iso()
    record["_seq"] = next_seq()
    return record


def touch(record):
    """Mark a versioned entity as modified: bump version + updated_at."""
    record["updated_at"] = now_iso()
    record["version"] = record.get("version", 1) + 1


def touch_updated_only(record):
    """Refresh updated_at WITHOUT incrementing version.

    PRD §2.4: ledger refreshes that the spec does not explicitly tie to a
    version bump refresh updated_at without inventing extra increments.
    """
    record["updated_at"] = now_iso()
