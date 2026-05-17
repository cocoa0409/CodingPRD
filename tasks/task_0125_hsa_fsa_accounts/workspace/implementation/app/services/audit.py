"""Audit-event creation + reconciliation invariant check."""
from __future__ import annotations

from flask import g

from ..store import store


def emit_audit_event(
    *,
    event_type: str,
    subject_entity: str,
    subject_id: str,
    account_id: str | None,
    plan_year_id: str | None = None,
    cents_delta: int = 0,
    ops_run_index: int | None = None,
    actor_role: str | None = None,
    actor_user_id: str | None = None,
    note: str | None = None,
) -> dict:
    """Append a single AuditEvent. Caller holds store.lock if mutating."""
    now = store.clock.now()
    row = {
        "id": store.new_id(),
        "_seq": store.next_seq(),
        "account_id": account_id,
        "plan_year_id": plan_year_id,
        "event_type": event_type,
        "subject_entity": subject_entity,
        "subject_id": subject_id,
        "actor_role": actor_role if actor_role is not None else getattr(g, "role", None),
        "actor_user_id": actor_user_id if actor_user_id is not None else getattr(g, "user_id", None),
        "cents_delta": int(cents_delta),
        "ops_run_index": ops_run_index,
        "occurred_at": now,
        # PRD §2.0: append-only entities (AuditEvent included) carry
        # id and created_at; the latter is the logical clock at write.
        "created_at": now,
    }
    if note is not None:
        row["note"] = note
    store.audit_events.append(row)
    return row


def find_claim_submitted_event_actor(claim_id: str) -> str | None:
    """Return the actor_user_id on the most-recent CLAIM_SUBMITTED event for a claim."""
    actor = None
    for ev in store.audit_events:
        if ev["event_type"] == "CLAIM_SUBMITTED" and ev["subject_id"] == claim_id:
            actor = ev["actor_user_id"]  # last wins
    return actor


def reconcile_plan_year(plan_year_id: str) -> bool:
    """Return True if the audit ledger reconciles with the plan year denormalized counters.

    Invariant per PRD §2.8 / SCAFFOLD §1.3 audit_trail_completeness:
        sum(cents_delta) over CONTRIBUTION + CLAIM subject_entity events for this plan year
            == contributions_ytd_cents - claims_paid_ytd_cents
    """
    py = store.plan_years.get(plan_year_id)
    if py is None:
        return True  # nothing to reconcile
    total = 0
    for ev in store.audit_events:
        if ev.get("plan_year_id") != plan_year_id:
            continue
        if ev["subject_entity"] in ("CONTRIBUTION", "CLAIM"):
            total += ev["cents_delta"]
    expected = py["contributions_ytd_cents"] - py["claims_paid_ytd_cents"]
    return total == expected
