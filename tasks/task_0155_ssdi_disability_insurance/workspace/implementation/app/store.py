"""In-memory data store for all entities.

Each entity is stored in its own dict keyed by id. A coarse-grained re-entrant
lock serializes mutations to make the concurrency posture in §3.4 / §3.7 /
§3.8 deterministic.
"""

from __future__ import annotations

from threading import RLock
from typing import Dict, Iterable


_lock = RLock()


def lock() -> RLock:
    return _lock


claimants: Dict[str, dict] = {}
quarter_credits: Dict[str, dict] = {}
medical_evidence: Dict[str, dict] = {}
applications: Dict[str, dict] = {}
determinations: Dict[str, dict] = {}
hearing_slots: Dict[str, dict] = {}
child_auxiliaries: Dict[str, dict] = {}
ssi_supplements: Dict[str, dict] = {}
cdr_reviews: Dict[str, dict] = {}


def all_entities() -> Iterable[Dict[str, dict]]:
    return (
        claimants,
        quarter_credits,
        medical_evidence,
        applications,
        determinations,
        hearing_slots,
        child_auxiliaries,
        ssi_supplements,
        cdr_reviews,
    )


def reset() -> None:
    with _lock:
        for store in all_entities():
            store.clear()
