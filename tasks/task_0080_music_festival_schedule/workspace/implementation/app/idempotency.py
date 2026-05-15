"""Idempotency-key check from §1.4 priority-22 and PRD §2.5.

The four endpoints that honour the body field `idempotency_key` are
(per PRD §2.5): schedule-changes create, schedule-changes apply,
program-item cancel, and ticket-type issue.  Other POSTs ignore the
field even when the client sends it.

The window during which the key is active is `IDEMPOTENCY_WINDOW_SECONDS = 86400`.
A second POST with the same key + same body hash returns the stored
response with `is_idempotent_replay: true` on the meta block and skips
the side-effects.  A same-key-different-body collision raises
`ERR_IDEMPOTENCY_KEY_REUSED`.
"""
from __future__ import annotations

import time as _time
from typing import Any, Callable, Dict, Optional, Tuple

from flask import Response, g, jsonify

from .auth import actor_tuple
from .errors import ApiError
from .storage import IDEMPOTENCY_STORE, real_now_unix


def idempotency_lookup_or_store(
    endpoint_label: str,
    idempotency_key: Optional[str],
    body: dict,
    festival_for_clock: Optional[dict],
    now_unix_override: Optional[int] = None,
) -> Tuple[Optional[Response], Optional[Callable[[int, dict], None]]]:
    """If a stored entry matches the (label, key, actor, body-hash) triple,
    return a Flask response that replays it; otherwise return a `store`
    callback the caller should invoke after the request's normal handler
    finishes successfully.

    The clock source for the expiry check is `real_now + Festival.clock_offset_seconds`
    per PRD §2.5; when no festival context is supplied (the harness's bare
    test), we fall back to the wall clock.
    """
    if not idempotency_key:
        return None, None

    actor_id, _role = actor_tuple()

    body_hash = IDEMPOTENCY_STORE.body_hash(body)

    if now_unix_override is not None:
        now_unix = int(now_unix_override)
    elif festival_for_clock is not None:
        now_unix = int(real_now_unix()) + int(
            festival_for_clock.get("clock_offset_seconds", 0)
        )
    else:
        now_unix = int(real_now_unix())

    outcome, entry = IDEMPOTENCY_STORE.lookup(
        endpoint_label, idempotency_key, actor_id, body_hash, now_unix
    )

    if outcome == "replay":
        # Replay the stored response verbatim, but stamp the new request
        # id and timestamp on the meta block and set the
        # `is_idempotent_replay: true` flag per PRD §2.5.  The stored
        # status code is honoured.
        stored_body = entry["response_body"]
        new_body = dict(stored_body)
        new_meta = dict(stored_body.get("meta", {}))
        new_meta["api_request_id"] = getattr(g, "api_request_id", new_meta.get("api_request_id"))
        new_meta["api_request_timestamp"] = getattr(
            g, "api_request_timestamp", new_meta.get("api_request_timestamp")
        )
        new_meta["is_idempotent_replay"] = True
        new_body["meta"] = new_meta
        resp = jsonify(new_body)
        resp.status_code = int(entry["status_code"])
        resp.headers["Content-Type"] = "application/json"
        return resp, None

    if outcome == "conflict":
        raise ApiError(
            "ERR_IDEMPOTENCY_KEY_REUSED",
            f"idempotency_key {idempotency_key!r} was used with a different body within the window",
        )

    # Fresh key — return a `store` callback the route handler invokes with
    # the final status code and the envelope-body dict on success.
    def _store(status_code: int, envelope_body: Dict[str, Any]) -> None:
        IDEMPOTENCY_STORE.store(
            endpoint_label,
            idempotency_key,
            actor_id,
            body_hash,
            status_code,
            envelope_body,
            now_unix,
        )

    return None, _store
