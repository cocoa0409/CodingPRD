"""In-memory data store. Each table is a dict id -> entity dict."""
import uuid
import threading

from clock import now, iso


# Tables (one dict per entity)
counselors = {}
clients = {}
certification_cycles = {}
availability_slots = {}
appointments = {}
counseling_records = {}
crisis_incidents = {}
settlement_ledger = {}
payouts = {}
supervision_sessions = {}
ce_records = {}
audit_log = {}


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
    if d is None:
        return None
    return {k: v for k, v in d.items() if not k.startswith("_")}


def reset_all() -> None:
    global _seq
    for tbl in [
        counselors, clients, certification_cycles, availability_slots,
        appointments, counseling_records, crisis_incidents, settlement_ledger,
        payouts, supervision_sessions, ce_records, audit_log,
    ]:
        tbl.clear()
    with _seq_lock:
        _seq = 0
