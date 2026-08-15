"""In-memory data store + logical clock (PRD §2.4, §2.5).

Storage is in-memory only: plain dicts keyed by id, empty at every boot.
No seeding, no files, no external persistence.
"""

import uuid
from datetime import date, datetime, timezone


def iso_z(dt):
    """ISO 8601 UTC with three fractional digits, e.g. 2026-08-01T00:00:00.000Z."""
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def wall_now_iso():
    return iso_z(datetime.now(timezone.utc))


class Store:
    def __init__(self):
        self.customers = {}
        self.lots = {}
        self.tests = {}
        self.schedules = {}
        self.units = {}
        self.tickets = {}
        self.runs = {}
        self.blends = {}
        self.claims = {}
        self.agreements = {}
        self.invoices = {}
        self.payments = {}
        self.reversed_payment_ids = set()
        self.seq = 0  # insertion sequence, tiebreaks equal created_at values
        # Logical clock: starts at 2026-08-01T00:00:00Z before any set call.
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


store = Store()


def new_id():
    return str(uuid.uuid4())


def next_seq():
    store.seq += 1
    return store.seq


def logical_now():
    return store.clock


def logical_now_iso():
    return iso_z(store.clock)


def current_date():
    return store.clock.date()


def stamp_new(rec):
    """Common resource properties on creation (PRD §2.5)."""
    rec["id"] = new_id()
    rec["created_at"] = wall_now_iso()
    rec["updated_at"] = rec["created_at"]
    rec["version"] = 1
    rec["_seq"] = next_seq()
    return rec


def stamp_new_payment(rec):
    """Payments are immutable ledger entries: only id + created_at (PRD §2.5)."""
    rec["id"] = new_id()
    rec["created_at"] = wall_now_iso()
    rec["_seq"] = next_seq()
    return rec


def touch(rec):
    """Refresh updated_at and advance version on any mutation (PRD §2.5)."""
    rec["updated_at"] = wall_now_iso()
    rec["version"] += 1


def public(rec):
    """Serialize a record: drop internal keys (underscore-prefixed)."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def sort_by_creation(records):
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


def parse_date(s):
    if not isinstance(s, str):
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def parse_datetime(s):
    if not isinstance(s, str):
        return None
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
