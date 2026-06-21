"""State-machine cascades and cross-entity side effects (scaffold §1.2, PRD §3).

This module concentrates the multi-row writes:
  * Settlement-offer 30-day expiry sweep (PRD §3.5, §2.10).
  * Demand-letter send -> case ACTIVE -> DEMAND_SENT cascade (PRD §3.4).
  * First-offer-on-case -> case DEMAND_SENT -> IN_NEGOTIATION cascade (PRD §3.5).
  * Settlement-offer accept -> case SETTLED cascade with lien waterfall,
    court-event cancellations, and disbursement creation (PRD §3.6, §3.7).
  * Disbursement release -> AGREED liens -> PAID cascade (PRD §3.7).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, Any, List

import db
from db import (
    settlement_offers, cases, medical_liens, court_events, disbursements,
    bump, stamp_common, parse_iso_dt, current_clock_dt, now_iso,
)
from services.calculations import (
    compute_contingency_fee_cents,
    compute_lien_waterfall,
)


# ---- Settlement-offer 30-day expiry sweep -----------------------------------

def expire_pending_offers(case_id_filter: str = None) -> None:
    """Sweep PENDING settlement offers whose created_at is at least 30 days
    behind the current clock. Per PRD §3.5: 'once thirty days have passed
    since the offer's created_at, an offer still in PENDING is moved
    PENDING → EXPIRED'.

    When case_id_filter is None, sweeps all offers system-wide (called from
    /_clock/set_current_utc). When set, sweeps only offers on that case
    (called from GET /cases/{id}).
    """
    now = current_clock_dt()
    threshold = now - timedelta(days=30)
    for off in list(settlement_offers.values()):
        if off["status"] != "PENDING":
            continue
        if case_id_filter is not None and off["case_id"] != case_id_filter:
            continue
        created = parse_iso_dt(off["created_at"])
        # Per PRD §3.5 + scaffold transition precondition:
        # "SystemClock.current_utc >= SettlementOffer.created_at + 30 days"
        # which is equivalent to created <= now - 30d.
        if created + timedelta(days=30) <= now:
            off["status"] = "EXPIRED"
            off["responded_at"] = db.get_current_utc()
            bump(off)


# ---- Demand-letter send -> Case ACTIVE -> DEMAND_SENT -----------------------

def cascade_case_to_demand_sent(case: Dict[str, Any]) -> None:
    """Depth-two side effect of DemandLetter.DRAFT -> SENT (PRD §3.4)."""
    case["status"] = "DEMAND_SENT"
    bump(case)


# ---- First-offer-on-case -> Case DEMAND_SENT -> IN_NEGOTIATION --------------

def cascade_case_to_in_negotiation(case: Dict[str, Any]) -> None:
    """Depth-two side effect of first SettlementOffer creation (PRD §3.5)."""
    case["status"] = "IN_NEGOTIATION"
    bump(case)


# ---- Settlement-offer accept -> SETTLED cascade -----------------------------

def cascade_case_to_settled(case: Dict[str, Any], accepted_offer: Dict[str, Any]) -> Dict[str, Any]:
    """Full PRD §3.6 cascade. Returns the newly created Disbursement row.

    Steps (order pinned by PRD §3.7):
      1. case.status := SETTLED; case.gross_settlement_cents := offer.amount.
      2. fee = contingency_fee(gross, filed_in_court) — single rounded multiply.
      3. distributable = gross - fee.
      4. Open liens on case in {ASSERTED, NEGOTIATING, AGREED}, sorted by
         created_at ASC, get capped by lien_proportional_cap against the
         distributable pool. Each lien.negotiated_amount_cents := cap, and the
         lien auto-transitions to AGREED. (PAID is reached only on release.)
      5. total_lien_payout = sum of caps.
      6. net_to_client = gross - fee - total_lien_payout.
      7. Every SCHEDULED CourtEvent on the case -> CANCELLED.
      8. Create Disbursement(status=PENDING) with the four computed amounts.
      9. case.version += 1 (via bump).
    """
    case_id = case["id"]

    # Step 1
    case["status"] = "SETTLED"
    gross = int(accepted_offer["offer_amount_cents"])
    case["gross_settlement_cents"] = gross

    # Step 2
    fee = compute_contingency_fee_cents(gross, bool(case.get("filed_in_court", False)))

    # Step 3
    distributable = gross - fee

    # Step 4: collect open liens, sorted by created_at ASC, capped by waterfall.
    open_liens = [
        l for l in medical_liens.values()
        if l["case_id"] == case_id and l["status"] in ("ASSERTED", "NEGOTIATING", "AGREED")
    ]
    open_liens.sort(key=lambda l: l["created_at"])

    caps = compute_lien_waterfall(open_liens, distributable)
    cap_map = dict(caps)
    total_lien_payout = 0
    for l in open_liens:
        cap = cap_map[l["id"]]
        # PRD §3.6: each lien's negotiated_amount_cents := lesser of
        # asserted_amount_cents and the proportional cap.
        new_neg = min(int(l["asserted_amount_cents"]), cap)
        l["negotiated_amount_cents"] = new_neg
        # auto-transition to AGREED (ASSERTED|NEGOTIATING|AGREED -> AGREED).
        if l["status"] != "AGREED":
            l["status"] = "AGREED"
        total_lien_payout += new_neg
        bump(l)

    # Step 6
    net_to_client = gross - fee - total_lien_payout

    # Step 7: cancel SCHEDULED court events on this case.
    for ev in list(court_events.values()):
        if ev["case_id"] == case_id and ev["status"] == "SCHEDULED":
            ev["status"] = "CANCELLED"
            bump(ev)

    # Step 8: create Disbursement (PENDING).
    disb: Dict[str, Any] = {
        "case_id": case_id,
        "gross_settlement_cents": gross,
        "contingency_fee_cents": fee,
        "total_lien_payout_cents": total_lien_payout,
        "net_to_client_cents": net_to_client,
        "status": "PENDING",
    }
    stamp_common(disb)
    disbursements[disb["id"]] = disb

    # Step 9: bump the case row itself.
    bump(case)
    return disb


# ---- Disbursement release -> AGREED liens cascade ---------------------------

def cascade_release_disbursement(case: Dict[str, Any], disb: Dict[str, Any]) -> None:
    """PRD §3.7: every AGREED lien on the case auto-transitions to PAID."""
    case_id = case["id"]
    disb["status"] = "RELEASED"
    bump(disb)
    for l in medical_liens.values():
        if l["case_id"] == case_id and l["status"] == "AGREED":
            l["status"] = "PAID"
            bump(l)
    bump(case)
