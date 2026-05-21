"""Cascade helpers — atomic touch of updated_at + version, and cross-entity propagations.

Each function here represents a chain of mutations described in the PRD §2.8.
All callers must hold `store.lock`.
"""
from __future__ import annotations

from typing import Any


def touch(rec: dict[str, Any], clock) -> None:
    """Refresh updated_at and bump version by one — for versioned resources."""
    rec["updated_at"] = clock.now_iso()
    rec["version"] = rec.get("version", 0) + 1


def cancel_order(store, clock, order: dict[str, Any]) -> None:
    """Cancel a still-PLACED order — used by restaurant suspension fan-out."""
    order["status"] = "CANCELLED"
    if order["payment_status"] in {"UNPAID", "AUTHORIZED"}:
        order["payment_status"] = "VOIDED"
    touch(order, clock)
