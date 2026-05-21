"""In-memory data store keyed by entity type and ID."""
from __future__ import annotations

import secrets
import string
import uuid
from threading import RLock
from typing import Any


def new_id() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    alphabet = string.ascii_letters + string.digits
    suffix = "".join(secrets.choice(alphabet) for _ in range(20))
    return f"req_{suffix}"


class Store:
    """A thread-safe in-memory store."""

    def __init__(self) -> None:
        self.lock = RLock()
        self.parks: dict[str, dict[str, Any]] = {}
        self.lots: dict[str, dict[str, Any]] = {}
        self.homes: dict[str, dict[str, Any]] = {}
        self.residents: dict[str, dict[str, Any]] = {}
        self.leases: dict[str, dict[str, Any]] = {}
        self.rent_notices: dict[str, dict[str, Any]] = {}
        self.eviction_cases: dict[str, dict[str, Any]] = {}
        self.utility_bills: dict[str, dict[str, Any]] = {}
        self.home_sale_transfers: dict[str, dict[str, Any]] = {}
        self.conversion_requests: dict[str, dict[str, Any]] = {}


store = Store()


__all__ = ["store", "Store", "new_id", "new_request_id"]
