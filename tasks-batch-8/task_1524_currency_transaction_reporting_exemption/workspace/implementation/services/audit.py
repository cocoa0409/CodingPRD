"""Append-only audit ledger with sha256 hash chain (SCAFFOLD §1.3 audit_hash_chain).

Ordering rule: automatic system events (SYSTEM_AUTO / SYSTEM_SWEEP) are
appended as the cascade produces them; the single AuditEvent for the client
call itself is appended LAST so its details.side_effects can summarize the
full cascade (per the state-machine side_effects ordering, 'append
AuditEvent' is always the final side effect).
"""
import hashlib
import json

from flask import g

from db import new_id, now_iso, store

GENESIS_HASH = "0" * 64


def canonical_json(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def compute_hash(prev_hash, sequence_no, action, entity_type, entity_id, details):
    payload = "%s|%s|%s|%s|%s|%s" % (
        prev_hash,
        sequence_no,
        action,
        entity_type,
        entity_id,
        canonical_json(details),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def append_event(actor_role, actor_id, action, entity_type, entity_id, details):
    sequence_no = len(store.audit_events) + 1
    prev_hash = store.audit_events[-1]["event_hash"] if store.audit_events else GENESIS_HASH
    event_hash = compute_hash(
        prev_hash, sequence_no, action, entity_type, entity_id, details
    )
    store.seq += 1
    ev = {
        "_seq": store.seq,
        "id": new_id(),
        "sequence_no": sequence_no,
        "actor_role": actor_role,
        "actor_id": actor_id,
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "details": details,
        "prev_hash": prev_hash,
        "event_hash": event_hash,
        "created_at": now_iso(),
    }
    store.audit_events.append(ev)
    return ev


def add_fx(effect):
    """Record a cascade side-effect summary for the in-flight request."""
    fx = getattr(g, "fx", None)
    if fx is None:
        fx = []
        g.fx = fx
    fx.append(effect)


def main_event(action, entity_type, entity_id, before, after):
    """Append the single AuditEvent for the client-driven mutation itself."""
    fx = list(getattr(g, "fx", []) or [])
    details = {"before": before, "after": after, "side_effects": fx}
    return append_event(
        getattr(g, "user_role", None),
        getattr(g, "user_id", None),
        action,
        entity_type,
        entity_id,
        details,
    )


def system_event(action, entity_type, entity_id, before, after):
    """Append an automatic-mutation event (SYSTEM_AUTO or SYSTEM_SWEEP)."""
    details = {"before": before, "after": after, "side_effects": []}
    return append_event("SYSTEM", None, action, entity_type, entity_id, details)


def verify_chain():
    prev_hash = GENESIS_HASH
    checked = 0
    for expected_seq, ev in enumerate(store.audit_events, start=1):
        if ev["sequence_no"] != expected_seq:
            return False, checked
        if ev["prev_hash"] != prev_hash:
            return False, checked
        recomputed = compute_hash(
            ev["prev_hash"],
            ev["sequence_no"],
            ev["action"],
            ev["entity_type"],
            ev["entity_id"],
            ev["details"],
        )
        if recomputed != ev["event_hash"]:
            return False, checked
        prev_hash = ev["event_hash"]
        checked += 1
    return True, checked
