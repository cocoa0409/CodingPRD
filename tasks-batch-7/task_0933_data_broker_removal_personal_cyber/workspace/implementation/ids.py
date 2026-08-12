"""Monotonic, UUID-shaped identifier minting.

The logical clock is coarse: many rows legitimately share a `created_at`, so the
PRD's documented `id` tie-break becomes load-bearing for list ordering. A random
UUID4 would make same-instant ordering nondeterministic and produce genuinely
flaky list tests. Every id minted here is a valid 36-character UUID string whose
leading 48 bits carry a monotonic counter, so ascending `id` == creation order.

This is a determinism measure only; it seeds no data.
"""

import os
import threading

_lock = threading.Lock()
_counter = 0


def reset() -> None:
    global _counter
    with _lock:
        _counter = 0


def new_id() -> str:
    """Mint a UUID-shaped string that sorts by creation order."""
    global _counter
    with _lock:
        _counter += 1
        n = _counter
    # 48-bit monotonic prefix (12 hex chars), then a version-4 nibble, then
    # random entropy with the RFC-4122 variant bits pinned.
    prefix = f"{n & 0xFFFFFFFFFFFF:012x}"
    rand = os.urandom(10).hex()  # 20 hex chars
    body = prefix + "4" + rand[1:5] + "8" + rand[6:20]
    # body is exactly 32 hex characters
    return f"{body[0:8]}-{body[8:12]}-{body[12:16]}-{body[16:20]}-{body[20:32]}"


def new_token(prefix: str = "") -> str:
    """Opaque server-issued token (invitation tokens, request ids)."""
    return prefix + os.urandom(12).hex()
