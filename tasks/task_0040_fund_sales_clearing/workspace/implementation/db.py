"""In-memory data store and id/timestamp utilities."""
import threading
import uuid

from clock import now, iso


# Tables (id -> entity dict). Common-fields entities: investors, funds, orders, holdings, dividend_plans, recon_runs.
investors = {}
funds = {}
orders = {}
holdings = {}
dividend_plans = {}
recon_runs = {}

# Non-common-fields entities (only id + created_at):
nav_snapshots = {}
lot_entries = {}
dividend_distributions = {}
recon_exceptions = {}
settlement_instructions = {}
audit_logs = {}

# Idempotency index: (investor_id, idempotency_key) -> order_id
idempotency_index = {}

_seq_lock = threading.Lock()
_seq = 0
_lock = threading.Lock()


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
        investors, funds, orders, holdings, dividend_plans, recon_runs,
        nav_snapshots, lot_entries, dividend_distributions, recon_exceptions,
        settlement_instructions, audit_logs, idempotency_index,
    ]:
        tbl.clear()
    with _seq_lock:
        _seq = 0
