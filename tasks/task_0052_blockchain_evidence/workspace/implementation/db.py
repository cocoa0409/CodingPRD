"""In-memory data store. Each table is a dict id -> entity dict."""
import threading
import uuid

from clock import iso, now


# ---- Tables ----
customers = {}
fee_accounts = {}                # customer_id -> fee_account dict
evidences = {}
on_chain_txs = {}
batches = {}
certificates = {}
timestamp_notarizations = {}
judicial_packages = {}
verification_reports = {}
recharges = {}
invoices = {}
audit_logs = {}

# Indices for uniqueness lookup.
recharge_ref_index = {}          # external_payment_ref -> recharge_id
idempotency_index = {}           # (customer_id, idempotency_key) -> evidence_id
verification_code_index = {}     # verification_code -> certificate_id


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
    ts = iso(now())
    if "version" in d:
        d["version"] = d["version"] + 1
    if "updated_at" in d:
        d["updated_at"] = ts


def public(d: dict) -> dict:
    """Strip private fields (those starting with underscore)."""
    return {k: v for k, v in d.items() if not k.startswith("_")}


def reset_all() -> None:
    global _seq
    for tbl in [
        customers, fee_accounts, evidences, on_chain_txs, batches,
        certificates, timestamp_notarizations, judicial_packages,
        verification_reports, recharges, invoices, audit_logs,
        recharge_ref_index, idempotency_index, verification_code_index,
    ]:
        tbl.clear()
    with _seq_lock:
        _seq = 0
