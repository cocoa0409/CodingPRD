"""Season audit log: append-only, hash-chained (PRD 2.11).

hash_chain_prev: SHA-256 of the previous row in the same season (genesis uses
64 zero hex chars). hash_chain_self: SHA-256 over
(hash_chain_prev || action || target_id || canonical(detail)).
"""
import hashlib
import json

import store
from util import new_child_record

GENESIS = "0" * 64


def _canonical(detail):
    return json.dumps(detail if detail is not None else {},
                      sort_keys=True, separators=(",", ":"), default=str)


def _self_hash(prev, action, target_id, detail):
    h = hashlib.sha256()
    h.update(prev.encode("utf-8"))
    h.update((action or "").encode("utf-8"))
    h.update((target_id or "").encode("utf-8"))
    h.update(_canonical(detail).encode("utf-8"))
    return h.hexdigest()


def season_rows(season_id):
    rows = [r for r in store.audit_logs.values() if r["season_id"] == season_id]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rows


def append(season_id, actor_role, actor_id, action, target_type, target_id, detail=None):
    rows = season_rows(season_id)
    prev = rows[-1]["hash_chain_self"] if rows else GENESIS
    rec = new_child_record()
    rec.update({
        "season_id": season_id,
        "actor_role": actor_role,
        "actor_id": actor_id,
        "action": action,
        "target_type": target_type,
        "target_id": target_id,
        "detail": detail if detail is not None else {},
        "hash_chain_prev": prev,
        "hash_chain_self": _self_hash(prev, action, target_id, detail),
    })
    store.audit_logs[rec["id"]] = rec
    return rec


def verify_chain(season_id):
    """Re-verify the chain row by row. Returns True when intact."""
    prev = GENESIS
    for row in season_rows(season_id):
        if row["hash_chain_prev"] != prev:
            return False
        expect = _self_hash(row["hash_chain_prev"], row["action"],
                            row["target_id"], row["detail"])
        if expect != row["hash_chain_self"]:
            return False
        prev = row["hash_chain_self"]
    return True
