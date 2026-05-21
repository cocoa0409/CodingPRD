"""Wallet operations and ledger entries."""
from __future__ import annotations

from typing import Optional

from ..errors import APIError
from ..store import get_store
from ..util import new_id
from .common import append_only_create, stamp_update


_VALID_KINDS = {"DEPOSIT", "FEE_CHARGE", "FEE_REFUND", "LOTTERY_FEE", "PERMIT_FEE", "ADJUSTMENT"}
_VALID_REF_KINDS = {
    "TimedEntryReservation",
    "CampgroundReservation",
    "BackcountryPermit",
    "LotteryApplication",
    "None",
}


def write_ledger(
    visitor_id: str,
    kind: str,
    amount_cents: int,
    reference_kind: str,
    reference_id: Optional[str] = None,
) -> dict:
    if kind not in _VALID_KINDS:
        raise APIError("ERR_VALIDATION", f"Invalid ledger kind: {kind}", 422)
    if reference_kind not in _VALID_REF_KINDS:
        raise APIError("ERR_VALIDATION", f"Invalid reference_kind: {reference_kind}", 422)
    store = get_store()
    entry = {
        "id": new_id(),
        "visitor_id": visitor_id,
        "kind": kind,
        "amount_cents": amount_cents,
        "reference_kind": reference_kind,
        "reference_id": reference_id,
    }
    append_only_create(entry)
    store.ledger_entries[entry["id"]] = entry
    visitor = store.visitors[visitor_id]
    visitor["wallet_balance_cents"] = visitor.get("wallet_balance_cents", 0) + amount_cents
    if visitor["wallet_balance_cents"] < 0:
        # Shouldn't be reachable because callers guard with insufficient_funds first
        raise APIError("ERR_INSUFFICIENT_FUNDS", "Wallet would go negative", 402)
    stamp_update(visitor)
    return entry


def debit_for_fee(
    visitor_id: str,
    amount_cents: int,
    kind: str,
    reference_kind: str,
    reference_id: str,
) -> dict:
    if amount_cents < 0:
        raise APIError("ERR_VALIDATION", "Fee must be non-negative", 422)
    store = get_store()
    visitor = store.visitors[visitor_id]
    if visitor.get("wallet_balance_cents", 0) < amount_cents:
        raise APIError("ERR_INSUFFICIENT_FUNDS", "Insufficient wallet balance", 402)
    return write_ledger(visitor_id, kind, -amount_cents, reference_kind, reference_id)


def refund(
    visitor_id: str,
    amount_cents: int,
    reference_kind: str,
    reference_id: str,
) -> Optional[dict]:
    if amount_cents <= 0:
        return None
    return write_ledger(visitor_id, "FEE_REFUND", amount_cents, reference_kind, reference_id)
