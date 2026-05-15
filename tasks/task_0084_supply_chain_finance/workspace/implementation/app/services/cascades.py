"""Cascade helpers (PRD §2.7 + §3.x).

Cascading state changes update each affected entity's `version` and refresh
its `updated_at` exactly like a direct write would.
"""
from __future__ import annotations

from typing import Optional

from ..store import store


def cascade_revoke_confirmation(confirmation: dict, actor_role: str, actor_id: str) -> None:
    """When a PayableConfirmation CONFIRMED -> REVOKED:
    - subtract amount_cents from core_enterprise.credit_line_reserved_cents
    - cascade Receivable {REGISTERED,PLEDGED,TRANSFERRED} -> WRITTEN_OFF
    - cascade FinancingApplication {DRAFT,UNDER_REVIEW} -> CANCELLED
    Audit entries are appended for each cascade.
    """
    # 1) Release reservation on core enterprise (invariant: never negative)
    ce = store.core_enterprises.get(confirmation["core_enterprise_id"])
    if ce is not None:
        new_reserved = int(ce.get("credit_line_reserved_cents", 0)) - int(confirmation["amount_cents"])
        if new_reserved < 0:
            new_reserved = 0
        ce["credit_line_reserved_cents"] = new_reserved
        store.stamp_update(ce)

    # 2) Cascade Receivable referencing this confirmation
    for receivable in store.receivables.values():
        if receivable.get("confirmation_id") != confirmation["id"]:
            continue
        if receivable.get("status") in ("REGISTERED", "PLEDGED", "TRANSFERRED"):
            receivable["status"] = "WRITTEN_OFF"
            store.stamp_update(receivable)
            store.append_audit(
                actor_role="system",
                actor_id="system",
                entity_type="Receivable",
                entity_id=receivable["id"],
                action="WRITE_OFF",
            )
            # 3) Cascade FinancingApplication referencing this receivable
            for app in store.financing_applications.values():
                if app.get("receivable_id") != receivable["id"]:
                    continue
                if app.get("status") in ("DRAFT", "UNDER_REVIEW", "SUBMITTED", "RETURNED_FOR_REVISION"):
                    app["status"] = "CANCELLED"
                    store.stamp_update(app)
                    store.append_audit(
                        actor_role="system",
                        actor_id="system",
                        entity_type="FinancingApplication",
                        entity_id=app["id"],
                        action="REJECT",
                    )


def cascade_settle_schedule(schedule: dict, actor_role: str, actor_id: str) -> None:
    """When a RepaymentSchedule -> SETTLED.

    - Receivable.status -> SETTLED (cascade)
    - PayableConfirmation.status -> SETTLED (cascade)
    - core_enterprise.credit_line_reserved_cents -= confirmation.amount_cents
    - core_enterprise.credit_line_consumed_cents -= principal_cents
    - Close any open CollectionCase -> CLOSED (if not WRITTEN_OFF)
    """
    application = store.financing_applications.get(schedule["application_id"])
    if application is None:
        return

    receivable = store.receivables.get(application.get("receivable_id"))
    if receivable is None:
        return

    confirmation = store.payable_confirmations.get(receivable.get("confirmation_id"))
    if confirmation is None:
        return

    ce = store.core_enterprises.get(confirmation["core_enterprise_id"])
    principal = int(application.get("approved_amount_cents") or 0)
    conf_amount = int(confirmation.get("amount_cents") or 0)

    # Receivable -> SETTLED
    if receivable.get("status") not in ("SETTLED", "WRITTEN_OFF"):
        receivable["status"] = "SETTLED"
        store.stamp_update(receivable)

    # PayableConfirmation -> SETTLED
    if confirmation.get("status") not in ("SETTLED", "REVOKED"):
        confirmation["status"] = "SETTLED"
        store.stamp_update(confirmation)
        store.append_audit(
            actor_role="system",
            actor_id="system",
            entity_type="PayableConfirmation",
            entity_id=confirmation["id"],
            action="REPAY",
            amount_cents=conf_amount,
        )

    # CoreEnterprise ledger
    if ce is not None:
        ce["credit_line_reserved_cents"] = max(
            0, int(ce.get("credit_line_reserved_cents", 0)) - conf_amount
        )
        ce["credit_line_consumed_cents"] = max(
            0, int(ce.get("credit_line_consumed_cents", 0)) - principal
        )
        store.stamp_update(ce)

    # Close open collection case if still in SOFT/HARD/JOINT_LIABILITY
    for case in store.collection_cases.values():
        if case.get("schedule_id") != schedule["id"]:
            continue
        if case.get("stage") in ("SOFT", "HARD", "JOINT_LIABILITY"):
            case["stage"] = "CLOSED"
            store.stamp_update(case)


def cascade_blacklist_supplier(supplier: dict) -> None:
    """Set Supplier.status to BLACKLISTED and reject every SUBMITTED/UNDER_REVIEW
    financing application for this supplier."""
    if supplier.get("status") == "BLACKLISTED":
        return
    supplier["status"] = "BLACKLISTED"
    store.stamp_update(supplier)
    for app in store.financing_applications.values():
        if app.get("supplier_id") != supplier["id"]:
            continue
        if app.get("status") in ("SUBMITTED", "UNDER_REVIEW"):
            app["status"] = "REJECTED"
            store.stamp_update(app)
            store.append_audit(
                actor_role="system",
                actor_id="system",
                entity_type="FinancingApplication",
                entity_id=app["id"],
                action="REJECT",
            )


def latest_confirmation_for_supplier(supplier_id: str) -> Optional[dict]:
    """Return the most recent PayableConfirmation (by created_at) that names
    `supplier_id` and is currently CONFIRMED or SETTLED — used for upstream
    tier-parent resolution."""
    best = None
    for conf in store.payable_confirmations.values():
        if conf.get("supplier_id") != supplier_id:
            continue
        if conf.get("status") not in ("CONFIRMED", "SETTLED"):
            continue
        if best is None or conf.get("created_at", "") > best.get("created_at", ""):
            best = conf
    return best


def any_confirmation_for_supplier(supplier_id: str) -> Optional[dict]:
    """Return any non-terminal PayableConfirmation for a supplier, regardless
    of status — used during the upload precondition to confirm the parent has
    *some* confirmation (the more specific CONFIRMED/SETTLED check belongs at
    the confirm-step)."""
    best = None
    for conf in store.payable_confirmations.values():
        if conf.get("supplier_id") != supplier_id:
            continue
        if best is None or conf.get("created_at", "") > best.get("created_at", ""):
            best = conf
    return best
