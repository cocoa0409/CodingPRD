"""Append-only points ledger (PRD §2.7).

Each function:
  - appends one PointsTransaction
  - returns the appended transaction (with balance_after)
The caller is responsible for adjusting Household.points_balance / lifetime
counters consistent with the entry; this helper writes balance_after based
on the household's CURRENT balance, so callers must update the balance
BEFORE invoking this function.
"""

from __future__ import annotations

from db import db, gen_id


def append_transaction(
    household: dict,
    *,
    kind: str,
    amount: int,
    related_entity_kind: str,
    related_entity_id: str,
) -> dict:
    tx = {
        "id": gen_id(),
        "created_at": db.now_iso(),
        "household_id": household["id"],
        "kind": kind,
        "amount": int(amount),
        "balance_after": int(household["points_balance"]),
        "related_entity_kind": related_entity_kind,
        "related_entity_id": related_entity_id,
    }
    db.points_transactions[tx["id"]] = tx
    return tx


def append_audit_log(
    *,
    actor_role: str,
    actor_id: str,
    action: str,
    subject_kind: str,
    subject_id: str,
    before: dict,
    after: dict,
    reason: str | None,
) -> dict:
    entry = {
        "id": gen_id(),
        "created_at": db.now_iso(),
        "actor_role": actor_role,
        "actor_id": actor_id,
        "action": action,
        "subject_kind": subject_kind,
        "subject_id": subject_id,
        "before": before,
        "after": after,
        "reason": reason,
    }
    db.audit_logs[entry["id"]] = entry
    return entry
