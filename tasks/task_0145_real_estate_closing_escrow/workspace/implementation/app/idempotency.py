"""Idempotency-Key helpers.

Every POST and state-transition endpoint requires an Idempotency-Key header.
If the same key is replayed with an identical request body, we return the
original response; if it is replayed with a *different* body, we reject with
ERR_IDEMPOTENCY_REPLAY_MISMATCH.

This helper is intentionally minimal: route handlers call `lookup(...)` at the
start and `store(...)` once they have a (status, body) response to return.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from flask import request

from app import store
from app.errors import ApiError
from app.util import canonical_payload_hash


def require_idempotency_key() -> str:
    key = request.headers.get("Idempotency-Key")
    if not key:
        raise ApiError("ERR_BAD_REQUEST", "Idempotency-Key header required.")
    return key


def lookup(idempotency_key: str, request_body: Any) -> Optional[Tuple[int, Dict[str, Any]]]:
    """Return a cached (status, body) tuple if this key was used before.

    - If the prior body hash matches, return the cached response.
    - If it does not match, raise ERR_IDEMPOTENCY_REPLAY_MISMATCH.
    - If unseen, return None — the caller may proceed and call ``store(...)``.
    """
    cached = store.idempotency_cache.get(idempotency_key)
    if cached is None:
        return None
    cached_hash, status, body = cached
    if cached_hash != canonical_payload_hash(request_body):
        raise ApiError(
            "ERR_IDEMPOTENCY_REPLAY_MISMATCH",
            "Idempotency-Key was previously used with a different request body.",
        )
    return status, body


def remember(idempotency_key: str, request_body: Any, status: int, body: Dict[str, Any]) -> None:
    store.idempotency_cache[idempotency_key] = (
        canonical_payload_hash(request_body),
        status,
        body,
    )
