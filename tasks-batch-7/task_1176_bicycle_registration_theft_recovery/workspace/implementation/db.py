"""In-memory data store, logical clock, id/sequence minting, mutation helpers."""
import uuid
from datetime import datetime, timezone

# --- entity tables (empty at boot; nothing is seeded) -----------------------
owners = {}
partner_orgs = {}
bicycles = {}
transfers = {}
theft_reports = {}
intakes = {}
matches = {}
claims = {}
auctions = {}
bids = {}
events = {}
event_registrations = {}
duplicate_flags = {}
ledger = {}
notifications = {}

# --- logical clock (PRD §2.4) ------------------------------------------------
_CLOCK_DEFAULT = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = {"now": _CLOCK_DEFAULT}

_seq = {"n": 0}


def now():
    return _clock["now"]


def set_clock(dt):
    _clock["now"] = dt


def next_seq():
    _seq["n"] += 1
    return _seq["n"]


def new_id():
    return str(uuid.uuid4())


def new_record(fields, ledger_entry=False):
    """Create a record dict with system-managed common fields (PRD §2.5).

    LedgerEntry is append-only: only id + created_at, no updated_at/version.
    """
    rec = dict(fields)
    rec["id"] = new_id()
    rec["created_at"] = now()
    rec["_seq"] = next_seq()
    if not ledger_entry:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    return rec


def bump(rec):
    """Every mutation increments version by 1 and refreshes updated_at."""
    rec["version"] += 1
    rec["updated_at"] = now()


def post_ledger(entry_type, direction, account, amount_cents,
                owner_id=None, partner_org_id=None, auction_id=None,
                bicycle_id=None, reference_note=None):
    rec = new_record({
        "entry_type": entry_type,
        "direction": direction,
        "account": account,
        "amount_cents": int(amount_cents),
        "owner_id": owner_id,
        "partner_org_id": partner_org_id,
        "auction_id": auction_id,
        "bicycle_id": bicycle_id,
        "reference_note": reference_note,
    }, ledger_entry=True)
    ledger[rec["id"]] = rec
    return rec


def notify(owner_id, kind, message, related_entity_type=None, related_entity_id=None):
    rec = new_record({
        "owner_id": owner_id,
        "kind": kind,
        "message": message,
        "related_entity_type": related_entity_type,
        "related_entity_id": related_entity_id,
        "read": False,
    })
    notifications[rec["id"]] = rec
    return rec
