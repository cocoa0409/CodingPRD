"""Monotonic identifier minting.

PRD 2.4: "Every resource in the system carries a server-minted `id` -- a UUID
string with no type prefix of any kind".

The ids are UUID-shaped but MONOTONIC: a 48-bit process-local counter occupies
the high bits, so ascending `id` == creation order.  The logical clock is
coarse (many rows share one `created_at`), which makes the `id` tie-break in
list ordering load-bearing; random UUIDs would make same-instant ordering
nondeterministic and therefore flaky.
"""

import os
import threading

_lock = threading.Lock()
_counter = 0
_ENTROPY = os.urandom(8)


def _hex(n, width):
    return ("%0" + str(width) + "x") % n


def new_id():
    """Mint the next monotonic UUID-shaped identifier."""
    global _counter
    with _lock:
        _counter += 1
        n = _counter
    hi = _hex(n, 12)                       # 48-bit counter -> time_low + time_mid
    # Version 4 nibble and RFC-4122 variant bits keep the string UUID-shaped.
    tail = _ENTROPY.hex()                  # 16 hex chars of per-process entropy
    return "%s-%s-4%s-8%s-%s%s" % (
        hi[0:8], hi[8:12], tail[0:3], tail[3:6], tail[6:16], _hex(n, 2)[-2:],
    )


_ALNUM = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
_req_counter = 0


def new_request_id():
    """PRD 2.2: a server-generated unique request identifier starting with `req_`."""
    global _req_counter
    with _lock:
        _req_counter += 1
        n = _req_counter
    body = []
    seed = n
    for _ in range(20):
        body.append(_ALNUM[seed % len(_ALNUM)])
        seed = seed // len(_ALNUM) + 7
    return "req_" + "".join(body)
