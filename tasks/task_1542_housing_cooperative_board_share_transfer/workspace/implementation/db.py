"""In-memory data store.

Pure Python dicts keyed by id. No SQLite, no disk persistence, no seeding:
every process boot starts with a completely empty store. All entities any
caller needs are constructed through the declared API surface.
"""
import uuid

STORE = {
    "cooperatives": {},
    "units": {},
    "shareholders": {},
    "share_ledger_entries": {},
    "charge_schedules": {},
    "maintenance_charges": {},
    "payments": {},
    "arrears_actions": {},
    "purchase_applications": {},
    "interviews": {},
    "resolutions": {},
    "resolution_votes": {},
    "sublet_agreements": {},
    "alteration_agreements": {},
    "meetings": {},
    "ballots": {},
}

_seq_counter = [0]


def new_id():
    """Server-minted UUID with no type prefix."""
    return str(uuid.uuid4())


def next_seq():
    """Monotonic insertion sequence; stable tie-break for created_at ordering."""
    _seq_counter[0] += 1
    return _seq_counter[0]
