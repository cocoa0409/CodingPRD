"""Ledger reconciliation and derived-amount recomputation (PRD §2.6, §2.7).

Every recompute that changes a parent entity refreshes its updated_at and bumps
its version. Reconciliations are immediate (synchronous with the triggering event).
"""
from __future__ import annotations

import db
from services.common import touch

# Invoice statuses that count toward a PO's matched_amount_cents (PRD §2.6).
MATCHED_STATUSES = {"MATCHED", "APPROVED", "SCHEDULED", "PAID"}


def recompute_po_received(po: dict):
    """received_amount_cents = sum over the PO's POSTED goods receipts (PRD §2.6)."""
    total = sum(
        gr["received_amount_cents"]
        for gr in db.goods_receipts.values()
        if gr["po_id"] == po["id"] and gr["status"] == "POSTED"
    )
    if po["received_amount_cents"] != total:
        po["received_amount_cents"] = total
        touch(po)


def recompute_po_matched(po: dict):
    """matched_amount_cents = sum of total_amount_cents over the PO's invoices in
    {MATCHED, APPROVED, SCHEDULED, PAID}; derives PO status (PRD §2.6)."""
    total = sum(
        inv["total_amount_cents"]
        for inv in db.invoices.values()
        if inv["po_id"] == po["id"] and inv["status"] in MATCHED_STATUSES
    )
    new_status = "CLOSED" if total >= po["ordered_amount_cents"] else "OPEN"
    if po["matched_amount_cents"] != total or po["status"] != new_status:
        po["matched_amount_cents"] = total
        po["status"] = new_status
        touch(po)


def recompute_invoice_total(inv: dict):
    """total_amount_cents = sum of the invoice's lines' amount_cents (PRD §2.6)."""
    total = sum(
        ln["amount_cents"]
        for ln in db.invoice_lines.values()
        if ln["invoice_id"] == inv["id"]
    )
    if inv["total_amount_cents"] != total:
        inv["total_amount_cents"] = total
        touch(inv)


def recompute_batch_total(batch: dict):
    """total_disbursed_cents = sum of member payments' net_amount_cents
    (sum-of-rounded, no status filter) (PRD §3.7).

    Sets the derived field only. The caller (add/remove payment) owns the single
    version bump for the operation (PRD §3.6: each add/remove increments version
    by exactly one), so this helper does NOT touch() to avoid double-bumping.
    """
    batch["total_disbursed_cents"] = sum(
        p["net_amount_cents"]
        for p in db.payments.values()
        if p["batch_id"] == batch["id"]
    )
