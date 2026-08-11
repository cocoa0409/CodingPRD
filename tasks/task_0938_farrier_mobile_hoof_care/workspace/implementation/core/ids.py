"""Server-minted identifiers.

Every id is a UUID string with no type prefix and no embedded meaning
(PRD 2.4).  A monotonic counter occupies the leading 12 hex digits so that the
ascending lexicographic order of ids matches creation order; the remainder is
random.  The result still parses as a valid RFC 4122 version-4 UUID string.
"""

import random
import threading

_lock = threading.Lock()
_counter = 0
_rng = random.Random()


def new_id():
    global _counter
    with _lock:
        _counter += 1
        n = _counter
    head = "%012x" % (n & 0xFFFFFFFFFFFF)
    node = "%012x" % _rng.getrandbits(48)
    seq = "%03x" % _rng.getrandbits(12)
    variant = "%01x" % (8 + _rng.getrandbits(2))
    clock_seq = "%03x" % _rng.getrandbits(12)
    return "%s-%s-4%s-%s%s-%s" % (head[:8], head[8:12], seq, variant, clock_seq, node)


def new_request_id():
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    return "req_" + "".join(_rng.choice(alphabet) for _ in range(20))


def reset():
    global _counter
    with _lock:
        _counter = 0
