"""In-memory data store. All state lives in module-level dicts keyed by id.

The store starts completely empty on every boot — no seeding anywhere.
"""

import uuid
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

_START_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_current_clock = _START_CLOCK


def now() -> datetime:
    """Current logical-clock instant (timezone-aware UTC)."""
    return _current_clock


def set_clock(to_dt: datetime) -> None:
    global _current_clock
    _current_clock = to_dt


def fmt_ts(dt) -> str:
    """Render a datetime as ISO 8601 UTC with exactly 3 fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms:03d}Z"


# ---------------------------------------------------------------------------
# Stores — keyed by id, insertion ordered (creation order == created_at order
# because ids are minted sequentially through create_resource)
# ---------------------------------------------------------------------------

stores = {
    "providers": {},
    "edit_rules": {},
    "edit_versions": {},
    "vendor_edits": {},
    "claims": {},
    "claim_lines": {},
    "edit_hits": {},
    "review_tasks": {},
    "disputes": {},
    "ibrs": {},
    "inpatient_reviews": {},
    "abrasion_profiles": {},
    "savings_periods": {},
}


def new_id() -> str:
    return str(uuid.uuid4())


def create_resource(store_name: str, fields: dict) -> dict:
    """Insert a new resource, stamping id/created_at/updated_at/version."""
    ts = now()
    rec = {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1}
    rec.update(fields)
    stores[store_name][rec["id"]] = rec
    return rec


def touch(rec: dict) -> None:
    """Mutation bookkeeping: refresh updated_at and bump version."""
    rec["updated_at"] = now()
    rec["version"] = rec.get("version", 1) + 1


def get(store_name: str, rec_id: str):
    return stores[store_name].get(rec_id)


def all_records(store_name: str):
    return list(stores[store_name].values())
