"""In-memory data store."""
import uuid
import threading
from clock import now, to_iso_ms


# Singleton state — separate dicts keyed by id
state = {
    "members": {},
    "card_types": {},
    "cards": {},
    "trainers": {},
    "trainer_slots": {},
    "pt_bookings": {},
    "pt_packages": {},
    "group_classes": {},
    "group_bookings": {},
    "wallet_transactions": {},
    "freeze_episodes": {},
    "transfer_records": {},
    "commission_records": {},
    "payout_cycles": {},
    "renewal_reminders": {},
    "audit_log": {},
}

# A lock used to make multi-step operations atomic enough for our in-memory store.
lock = threading.RLock()

# An order counter for stable, monotonic created_at tie-breaking across appends.
_order_counter = 0


def next_order() -> int:
    global _order_counter
    _order_counter += 1
    return _order_counter


def new_id() -> str:
    return str(uuid.uuid4())


def stamp_create(obj: dict, with_common_fields: bool = True):
    """Mint common system fields on create."""
    if "id" not in obj:
        obj["id"] = new_id()
    ts = now()
    obj["created_at"] = ts
    if with_common_fields:
        obj["updated_at"] = ts
        obj["version"] = 1
    obj["_order"] = next_order()


def bump(obj: dict):
    """Bump updated_at/version on mutation."""
    obj["updated_at"] = now()
    obj["version"] = obj.get("version", 1) + 1


def reset_all():
    """Reset all stores (used for tests)."""
    global _order_counter
    for k in state:
        state[k] = {} if isinstance(state[k], dict) else []
    _order_counter = 0
