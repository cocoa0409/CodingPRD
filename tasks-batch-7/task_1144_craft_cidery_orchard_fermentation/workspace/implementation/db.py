"""In-memory data store, logical clock, and id/sequence generation.

Storage is in-memory only: plain dicts keyed by id. The store starts empty on
every boot; nothing is seeded or preloaded.
"""

import uuid
from datetime import datetime, timezone

# --- entity collections (all start empty) -----------------------------------
store = {
    "varieties": {},
    "yeast_programs": {},
    "contracts": {},
    "harvest_lots": {},
    "press_batches": {},
    "blend_lines": {},
    "tanks": {},
    "fermentation_batches": {},
    "products": {},
    "label_approvals": {},
    "licenses": {},
    "packaging_runs": {},
    "orders": {},
    "excise_reports": {},
    "compliance_events": {},
}

# --- insertion sequence for stable created_at ordering ----------------------
_seq = [0]


def next_seq():
    _seq[0] += 1
    return _seq[0]


# --- logical clock ----------------------------------------------------------
# Before any operator intervenes the logical clock reads 2026-05-01T00:00:00Z.
# It is advanced only via POST /cidery/_clock/set_current_utc and never falls
# back to wall-clock time.
_clock = [datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)]


def now():
    return _clock[0]


def set_now(dt):
    _clock[0] = dt


# --- helpers ----------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def stamp_new(rec, common=True):
    rec["id"] = new_id()
    rec["created_at"] = now()
    rec["_seq"] = next_seq()
    if common:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1


def bump(rec):
    """Mutation: refresh updated_at and increment version by one."""
    rec["updated_at"] = now()
    rec["version"] += 1
