"""In-memory data store. Entirely process-local: a fresh boot starts empty.

NO seeding, preloading, or hardcoded entity data anywhere in this module or
its consumers — every entity is created through the declared API surface.
"""

import threading
import uuid
from datetime import datetime, timezone

LOCK = threading.RLock()

STORE = {
    "recipes": {},
    "components": {},
    "customers": {},
    "orders": {},
    "batches": {},
    "cells": {},
    "cycles": {},
    "lines": {},
    "runs": {},
    "film_lots": {},
    "ccp_checks": {},
    "slots": {},
    "lots": {},
    "complaints": {},
}

_SEQ = [0]


def next_seq():
    _SEQ[0] += 1
    return _SEQ[0]


def new_id():
    return str(uuid.uuid4())


def now_str():
    """ISO 8601 UTC wall-clock timestamp with three fractional digits (PRD §2.5).
    Used for created_at / updated_at / meta timestamps."""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


# ---- Server logical clock (PRD §2.6) ----
# Starts at exactly 2026-08-01T00:00:00Z; never falls back to wall-clock time.
DEFAULT_CLOCK_RAW = "2026-08-01T00:00:00Z"
CLOCK = {"dt": datetime(2026, 8, 1, tzinfo=timezone.utc), "raw": DEFAULT_CLOCK_RAW}


def logical_now():
    return CLOCK["dt"]


def set_logical_clock(dt):
    CLOCK["dt"] = dt


def new_record(common=True):
    """Fresh system-managed fields. common=False -> CCPCheck
    (id + created_at only, no updated_at/version per PRD §2.5)."""
    rec = {
        "id": new_id(),
        "created_at": now_str(),
        "_seq": next_seq(),
    }
    if common:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    return rec


def bump(rec):
    """Refresh updated_at and advance version by exactly one (PRD §2.5)."""
    rec["updated_at"] = now_str()
    rec["version"] += 1
