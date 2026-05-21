"""In-memory data store — one big lock guards all mutations."""
from __future__ import annotations

import threading
import uuid
from typing import Any


def gen_id() -> str:
    return str(uuid.uuid4())


class Store:
    def __init__(self) -> None:
        self.lock = threading.RLock()

        # Primary tables keyed by id
        self.marinas: dict[str, dict[str, Any]] = {}
        self.boaters: dict[str, dict[str, Any]] = {}
        self.vessels: dict[str, dict[str, Any]] = {}
        self.slips: dict[str, dict[str, Any]] = {}
        self.reservations: dict[str, dict[str, Any]] = {}
        self.waitlist: dict[str, dict[str, Any]] = {}
        self.transfer_requests: dict[str, dict[str, Any]] = {}
        self.pump_out_jobs: dict[str, dict[str, Any]] = {}
        self.utility_readings: dict[str, dict[str, Any]] = {}
        self.utility_settlements: dict[str, dict[str, Any]] = {}
        self.policies: dict[str, dict[str, Any]] = {}
        self.tow_contracts: dict[str, dict[str, Any]] = {}
        self.tow_events: dict[str, dict[str, Any]] = {}

        # Per-marina monotonic waitlist sequence counters
        self.waitlist_seq: dict[str, int] = {}


store = Store()
