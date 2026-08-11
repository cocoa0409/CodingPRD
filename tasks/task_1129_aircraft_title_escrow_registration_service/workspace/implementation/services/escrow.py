"""Escrow file business logic: posture, totals, state transitions, cascades."""

from datetime import date, timedelta

import db
from db import (
    escrow_file_store, lien_store, lien_release_store, deposit_store,
    disbursement_store, filing_store, title_search_store, trust_agreement_store,
    closing_document_store, aircraft_store, touch, get_logical_now,
)
from services.calculations import compute_lien_priority_ranks


# ---------------------------------------------------------------------------
# Posture
# ---------------------------------------------------------------------------

def recompute_posture(escrow_file: dict):
    """Recompute posture from liens + trust agreements per PRD §2.9."""
    file_id = escrow_file["id"]
    aircraft_id = escrow_file["aircraft_id"]

    # Lien check: any lien in DISCOVERED, DISPUTED, or RELEASE_PENDING blocks
    lien_blocked = any(
        ln["escrow_file_id"] == file_id and ln["status"] in ("DISCOVERED", "DISPUTED", "RELEASE_PENDING")
        for ln in lien_store.values()
    )

    # Trust check: if requires_trust, need ACCEPTED trust covering today's logical date
    trust_blocked = False
    if escrow_file.get("requires_trust"):
        today = get_logical_now().date()
        covered = any(
            ta["aircraft_id"] == aircraft_id
            and ta["status"] == "ACCEPTED"
            and date.fromisoformat(ta["effective_date"]) <= today <= date.fromisoformat(ta["expiry_date"])
            for ta in trust_agreement_store.values()
        )
        trust_blocked = not covered

    if lien_blocked and trust_blocked:
        escrow_file["posture"] = "LIEN_AND_TRUST_BLOCKED"
    elif lien_blocked:
        escrow_file["posture"] = "LIEN_BLOCKED"
    elif trust_blocked:
        escrow_file["posture"] = "TRUST_BLOCKED"
    else:
        escrow_file["posture"] = "READY"


# ---------------------------------------------------------------------------
# Live totals
# ---------------------------------------------------------------------------

def recompute_totals(escrow_file: dict):
    """Recompute total_funded_cents, escrow_balance_cents, seller_net_proceeds_cents."""
    file_id = escrow_file["id"]

    total_funded = sum(
        d["amount_cents"]
        for d in deposit_store.values()
        if d["escrow_file_id"] == file_id and d["status"] == "RECEIVED"
    )
    released_disb = [
        d for d in disbursement_store.values()
        if d["escrow_file_id"] == file_id and d["status"] == "RELEASED"
    ]
    total_released = sum(d["amount_cents"] for d in released_disb)

    escrow_file["total_funded_cents"] = total_funded
    escrow_file["escrow_balance_cents"] = total_funded - total_released

    lien_payoff_sum = sum(d["amount_cents"] for d in released_disb if d["purpose"] == "LIEN_PAYOFF")
    tax_sum = sum(d["amount_cents"] for d in released_disb if d["purpose"] == "TAX_REMITTANCE")
    escrow_file["seller_net_proceeds_cents"] = (
        escrow_file["purchase_price_cents"]
        + escrow_file["proration_amount_cents"]
        - escrow_file["escrow_fee_cents"]
        - lien_payoff_sum
        - tax_sum
    )


# ---------------------------------------------------------------------------
# Bubble-up transitions
# ---------------------------------------------------------------------------

def try_bubble_cleared(escrow_file: dict):
    """If file is SEARCH_COMPLETE and posture is READY, bubble to CLEARED, then check FUNDED."""
    if escrow_file["status"] == "SEARCH_COMPLETE" and escrow_file["posture"] == "READY":
        escrow_file["status"] = "CLEARED"
        touch(escrow_file)
        try_bubble_funded(escrow_file)


def try_bubble_funded(escrow_file: dict):
    """If file is CLEARED and total_funded >= buyer_amount_due, bubble to FUNDED."""
    if (
        escrow_file["status"] == "CLEARED"
        and escrow_file["total_funded_cents"] >= escrow_file["buyer_amount_due_cents"]
    ):
        escrow_file["status"] = "FUNDED"
        touch(escrow_file)


def try_revert_funded(escrow_file: dict):
    """If file is FUNDED and total_funded < buyer_amount_due, revert to CLEARED."""
    if (
        escrow_file["status"] == "FUNDED"
        and escrow_file["total_funded_cents"] < escrow_file["buyer_amount_due_cents"]
    ):
        escrow_file["status"] = "CLEARED"
        touch(escrow_file)


