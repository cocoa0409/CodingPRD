"""In-memory store.

Every table starts EMPTY on boot.  Nothing here is ever seeded, preloaded or
hardcoded: tests build all preconditions through the declared API surface.
"""

import random
import time

insurance_plans = {}
patients = {}
prescriptions = {}
fill_cycles = {}
cycle_lines = {}
pouch_rolls = {}
pouches = {}
refill_authorizations = {}
shipments = {}
vacation_exceptions = {}
credit_memos = {}
adherence_events = {}

# A UUID version 7 generator: a 48-bit millisecond timestamp, then a
# monotonic intra-millisecond counter, then randomness.  Identifiers are
# therefore opaque UUID strings that also sort in creation order, so the
# documented "ascending created_at, ascending id" list ordering is stable
# even when many rows share one logical-clock timestamp (PRD 2.3 / 2.5).
_clock_state = {"ms": 0, "seq": 0}


def new_id():
    ms = int(time.time() * 1000)
    if ms > _clock_state["ms"]:
        _clock_state["ms"] = ms
        _clock_state["seq"] = 0
    else:
        _clock_state["seq"] += 1
        if _clock_state["seq"] > 0xFFF:
            _clock_state["ms"] += 1
            _clock_state["seq"] = 0
    ms = _clock_state["ms"]
    return "%08x-%04x-7%03x-%04x-%012x" % (
        (ms >> 16) & 0xFFFFFFFF,
        ms & 0xFFFF,
        _clock_state["seq"],
        0x8000 | random.getrandbits(14),
        random.getrandbits(48),
    )
