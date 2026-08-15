"""In-memory data store. All state lives in module-level dicts keyed by id.
The store starts EMPTY on every boot — no seeding of any kind.
A monotonic sequence orders creation for created_at ties.
"""
import itertools

# Logical clock state (single mutable holder)
_clock = {
    # Startup default per PRD §2.5: exactly 2026-08-01T00:00:00Z
    "now": None,  # set below via reset()
}

_seq = itertools.count(1)

stores = {
    "vendors": {},
    "content_ledger_events": {},          # id -> event (append-only)
    "instruments": {},
    "evidence": {},
    "guides": {},
    "requisitions": {},
    "cycles": {},
    "candidates": {},
    "assessments": {},
    "accommodation_requests": {},
    "interviewers": {},
    "calibrations": {},
    "sessions": {},
    "scorecards": {},
    "decisions": {},
    "snapshots": {},
    "purge_events": {},                    # id -> event (append-only)
}


def next_seq():
    return next(_seq)


def reset():
    """Reset everything to the pristine boot state."""
    from datetime import datetime, timezone
    for k in stores:
        stores[k].clear()
    _clock["now"] = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def get_now():
    return _clock["now"]


def set_now(dt):
    _clock["now"] = dt


reset()
