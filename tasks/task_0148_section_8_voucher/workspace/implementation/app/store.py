"""In-memory data store for all entities.

Each entity is stored in its own dict keyed by id. A coarse-grained re-entrant
lock serializes mutations to make the concurrency posture in §2.12 deterministic.
"""

from __future__ import annotations

from threading import RLock
from typing import Any, Dict, Iterable, List, Optional


_lock = RLock()


def lock() -> RLock:
    return _lock


# Each map holds the canonical dict for one entity instance.
applicants: Dict[str, dict] = {}
vouchers: Dict[str, dict] = {}
units: Dict[str, dict] = {}
payment_standards: Dict[str, dict] = {}
tenancies: Dict[str, dict] = {}
inspections: Dict[str, dict] = {}
rent_reasonableness_records: Dict[str, dict] = {}
annual_reviews: Dict[str, dict] = {}
portability_requests: Dict[str, dict] = {}
hap_payments: Dict[str, dict] = {}


# Network of configured PHAs (PRD §3.2).
CONFIGURED_PHAS = ("PHA_001", "PHA_002", "PHA_003")
DEFAULT_PHA = "PHA_001"


def all_entities() -> Iterable[Dict[str, dict]]:
    return (
        applicants,
        vouchers,
        units,
        payment_standards,
        tenancies,
        inspections,
        rent_reasonableness_records,
        annual_reviews,
        portability_requests,
        hap_payments,
    )


def reset() -> None:
    with _lock:
        for store in all_entities():
            store.clear()
