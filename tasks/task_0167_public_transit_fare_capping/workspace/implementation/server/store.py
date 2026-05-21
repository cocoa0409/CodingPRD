"""In-memory data store. Single global lock is used to serialise mutations."""
from __future__ import annotations

import threading
import uuid
from typing import Any


def gen_id() -> str:
    return str(uuid.uuid4())


class Store:
    """Tables keyed by id; lock guards all reads-followed-by-writes."""

    def __init__(self) -> None:
        self.lock = threading.RLock()

        # Primary tables
        self.riders: dict[str, dict[str, Any]] = {}
        self.employers: dict[str, dict[str, Any]] = {}
        self.cards: dict[str, dict[str, Any]] = {}
        self.reduced_fare_certs: dict[str, dict[str, Any]] = {}
        self.low_income_verifications: dict[str, dict[str, Any]] = {}
        self.mobile_tokens: dict[str, dict[str, Any]] = {}
        self.trips: dict[str, dict[str, Any]] = {}
        self.transfer_links: dict[str, dict[str, Any]] = {}
        self.cap_periods: dict[str, dict[str, Any]] = {}
        self.fsa_accounts: dict[str, dict[str, Any]] = {}
        self.fsa_contributions: dict[str, dict[str, Any]] = {}
        self.disputes: dict[str, dict[str, Any]] = {}


store = Store()