def try_bubble_recorded(escrow_file: dict):
    """CLOSED -> RECORDED when both BILL_OF_SALE and REGISTRATION_APPLICATION are ACCEPTED."""
    if escrow_file["status"] != "CLOSED":
        return
    file_id = escrow_file["id"]
    bos = any(
        f["escrow_file_id"] == file_id and f["filing_type"] == "BILL_OF_SALE" and f["status"] == "ACCEPTED"
        for f in filing_store.values()
    )
    reg = any(
        f["escrow_file_id"] == file_id and f["filing_type"] == "REGISTRATION_APPLICATION" and f["status"] == "ACCEPTED"
        for f in filing_store.values()
    )
    if bos and reg:
        escrow_file["status"] = "RECORDED"
        touch(escrow_file)
        try_bubble_verified(escrow_file)


def try_bubble_verified(escrow_file: dict):
    """RECORDED -> VERIFIED when no filing is SUBMITTED or REJECTED and every ACCEPTED filing is MATCHED."""
    if escrow_file["status"] != "RECORDED":
        return
    file_id = escrow_file["id"]
    filings = [f for f in filing_store.values() if f["escrow_file_id"] == file_id]
    has_pending_or_rejected = any(f["status"] in ("SUBMITTED", "REJECTED") for f in filings)
    if has_pending_or_rejected:
        return
    accepted = [f for f in filings if f["status"] == "ACCEPTED"]
    all_matched = all(f["verification_status"] == "MATCHED" for f in accepted)
    if all_matched:
        escrow_file["status"] = "VERIFIED"
        touch(escrow_file)


# ---------------------------------------------------------------------------
# Cancel cascade
# ---------------------------------------------------------------------------

def cancel_cascade(escrow_file: dict):
    """Cascade per PRD §2.9 and scaffold EscrowFile CANCELLED transition."""
    file_id = escrow_file["id"]

    # All RECEIVED Deposits -> RETURNED
    for d in deposit_store.values():
        if d["escrow_file_id"] == file_id and d["status"] == "RECEIVED":
            d["status"] = "RETURNED"
            d["returned_at"] = db.now_iso()
            touch(d)

    # All PENDING_APPROVAL or APPROVED DisbursementInstructions -> VOIDED
    for d in disbursement_store.values():
        if d["escrow_file_id"] == file_id and d["status"] in ("PENDING_APPROVAL", "APPROVED"):
            d["status"] = "VOIDED"
            touch(d)

    # All QUEUED or REJECTED Filings -> WITHDRAWN
    for f in filing_store.values():
        if f["escrow_file_id"] == file_id and f["status"] in ("QUEUED", "REJECTED"):
            f["status"] = "WITHDRAWN"
            touch(f)

    # All non-terminal LienReleases -> VOIDED
    for r in lien_release_store.values():
        lien = lien_store.get(r["lien_id"])
        if lien and lien["escrow_file_id"] == file_id and r["status"] in (
            "REQUESTED", "QUOTED", "RELEASE_RECEIVED", "FILED"
        ):
            r["status"] = "VOIDED"
            touch(r)

    # Each RELEASE_PENDING lien with no active release -> DISCOVERED
    for ln in lien_store.values():
        if ln["escrow_file_id"] == file_id and ln["status"] == "RELEASE_PENDING":
            has_active = any(
                r["lien_id"] == ln["id"] and r["status"] in ("REQUESTED", "QUOTED", "RELEASE_RECEIVED", "FILED")
                for r in lien_release_store.values()
            )
            if not has_active:
                ln["status"] = "DISCOVERED"
                touch(ln)

    # Recompute totals
    recompute_totals(escrow_file)
    touch(escrow_file)


# ---------------------------------------------------------------------------
# Lien helpers
# ---------------------------------------------------------------------------

def recompute_lien_priorities(aircraft_id: str):
    """Recompute priority_rank for all liens of an aircraft."""
    liens = [ln for ln in lien_store.values() if ln["aircraft_id"] == aircraft_id]
    ranks = compute_lien_priority_ranks(liens)
    rank_map = dict(ranks)
    for ln in liens:
        ln["priority_rank"] = rank_map[ln["id"]]


def lien_return_to_discovered_if_orphaned(lien_id: str):
    """If a RELEASE_PENDING lien has no active release, return to DISCOVERED."""
    ln = lien_store.get(lien_id)
    if not ln or ln["status"] != "RELEASE_PENDING":
        return
    has_active = any(
        r["lien_id"] == lien_id and r["status"] in ("REQUESTED", "QUOTED", "RELEASE_RECEIVED", "FILED")
        for r in lien_release_store.values()
    )
    if not has_active:
        ln["status"] = "DISCOVERED"
        touch(ln)
        ef = escrow_file_store.get(ln["escrow_file_id"])
        if ef:
            recompute_posture(ef)
            touch(ef)
