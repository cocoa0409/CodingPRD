"""Audit log helpers."""

import hashlib
import json
from flask import g, has_request_context

import db


def _digest(payload):
    if payload is None:
        return hashlib.sha256(b"").hexdigest()
    try:
        s = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        s = str(payload)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def append(action: str, subject_type: str, subject_id: str, lc_id: str = None,
           before_state: str = None, after_state: str = None, payload=None,
           actor_role: str = None, actor_id: str = None):
    """Append an audit log entry. Uses flask.g for actor when available."""
    if actor_role is None and has_request_context():
        actor_role = getattr(g, "role", None)
    if actor_id is None and has_request_context():
        actor_id = getattr(g, "user_id", None)
    if actor_role is None:
        actor_role = "system"

    return db.insert("audit_log_entries", {
        "actor_role": actor_role,
        "actor_id": actor_id,
        "action": action,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "lc_id": lc_id,
        "before_state": before_state,
        "after_state": after_state,
        "payload_digest": _digest(payload),
    }, with_version=False)
