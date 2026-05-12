"""Resource lookup helpers."""
import db
from errors import err


def get_customer(cust_id: str, *, body_ref: bool = False) -> dict:
    c = db.customers.get(cust_id)
    if c is None:
        if body_ref:
            raise err("ERR_CUSTOMER_NOT_FOUND", f"Customer {cust_id} not found")
        raise err("ERR_NOT_FOUND", f"Customer {cust_id} not found")
    return c


def get_evidence(ev_id: str) -> dict:
    e = db.evidences.get(ev_id)
    if e is None:
        raise err("ERR_NOT_FOUND", f"Evidence {ev_id} not found")
    return e


def get_batch(b_id: str) -> dict:
    b = db.batches.get(b_id)
    if b is None:
        raise err("ERR_NOT_FOUND", f"Batch {b_id} not found")
    return b


def get_certificate(c_id: str) -> dict:
    c = db.certificates.get(c_id)
    if c is None:
        raise err("ERR_NOT_FOUND", f"Certificate {c_id} not found")
    return c


def get_judicial_package(p_id: str) -> dict:
    p = db.judicial_packages.get(p_id)
    if p is None:
        raise err("ERR_NOT_FOUND", f"JudicialPackage {p_id} not found")
    return p


def get_notarization(n_id: str) -> dict:
    n = db.timestamp_notarizations.get(n_id)
    if n is None:
        raise err("ERR_NOT_FOUND", f"TimestampNotarization {n_id} not found")
    return n


def get_recharge(r_id: str) -> dict:
    r = db.recharges.get(r_id)
    if r is None:
        raise err("ERR_NOT_FOUND", f"Recharge {r_id} not found")
    return r


def get_invoice(i_id: str) -> dict:
    i = db.invoices.get(i_id)
    if i is None:
        raise err("ERR_NOT_FOUND", f"Invoice {i_id} not found")
    return i


def get_on_chain_tx(t_id: str) -> dict:
    t = db.on_chain_txs.get(t_id)
    if t is None:
        raise err("ERR_NOT_FOUND", f"OnChainTx {t_id} not found")
    return t


def notarization_for_evidence(ev_id: str) -> dict:
    for n in db.timestamp_notarizations.values():
        if n["evidence_id"] == ev_id:
            return n
    return None


def certificate_for_evidence(ev_id: str) -> dict:
    """Return the (newest by created_at) certificate for an evidence, or None."""
    rows = [c for c in db.certificates.values() if c["evidence_id"] == ev_id]
    if not rows:
        return None
    rows.sort(key=lambda r: r["_seq"], reverse=True)
    return rows[0]


def batch_members(batch_id: str) -> list:
    rows = [e for e in db.evidences.values() if e.get("batch_id") == batch_id]
    rows.sort(key=lambda r: r["_seq"])
    return rows


def latest_on_chain_tx_for_evidence(ev_id: str) -> dict:
    rows = [t for t in db.on_chain_txs.values() if t.get("evidence_id") == ev_id]
    if not rows:
        return None
    rows.sort(key=lambda r: r.get("attempt_index", 0), reverse=True)
    return rows[0]


def latest_on_chain_tx_for_batch(batch_id: str) -> dict:
    rows = [t for t in db.on_chain_txs.values() if t.get("batch_id") == batch_id]
    if not rows:
        return None
    rows.sort(key=lambda r: r.get("attempt_index", 0), reverse=True)
    return rows[0]
