"""In-memory data store.

Holds all entity dictionaries keyed by id, plus a process-wide RLock for atomicity.
Insertion order is preserved so list endpoints return results sorted by created_at
(ascending) without an extra sort.
"""
from __future__ import annotations

import uuid
from threading import RLock
from typing import Dict


def new_id() -> str:
    return str(uuid.uuid4())


class Store:
    def __init__(self):
        self.lock = RLock()
        self.taxpayers: Dict[str, dict] = {}
        self.tax_liabilities: Dict[str, dict] = {}
        self.installment_agreements: Dict[str, dict] = {}
        self.payments: Dict[str, dict] = {}
        self.offers: Dict[str, dict] = {}
        self.liens: Dict[str, dict] = {}
        self.tolling_events: Dict[str, dict] = {}
        self.reconsiderations: Dict[str, dict] = {}
        self.cnc_statuses: Dict[str, dict] = {}


STORE = Store()
