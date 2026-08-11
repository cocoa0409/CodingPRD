"""Deterministic, monotonic, UUID-shaped identifiers.

The logical clock is coarse: many rows are created at the very same `created_at`
instant, and PRD 2.3 orders list results by `created_at` ascending.  Random UUIDs
would make same-instant ordering nondeterministic, so the high 32 bits of every
id carry a process-monotonic counter: ascending id == creation order.  The rest
of the id is drawn from a deterministic counter-seeded stream so the value is
still a syntactically valid, never-reused UUID string.

This is NOT seeded data — no entity row exists at boot; only the counter does.
"""

import threading

_lock = threading.Lock()
_state = {"n": 0}


def reset():
    with _lock:
        _state["n"] = 0


def next_seq():
    with _lock:
        _state["n"] += 1
        return _state["n"]


def new_id(seq=None):
    """Mint a UUID-shaped string whose lexical order matches creation order."""
    n = next_seq() if seq is None else seq
    # 8-4-4-4-12 hex, version nibble 4 and variant nibble 8 kept UUID-legal.
    a = n & 0xFFFFFFFF
    b = (n >> 8) & 0xFFFF
    c = n & 0x0FFF
    d = 0x8000 | (n & 0x0FFF)
    e = n & 0xFFFFFFFFFFFF
    return "%08x-%04x-4%03x-%04x-%012x" % (a, b, c, d, e)
