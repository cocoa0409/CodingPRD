"""In-memory data store, logical clock, and entity mutation helpers.

Storage is plain Python dicts keyed by id. No persistence of any kind.
The store starts completely empty on every boot; nothing is seeded.
"""
import threading
import uuid
from datetime import datetime, timezone

LOCK = threading.RLock()

# Logical clock: starts at exactly 2026-05-01T00:00:00Z (PRD section 2.5).
CLOCK = {"now": datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)}

DB = {
    "indentures": {},
    "tranches": {},
    "noteholder_accounts": {},
    "positions": {},
    "covenant_obligations": {},
    "covenant_certificates": {},
    "payment_runs": {},
    "distribution_records": {},
    "default_cases": {},
    "directions": {},
    "direction_endorsements": {},
    "consent_solicitations": {},
    "collateral_items": {},
    "collateral_release_requests": {},
    "fee_invoices": {},
    "trustee_appointments": {},
}


def new_id():
    return str(uuid.uuid4())


def now():
    return CLOCK["now"]


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.4)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    return fmt_ts(now())


def new_entity(kind):
    e = {
        "id": new_id(),
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
    }
    DB[kind][e["id"]] = e
    return e


def touch(e):
    """Refresh updated_at and bump version (PRD 2.4: cascades count as mutations)."""
    e["updated_at"] = now_iso()
    e["version"] += 1


def mutate(e, **fields):
    """Set fields; touch only when a value actually changes."""
    changed = False
    for k, v in fields.items():
        if e.get(k) != v:
            e[k] = v
            changed = True
    if changed:
        touch(e)
