"""In-memory data store. All state lives in module-level dicts."""

import uuid
from datetime import datetime, timezone, timedelta

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

_CLOCK_START = "2026-05-01T00:00:00Z"
_logical_now = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


def get_logical_now() -> datetime:
    return _logical_now


def set_logical_now(dt: datetime):
    global _logical_now
    _logical_now = dt


def format_ts(dt: datetime) -> str:
    """Format datetime as ISO 8601 UTC with three fractional digits."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def logical_date_str() -> str:
    """Current logical date as YYYY-MM-DD."""
    return _logical_now.strftime("%Y-%m-%d")


def new_id() -> str:
    return str(uuid.uuid4())


def now_iso() -> str:
    return format_ts(_logical_now)


# ---------------------------------------------------------------------------
# Stores — empty at boot, populated exclusively via API
# ---------------------------------------------------------------------------

aircraft_store = {}      # id -> dict
party_store = {}         # id -> dict
escrow_file_store = {}   # id -> dict
trust_agreement_store = {}  # id -> dict
title_search_store = {}  # id -> dict
lien_store = {}          # id -> dict
lien_release_store = {}  # id -> dict
deposit_store = {}       # id -> dict
disbursement_store = {}  # id -> dict
filing_store = {}        # id -> dict
closing_document_store = {}  # id -> dict

# Track per-file submission counter for Filing.sequence_index
_filing_submit_counters = {}  # escrow_file_id -> count


def next_filing_sequence(escrow_file_id: str) -> int:
    cur = _filing_submit_counters.get(escrow_file_id, 0) + 1
    _filing_submit_counters[escrow_file_id] = cur
    return cur


# ---------------------------------------------------------------------------
# Entity helpers
# ---------------------------------------------------------------------------

def make_common_fields() -> dict:
    ts = now_iso()
    return {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1}


def touch(entity: dict):
    """Refresh updated_at and increment version."""
    entity["updated_at"] = now_iso()
    entity["version"] += 1


def touch_with_logical_ts(entity: dict):
    """Refresh updated_at without version bump (for internal recompute)."""
    entity["updated_at"] = now_iso()
