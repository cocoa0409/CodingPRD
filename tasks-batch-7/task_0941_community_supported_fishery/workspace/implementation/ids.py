"""Server-minted identifiers (PRD 2.4: "a UUID string with no type prefix").

Ordering rules in this system tie-break on created_at, and the logical clock
means many rows share one created_at value.  Random UUIDs would then make
same-instant ordering nondeterministic, so the counter that establishes
creation order is placed in the HIGH bits of the UUID: ascending id string ==
ascending creation order, while the string remains a syntactically valid
version-4 UUID.
"""
import os
import threading

_lock = threading.Lock()
_counter = 0


def _next():
    global _counter
    with _lock:
        _counter += 1
        return _counter


def new_id():
    """Mint a UUID-shaped id whose lexical order is creation order."""
    n = _next()
    # 12 hex digits of monotonic counter across the first two groups.
    hi = (n >> 16) & 0xFFFFFFFF
    mid = n & 0xFFFF
    rand = os.urandom(8)
    # version 4 nibble, RFC-4122 variant nibble, then random tail.
    g3 = 0x4000 | (rand[0] << 4 | (rand[1] >> 4)) & 0x0FFF
    g4 = 0x8000 | ((rand[2] << 6) | (rand[3] >> 2)) & 0x3FFF
    g5 = int.from_bytes(rand[4:8], "big") & 0xFFFFFFFF
    tail = (g5 << 16) | (rand[1] & 0xFFFF)
    return "%08x-%04x-%04x-%04x-%012x" % (hi, mid, g3, g4, tail & 0xFFFFFFFFFFFF)


def new_request_id():
    """Envelope api_request_id: "a server-generated unique identifier for the
    request that starts with req_" (PRD 2.2)."""
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    raw = os.urandom(20)
    return "req_" + "".join(alphabet[b % 36] for b in raw)


def reset():
    global _counter
    with _lock:
        _counter = 0
