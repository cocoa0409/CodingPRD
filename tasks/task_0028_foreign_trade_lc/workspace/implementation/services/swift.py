"""SWIFT message emission with deterministic idempotency."""

import hashlib
import db


def _idempotency_key(subject_type, subject_id, message_type) -> str:
    base = f"{subject_type}|{subject_id}|{message_type}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def emit(message_type: str, subject_type: str, subject_id: str, lc_id: str,
         sender_bic: str, receiver_bic: str, payload: dict):
    """Emit SwiftMessage row idempotently. Returns existing row when already emitted."""
    key = _idempotency_key(subject_type, subject_id, message_type)
    existing = db.find_one("swift_messages", idempotency_key=key)
    if existing is not None:
        return existing
    return db.insert("swift_messages", {
        "message_type": message_type,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "lc_id": lc_id,
        "sender_bic": sender_bic or "",
        "receiver_bic": receiver_bic or "",
        "payload": payload or {},
        "idempotency_key": key,
    }, with_version=False)
