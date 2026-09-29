"""Multi-hop cascades.  Every row a hop touches gets updated_at refreshed and
version incremented, exactly as a direct mutation would."""

import db
from services import derive, enums
from services.lookup import (
    filings_of_move,
    handoffs_of_order,
    moves_of_resident,
    orders_of_move,
    placements_of_move,
)


# ------------------------------------------------------------------- handoffs
def void_open_handoffs(order):
    for handoff in handoffs_of_order(order["id"]):
        if handoff["handoff_status"] in enums.OPEN_HANDOFF:
            handoff["handoff_status"] = "VOIDED"
            db.touch(handoff)


def void_open_credit(order):
    """Credit dimension hop: an open credit line dies with its order."""
    if order["credit_status"] in enums.OPEN_CREDIT:
        order["credit_status"] = "VOIDED"
        void_open_handoffs(order)
        return True
    return False


# --------------------------------------------------------------------- orders
def suspend_orders(move):
    changed = []
    for order in orders_of_move(move["id"]):
        if order["provision_status"] in enums.SUSPENDABLE_PROVISION:
            order["provision_status"] = "SUSPENDED"
            order["requested_service_date"] = None
            order["scheduled_window_start"] = None
            order["scheduled_window_end"] = None
            void_open_credit(order)
            db.touch(order)
            changed.append(order)
    return changed


def restore_orders(move):
    """Suspension's inverse: SUSPENDED -> DRAFT with scheduling fields still null."""
    changed = []
    for order in orders_of_move(move["id"]):
        if order["provision_status"] == "SUSPENDED":
            order["provision_status"] = "DRAFT"
            order["requested_service_date"] = None
            order["scheduled_window_start"] = None
            order["scheduled_window_end"] = None
            db.touch(order)
            changed.append(order)
    return changed


def cancel_orders(move, cancellation_reason):
    changed = []
    for order in orders_of_move(move["id"]):
        if order["provision_status"] in enums.CANCELLABLE_PROVISION:
            order["provision_status"] = "CANCELLED"
            order["cancellation_reason"] = cancellation_reason
            order["scheduled_window_start"] = None
            order["scheduled_window_end"] = None
            void_open_credit(order)
            db.touch(order)
            changed.append(order)
    return changed


def waive_order(order, waiver_reason):
    order["provision_status"] = "NOT_APPLICABLE"
    order["waiver_reason"] = waiver_reason
    void_open_credit(order)
    db.touch(order)
    return order


def fail_order(order, failure_reason, void_credit=True):
    order["provision_status"] = "PROVISION_FAILED"
    order["failure_reason"] = failure_reason
    order["scheduled_window_start"] = None
    order["scheduled_window_end"] = None
    if void_credit:
        void_open_credit(order)
    db.touch(order)
    return order


# -------------------------------------------------------------------- filings
def cancel_filings(move, cancellation_reason=None):
    changed = []
    for filing in filings_of_move(move["id"]):
        if filing["status"] in enums.FILING_NON_TERMINAL:
            filing["status"] = "CANCELLED"
            if cancellation_reason is not None:
                filing["cancellation_reason"] = cancellation_reason
            filing["mail_forwarding_confirmed_at"] = None
            db.touch(filing)
            changed.append(filing)
    return changed


# ----------------------------------------------------------------- placements
def void_open_placements_of_move(move):
    changed = []
    for placement in placements_of_move(move["id"]):
        if placement["placement_status"] in enums.PLACEMENT_OPEN:
            placement["placement_status"] = "VOIDED"
            db.touch(placement)
            changed.append(placement)
    return changed


def void_open_placements_of_resident(resident):
    """Marketing opt-out reaches every live move of the resident."""
    changed = []
    for move in moves_of_resident(resident["id"]):
        if move["lifecycle_status"] in enums.TERMINAL_LIFECYCLE:
            continue
        changed.extend(void_open_placements_of_move(move))
    return changed


# ------------------------------------------------------- consent revocation
def apply_consent_termination(consent, resident):
    """Shared cascade for a consent record leaving GRANTED (revoked or expired)."""
    scope = consent["scope"]
    if scope == "PARTNER_MARKETING":
        if not resident["marketing_opt_out"]:
            resident["marketing_opt_out"] = True
            resident["opted_out_at"] = db.now_iso()
            db.touch(resident)
        else:
            resident["opted_out_at"] = db.now_iso()
            db.touch(resident)
        void_open_placements_of_resident(resident)
        return

    for move in moves_of_resident(resident["id"]):
        if move["lifecycle_status"] in enums.TERMINAL_LIFECYCLE:
            continue
        if consent["move_id"] is not None and consent["move_id"] != move["id"]:
            continue
        snap = derive.snapshot(move)
        if derive.compute_gate(move) != "BLOCKED":
            derive.recompute(move)
            derive.commit(move, snap)
            continue
        move["consent_gate"] = "BLOCKED"
        move["blocked_reason"] = "CONSENT_REVOKED"
        if move["lifecycle_status"] in ("SCHEDULING", "IN_SERVICE"):
            move["lifecycle_status"] = "ATTENTION_REQUIRED"
        suspend_orders(move)
        derive.recompute(move)
        derive.commit(move, snap)


def apply_consent_restoration(resident, scope):
    """A fresh GRANTED consent reopens the gate and un-suspends service orders."""
    for move in moves_of_resident(resident["id"]):
        if move["lifecycle_status"] in enums.TERMINAL_LIFECYCLE:
            continue
        snap = derive.snapshot(move)
        was_blocked = move["consent_gate"] == "BLOCKED"
        gate = derive.compute_gate(move)
        move["consent_gate"] = gate
        if was_blocked and gate == "OPEN":
            restore_orders(move)
            if move["blocked_reason"] == "CONSENT_REVOKED":
                move["blocked_reason"] = "NONE"
        derive.recompute(move)
        derive.commit(move, snap)


# ----------------------------------------------------- move cancellation/merge
def cancel_move_children(move, order_reason, filing_reason):
    cancel_orders(move, order_reason)
    cancel_filings(move, filing_reason)
    void_open_placements_of_move(move)
