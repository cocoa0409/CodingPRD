"""In-memory data store. The store starts EMPTY on every boot — no seeding."""

import itertools
import uuid
from datetime import datetime, timezone

STORE = {
    "installer_companies": {},
    "soil_scientists": {},
    "system_designers": {},
    "inspectors": {},
    "health_officers": {},
    "project_managers": {},
    "customers": {},
    "sites": {},
    "soil_evaluations": {},
    "percolation_tests": {},
    "designs": {},
    "permits": {},
    "installations": {},
    "inspections": {},
    "material_verifications": {},
    "variance_requests": {},
    "maintenance_contracts": {},
    "maintenance_visits": {},
    "repair_cases": {},
}

# Monotonic insertion sequence: stable tiebreak for created_at ordering.
_SEQ = itertools.count(1)
_PERMIT_SEQ = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


def new_permit_number():
    return "PER-{:06d}".format(next(_PERMIT_SEQ))


def now_iso():
    """ISO 8601 UTC timestamp with three fractional digits (PRD §2.2/§2.4)."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(now.microsecond // 1000)


def create_record(collection, fields):
    """Insert a new row with common fields (PRD §2.4): id/created_at/updated_at/version."""
    ts = now_iso()
    rec = dict(fields)
    rec["id"] = new_id()
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    rec["_seq"] = next(_SEQ)
    STORE[collection][rec["id"]] = rec
    return rec


def touch(rec):
    """Common mutation rule: bump version and refresh updated_at (PRD §2.4)."""
    rec["updated_at"] = now_iso()
    rec["version"] += 1


def set_fields(rec, **fields):
    for key, value in fields.items():
        rec[key] = value
    touch(rec)


def public(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def sorted_rows(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
