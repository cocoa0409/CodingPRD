"""In-memory data store and the BAH ZIP lookup table.

The store holds all entity tables keyed by id. Concurrency is serialized by a
single coarse lock; tests do not race at high volume, and a single lock is the
simplest way to guarantee first-writer-wins semantics on state transitions.
"""
from __future__ import annotations

import threading
from typing import Any

from .clock import Clock


# A modest static BAH lookup table. Tests typically register their own ZIPs and
# rely on a default. We expose a lookup that falls back to a NATIONAL_AVG so an
# unknown ZIP still produces a deterministic figure.
DEFAULT_BAH = 1800.00
BAH_TABLE: dict[str, float] = {
    "00000": 1500.00,
    "10001": 4280.00,   # NYC
    "20001": 2700.00,   # DC
    "90001": 3600.00,   # LA
    "94101": 4500.00,   # SF
    "75201": 2100.00,   # Dallas
    "60601": 2400.00,   # Chicago
    "33101": 2900.00,   # Miami
    "98101": 2900.00,   # Seattle
    "30301": 2050.00,   # Atlanta
    "02108": 3450.00,   # Boston
    "85001": 2000.00,   # Phoenix
    "78701": 2150.00,   # Austin
    "55401": 1950.00,   # Minneapolis
    "27601": 1800.00,   # Raleigh
    "12345": 1600.00,
    "12346": 1700.00,
    "12347": 1900.00,
}

NATIONAL_AVG_BAH = 1789.00


class Store:
    """Process-wide in-memory store with a clock."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.clock = Clock()

        # Entity tables: id -> dict
        self.veterans: dict[str, dict] = {}
        self.dependents: dict[str, dict] = {}
        self.claims: dict[str, dict] = {}
        self.schools: dict[str, dict] = {}
        self.enrollments: dict[str, dict] = {}
        self.housing_payments: dict[str, dict] = {}
        self.yellow_ribbon_contributions: dict[str, dict] = {}
        self.voc_rehab_plans: dict[str, dict] = {}
        self.ledger_entries: dict[str, dict] = {}

        # Secondary indexes used for uniqueness checks
        self._school_facility_codes: set[str] = set()
        self._housing_payment_keys: set[tuple[str, str]] = set()

    # -------- BAH lookup --------

    def bah_for_zip(self, zip_code: str) -> float:
        return BAH_TABLE.get(zip_code, DEFAULT_BAH)

    # -------- Uniqueness helpers --------

    def reserve_facility_code(self, code: str) -> None:
        from .errors import ApiError

        if code in self._school_facility_codes:
            raise ApiError("ERR_INVALID_BODY", f"facility_code {code} already in use")
        self._school_facility_codes.add(code)

    def reserve_housing_payment_key(self, enrollment_id: str, month_year: str) -> None:
        from .errors import ApiError

        key = (enrollment_id, month_year)
        if key in self._housing_payment_keys:
            raise ApiError("ERR_PAYMENT_ALREADY_POSTED", "housing payment already posted for this month")
        self._housing_payment_keys.add(key)
