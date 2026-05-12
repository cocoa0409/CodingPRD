"""Refund execution: drives Order state, escrow ledger, settlement adjustments."""

from db import DB
from services.audit import append_audit, append_escrow
from services.calculations import commission_reversal
from services.common import bump_version


def execute_refund_internal(refund, actor_role: str, actor_id: str):
    """Execute an APPROVED refund, mutating the order and writing escrow entries.

    Caller is expected to have confirmed status==APPROVED.
    """
    order = DB.orders.get(refund["order_id"])
    if order is None:
        return refund

    approved = int(refund.get("approved_amount_cents") or 0)
    order_total = int(order.get("order_total_cents", 0))
    project_id = order["project_id"]

    # Pin previous payment status before transition
    prev_payment_status = order["payment_status"]

    # Synthesized voids (amount 0) must not change the already-VOIDED order's status
    # nor write money-moving ledger entries — only the audit trail is required and is
    # appended by the caller.
    if approved == 0:
        refund["status"] = "EXECUTED"
        bump_version(refund)
        # Audit FUND_FLOW for the (zero) movement
        append_audit(
            subject_type="REFUND_REQUEST",
            subject_id=refund["id"],
            event_type="FUND_FLOW",
            payload={"amount_cents": 0, "order_id": order["id"]},
            actor_role=actor_role,
            actor_id=actor_id,
        )
        return refund

    # For money-moving refunds, the order must be CHARGED or PARTIALLY_REFUNDED
    if prev_payment_status not in ("CHARGED", "PARTIALLY_REFUNDED"):
        # Defensive — execute should not have been allowed to reach here, but
        # we still mark the refund EXECUTED to remain idempotent in cascade flows.
        refund["status"] = "EXECUTED"
        bump_version(refund)
        return refund

    remainder = int(order.get("refundable_remainder_cents", 0))

    # Pinned per-order commission (set at CHARGE time)
    pin = DB.order_charge_pins.get(order["id"], {})
    original_commission = int(pin.get("commission_cents", 0))
    reversal = commission_reversal(original_commission, approved, order_total) if order_total > 0 else 0

    # Ledger entries
    append_escrow(project_id, order["id"], "REFUND_OUT", amount_cents=-approved)
    append_escrow(project_id, order["id"], "COMMISSION_REVERSAL", amount_cents=-reversal)

    # Determine post-refund order state
    if approved == remainder and remainder == order_total:
        # Full refund of an unshipped order
        order["payment_status"] = "REFUNDED"
        order["refundable_remainder_cents"] = 0
    else:
        order["payment_status"] = "PARTIALLY_REFUNDED"
        order["refundable_remainder_cents"] = max(0, remainder - approved)

    bump_version(order)

    append_audit(
        subject_type="ORDER",
        subject_id=order["id"],
        event_type="STATUS_CHANGE",
        payload={"from": prev_payment_status, "to": order["payment_status"]},
        actor_role=actor_role,
        actor_id=actor_id,
    )

    # Recompute final raised cents (REFUNDED orders drop out)
    project = DB.projects.get(project_id)
    if project is not None:
        from services.projects import recompute_final
        recompute_final(project)

    refund["status"] = "EXECUTED"
    bump_version(refund)

    append_audit(
        subject_type="REFUND_REQUEST",
        subject_id=refund["id"],
        event_type="FUND_FLOW",
        payload={"amount_cents": approved, "reversal_cents": reversal, "order_id": order["id"]},
        actor_role=actor_role,
        actor_id=actor_id,
    )
    append_audit(
        subject_type="REFUND_REQUEST",
        subject_id=refund["id"],
        event_type="REFUND_EXECUTED",
        payload={"amount_cents": approved, "reversal_cents": reversal, "order_id": order["id"]},
        actor_role=actor_role,
        actor_id=actor_id,
    )

    # Recompute open settlement batch refund_reversal_cents
    _recompute_open_batches_refund_reversal(project_id)

    return refund


def _recompute_open_batches_refund_reversal(project_id):
    """For DRAFT batches whose period covers refunds in the project, recompute
    refund_reversal_cents by aggregating COMMISSION_REVERSAL ledger entries
    keyed to that period."""
    for b in DB.settlement_batches.values():
        if b["project_id"] != project_id:
            continue
        if b["status"] != "DRAFT":
            continue
        b["refund_reversal_cents"] = _aggregate_refund_reversal(project_id, b["period_start"], b["period_end"])
        bump_version(b)


def _aggregate_refund_reversal(project_id, period_start, period_end):
    total = 0
    for entry in DB.escrow_ledger:
        if entry["project_id"] != project_id:
            continue
        if entry["entry_type"] != "COMMISSION_REVERSAL":
            continue
        ts = entry["created_at"]
        if period_start <= ts < period_end:
            # amount stored is negative; magnitude is the reversed commission
            total += abs(int(entry["amount_cents"]))
    return total
