"""In-memory data store. Each table is a dict id -> entity dict."""
import uuid
import threading

from clock import now, iso


# Tables
labs = {}
users = {}
equipment = {}
billing_rules = {}
maintenance_windows = {}
authorizations = {}
reservations = {}
usage_logs = {}
audit_events = {}

# Side ledgers
payment_ingest_log = {}   # external_payment_id -> reservation_id (for idempotency on payment-confirmed)
im_ingest_log = {}        # (audit_event_id, im_delivery_id) -> True (idempotency)
cost_transfer_ledger = []  # list of dicts

# external_user_id -> user.id (idempotency for /users create)
user_external_index = {}


# Insertion order tracking for stable list ordering by created_at ascending
_seq_lock = threading.Lock()
_seq = 0
_lock = threading.RLock()


def next_seq() -> int:
    global _seq
    with _seq_lock:
        _seq += 1
        return _seq


def lock():
    return _lock


def gen_id() -> str:
    return str(uuid.uuid4())


def stamp_create(d: dict, *, common_fields: bool = True) -> dict:
    ts = iso(now())
    d.setdefault("id", gen_id())
    d["created_at"] = ts
    d["_seq"] = next_seq()
    if common_fields:
        d["updated_at"] = ts
        d["version"] = 1
    return d


def stamp_update(d: dict) -> None:
    if "version" in d:
        d["version"] = d["version"] + 1
    if "updated_at" in d:
        d["updated_at"] = iso(now())


def public(d: dict) -> dict:
    """Strip private fields (those starting with underscore)."""
    return {k: v for k, v in d.items() if not k.startswith("_")}


def reset_all() -> None:
    """Reset all data (useful for tests)."""
    global _seq
    for tbl in [
        labs, users, equipment, billing_rules, maintenance_windows,
        authorizations, reservations, usage_logs, audit_events,
        payment_ingest_log, im_ingest_log, user_external_index,
    ]:
        tbl.clear()
    cost_transfer_ledger.clear()
    with _seq_lock:
        _seq = 0
