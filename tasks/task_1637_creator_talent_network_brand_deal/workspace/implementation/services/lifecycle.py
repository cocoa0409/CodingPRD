"""Cross-entity cascades and automatic transitions (PRD §2.9). Every resource
a cascade touches gets its own updated_at + version bump."""

import db
from services import helpers as H


def withdraw_open_pitches_of_creator(creator_id):
    """Creator suspension cascade: every pitch of this creator in SUBMITTED /
    SHORTLISTED / COUNTERED -> WITHDRAWN."""
    for p in db.pitches.values():
        if p["creator_id"] == creator_id and p["status"] in (
                "SUBMITTED", "SHORTLISTED", "COUNTERED"):
            p["status"] = "WITHDRAWN"
            H.touch(p)


def withdraw_open_pitches_of_brief(brief_id):
    """Brief expire/close cascade."""
    for p in db.pitches.values():
        if p["brief_id"] == brief_id and p["status"] in (
                "SUBMITTED", "SHORTLISTED", "COUNTERED"):
            p["status"] = "WITHDRAWN"
            H.touch(p)


def maybe_complete_deal(deal):
    """Bubble-up: every deliverable VERIFIED (and at least one exists) while
    deal is ACTIVE -> COMPLETED."""
    if deal["status"] != "ACTIVE":
        return
    dels = [d for d in db.deliverables.values() if d["deal_id"] == deal["id"]]
    if not dels:
        return
    if all(d["status"] == "VERIFIED" for d in dels):
        deal["status"] = "COMPLETED"
        H.touch(deal)


def void_checks_of_deliverable(deliverable):
    """Disclosure checks in QUEUED/FAILED -> VOIDED; recompute the creator's
    pending count once afterwards."""
    touched = False
    for chk in db.disclosure_checks.values():
        if chk["deliverable_id"] == deliverable["id"] and chk["status"] in (
                "QUEUED", "FAILED"):
            chk["status"] = "VOIDED"
            H.touch(chk)
            touched = True
    if touched:
        deal = db.deals.get(deliverable["deal_id"])
        if deal is not None:
            H.recompute_pending_disclosure_count(deal["creator_id"])


def terminate_deal_cascade(deal):
    """Deal termination cascade (PRD §3.4), pinned order:
    1. deliverables not VERIFIED/CANCELLED -> CANCELLED
    2. each cancelled deliverable voids its QUEUED/FAILED disclosure checks
    3. each voiding recomputes creator.pending_disclosure_count
    4. invoices DRAFT/ISSUED/OVERDUE -> VOID (void_reason DEAL_TERMINATED),
       brand.outstanding_balance_cents -= total_cents for each; PAID untouched
    5. payouts ACCRUED/PAYABLE/HELD -> CLAWED_BACK
    6. brief.slots_committed recomputed
    """
    creator_id = deal["creator_id"]

    # 1-3: deliverables + disclosure checks + pending count
    for d in db.deliverables.values():
        if d["deal_id"] != deal["id"]:
            continue
        if d["status"] in ("VERIFIED", "CANCELLED"):
            continue
        d["status"] = "CANCELLED"
        H.touch(d)
        for chk in db.disclosure_checks.values():
            if chk["deliverable_id"] == d["id"] and chk["status"] in (
                    "QUEUED", "FAILED"):
                chk["status"] = "VOIDED"
                H.touch(chk)
                H.recompute_pending_disclosure_count(creator_id)

    # 4: invoices
    for inv in db.invoices.values():
        if inv["deal_id"] != deal["id"]:
            continue
        if inv["status"] in ("DRAFT", "ISSUED", "OVERDUE"):
            was_outstanding = inv["status"] in ("ISSUED", "OVERDUE")
            inv["status"] = "VOID"
            inv["void_reason"] = "DEAL_TERMINATED"
            H.touch(inv)
            if was_outstanding:
                brand = db.brands.get(inv["brand_id"])
                if brand is not None:
                    brand["outstanding_balance_cents"] = (
                        int(brand.get("outstanding_balance_cents", 0))
                        - int(inv["total_cents"]))
                    H.touch(brand)

    # 5: payouts
    for po in db.payouts.values():
        if po["deal_id"] == deal["id"] and po["status"] in (
                "ACCRUED", "PAYABLE", "HELD"):
            po["status"] = "CLAWED_BACK"
            H.touch(po)

    # 6: brief slots
    H.recompute_slots_committed(deal["brief_id"])


def hold_payouts_of_deal(deal_id):
    """Dispute-raised cascade: payouts ACCRUED/PAYABLE -> HELD."""
    for po in db.payouts.values():
        if po["deal_id"] == deal_id and po["status"] in ("ACCRUED", "PAYABLE"):
            po["status"] = "HELD"
            H.touch(po)


def unhold_payouts_of_deal(deal_id):
    """Dispute-resolution cascade: HELD payouts -> PAYABLE when payout_due_at
    set, else ACCRUED."""
    for po in db.payouts.values():
        if po["deal_id"] == deal_id and po["status"] == "HELD":
            po["status"] = "PAYABLE" if po.get("payout_due_at") else "ACCRUED"
            H.touch(po)


def suspend_creator(creator):
    """Shared manual/auto suspension: ACTIVE -> SUSPENDED + pitch withdrawal
    cascade."""
    creator["status"] = "SUSPENDED"
    H.touch(creator)
    withdraw_open_pitches_of_creator(creator["id"])
