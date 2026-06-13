"""In-memory data store.

Every collection starts EMPTY on boot — no seeding. Tests build all
preconditions through the declared API surface.

Common audit fields (PRD §2.4):
  - id: server-minted UUID4, no type prefix
  - created_at: ISO 8601 UTC, 3 fractional digits
  - updated_at / version: only on mutable resources (version starts at 1,
    increments by 1 on every mutation, including derived-field recompute).

Append-only audit records (Notification, CheckIn, LedgerEntry) carry only
id + created_at.
"""
import uuid

from clock import now_iso

# Each collection: dict id -> record dict
defendants = {}
bail_orders = {}
bonds = {}
indemnitors = {}
indemnity_agreements = {}
collateral_items = {}
court_dates = {}
notifications = {}
check_ins = {}
gps_devices = {}
forfeitures = {}
ledger_entries = {}


def new_id():
    return str(uuid.uuid4())


def make_record(fields, mutable=True):
    """Create a record dict with audit fields populated. `fields` is the
    business payload (already validated)."""
    ts = now_iso()
    rec = {"id": new_id(), "created_at": ts}
    if mutable:
        rec["updated_at"] = ts
        rec["version"] = 1
    rec.update(fields)
    return rec


def touch(rec):
    """Mark a mutable record as mutated: bump updated_at and version."""
    rec["updated_at"] = now_iso()
    rec["version"] = rec.get("version", 1) + 1
