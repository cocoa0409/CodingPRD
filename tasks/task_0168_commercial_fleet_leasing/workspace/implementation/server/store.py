"""In-memory data store. A single RLock guards all read-then-write critical sections."""
from __future__ import annotations

import threading
import uuid
from typing import Any


def gen_id() -> str:
    return str(uuid.uuid4())


class Store:
    """Tables keyed by id."""

    def __init__(self) -> None:
        self.lock = threading.RLock()

        # Primary entities
        self.lessees: dict[str, dict[str, Any]] = {}
        self.vehicles: dict[str, dict[str, Any]] = {}
        self.lease_agreements: dict[str, dict[str, Any]] = {}
        self.fuel_cards: dict[str, dict[str, Any]] = {}
        self.fuel_card_transactions: dict[str, dict[str, Any]] = {}
        self.telematics_events: dict[str, dict[str, Any]] = {}
        self.maintenance_tickets: dict[str, dict[str, Any]] = {}
        self.collision_claims: dict[str, dict[str, Any]] = {}
        self.overage_settlements: dict[str, dict[str, Any]] = {}
        self.ifta_quarters: dict[str, dict[str, Any]] = {}


store = Store()
