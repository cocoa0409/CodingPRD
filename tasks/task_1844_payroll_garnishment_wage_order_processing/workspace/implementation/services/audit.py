"""Append-only, hash-chained audit log (PRD §2.11, calc audit_chain_integrity).

entry_hash[i] = sha256_hex(prev_hash[i] | payload_hash[i] | created_at[i])
prev_hash[0]  = 'GENESIS'; prev_hash[i] = entry_hash[i-1]  (per employer)
"""

import hashlib
import json

from flask import g

from db import logical_now, next_seq, store
from util import new_uuid, render_instant


def _sha256_hex(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _canonical(payload):
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def employer_chain(employer_id):
    entries = [
        e for e in store.audit_entries.values() if e["employer_id"] == employer_id
    ]
    # Ordered by created_at ASC, monotonic sequence disambiguating ties.
    return sorted(entries, key=lambda e: (e["created_at"], e["_seq"]))


def append_audit(employer_id, entity_type, entity_id, action, details=None,
                 actor_role=None, actor_id=None):
    try:
        role = actor_role or g.user_role
        actor = actor_id or g.user_id
    except RuntimeError:
        role = actor_role or "SYSTEM"
        actor = actor_id or "system"

    created_at = render_instant(logical_now())
    payload = {
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "actor_role": role,
        "actor_id": actor,
        "details": details or {},
    }
    payload_hash = _sha256_hex(_canonical(payload))

    chain = employer_chain(employer_id)
    prev_hash = chain[-1]["entry_hash"] if chain else "GENESIS"
    entry_hash = _sha256_hex(prev_hash + "|" + payload_hash + "|" + created_at)

    entry = {
        "id": new_uuid(),
        "created_at": created_at,
        "employer_id": employer_id,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "action": action,
        "actor_role": role,
        "actor_id": actor,
        "payload_hash": payload_hash,
        "prev_hash": prev_hash,
        "entry_hash": entry_hash,
        "_seq": next_seq(),
    }
    store.audit_entries[entry["id"]] = entry
    return entry


def verify_chain(employer_id):
    """Recompute every entry_hash and re-walk every prev_hash link."""
    prev_hash = "GENESIS"
    for entry in employer_chain(employer_id):
        if entry["prev_hash"] != prev_hash:
            return False
        recomputed = _sha256_hex(
            entry["prev_hash"] + "|" + entry["payload_hash"] + "|" + entry["created_at"]
        )
        if recomputed != entry["entry_hash"]:
            return False
        prev_hash = entry["entry_hash"]
    return True
