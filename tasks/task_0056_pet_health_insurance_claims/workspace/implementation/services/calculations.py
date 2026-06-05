"""Calculation rules (scaffold §1.3 / PRD §3).

All money is integer cents. round_half_up is applied at the exact step named
in each calculation's narrative, never sum-then-round.
"""
from __future__ import annotations

from decimal import Decimal

import db
from services.common import round_half_up, sorted_by_creation

# --- constants (scaffold §1.3) ----------------------------------------------
MULTI_PET_THRESHOLD = 2
MULTI_PET_DISCOUNT_BPS = 1000
WELLNESS_RIDER_PREMIUM_CENTS = 1500
WELLNESS_ALLOWANCE_CENTS = 30000
OCR_MISMATCH_TOLERANCE_BPS = 500


# ---------------------------------------------------------------------------
# calc account_monthly_premium  (PRD §3.1)
# ---------------------------------------------------------------------------
def recompute_account(account: dict) -> None:
    """Recompute active_policy_count, monthly_premium_cents, multi_pet_discount_applied.

    Discount applies to base premium ONLY; wellness rider premium is added AFTER
    and is never discounted (pinned order: discount+round per policy, then add
    rider, then sum across policies in created_at ASC order).
    """
    active = [
        p
        for p in db.policies.values()
        if p.get("account_id") == account["id"] and p.get("status") == "ACTIVE"
    ]
    active = sorted_by_creation(active)
    multi = len(active) >= MULTI_PET_THRESHOLD
    disc = MULTI_PET_DISCOUNT_BPS if multi else 0

    total = 0
    for po in active:
        discounted_base = round_half_up(
            Decimal(po["base_premium_cents"]) * Decimal(10000 - disc) / Decimal(10000)
        )
        line = discounted_base + (WELLNESS_RIDER_PREMIUM_CENTS if po.get("wellness_rider") else 0)
        total += line

    account["active_policy_count"] = len(active)
    account["monthly_premium_cents"] = total
    account["multi_pet_discount_applied"] = multi


# ---------------------------------------------------------------------------
# calc condition_exclusion  (PRD §3.3)
# ---------------------------------------------------------------------------
def compute_exclusion_status(condition: dict, policy: dict) -> str:
    """PRE_EXISTING if first_diagnosed_date < (effective_date + waiting_period_days),
    else COVERED. Strict '<' — a diagnosis exactly at coverage_start is COVERED.
    Day-granularity comparison.
    """
    eff = db.parse_iso_dt(policy["effective_date"])
    coverage_start = db.add_days(eff, int(policy.get("waiting_period_days", 0)))
    diagnosed = db.parse_iso_dt(condition["first_diagnosed_date"])
    if diagnosed.date() < coverage_start.date():
        return "PRE_EXISTING"
    return "COVERED"


# ---------------------------------------------------------------------------
# calc claim_eligible_amount  (PRD §3.6)
# ---------------------------------------------------------------------------
def recompute_eligible_amount(claim: dict) -> None:
    """Per-line allowance after exclusion, summed. Lines in created_at ASC.

    Excluded line -> allowed_amount_cents = 0; otherwise allowed = billed.
    eligible_amount_cents = sum of non-excluded lines' allowed amounts.
    """
    lines = [l for l in db.claim_lines.values() if l.get("claim_id") == claim["id"]]
    lines = sorted_by_creation(lines)
    eligible = 0
    for ln in lines:
        if ln.get("excluded"):
            ln["allowed_amount_cents"] = 0
        else:
            ln["allowed_amount_cents"] = ln["billed_amount_cents"]
            eligible += ln["allowed_amount_cents"]
    claim["eligible_amount_cents"] = eligible


# ---------------------------------------------------------------------------
# OCR mismatch  (PRD §3.5)
# ---------------------------------------------------------------------------
def ocr_mismatch_bps(ocr_total_cents: int, submitted_amount_cents: int) -> int:
    """abs(ocr - submitted) * 10000 / submitted, integer floor."""
    if submitted_amount_cents == 0:
        return 0
    return (abs(ocr_total_cents - submitted_amount_cents) * 10000) // submitted_amount_cents
