"""Reserve ledger mutations enforcing the conserved-total invariant (PRD §2.6).

total_incurred_cents = indemnity_reserve + medical_reserve
                     + indemnity_paid + medical_paid

Outstanding figures floored at 0; a payment that moves money between an
outstanding column and its paid column leaves total_incurred unchanged.
"""
from __future__ import annotations

from typing import Dict, Any, Optional

import db
from services import calculations as calc


def reserve_for_claim(claim_id: str) -> Optional[Dict[str, Any]]:
    for r in db.reserves.values():
        if r["claim_id"] == claim_id:
            return r
    return None


def latest_wage_statement(claim_id: str) -> Optional[Dict[str, Any]]:
    """Latest WageStatement for the claim by created_at ASC, last wins."""
    stmts = [w for w in db.wage_statements.values() if w["claim_id"] == claim_id]
    if not stmts:
        return None
    stmts.sort(key=lambda w: (w["created_at"], w["id"]))
    return stmts[-1]


def controlling_weekly_rate(claim_id: str) -> int:
    """ttd_weekly_rate_cents of the latest wage statement, or 0 if none."""
    ws = latest_wage_statement(claim_id)
    return ws["ttd_weekly_rate_cents"] if ws else 0


def recompute_total(reserve: Dict[str, Any]) -> None:
    reserve["total_incurred_cents"] = calc.total_incurred(
        reserve["indemnity_reserve_cents"],
        reserve["medical_reserve_cents"],
        reserve["indemnity_paid_cents"],
        reserve["medical_paid_cents"],
    )


def reproject(reserve: Dict[str, Any], claim_id: str, projected_weeks: int,
              severity_tier: str) -> None:
    """Recompute the two outstanding reserve figures (calc indemnity_reserve_forward).

    Paid columns are preserved; total_incurred is recomputed.
    """
    weekly = controlling_weekly_rate(claim_id)
    reserve["projected_weeks"] = projected_weeks
    reserve["severity_tier"] = severity_tier
    reserve["indemnity_reserve_cents"] = calc.indemnity_reserve_forward(weekly, projected_weeks)
    reserve["medical_reserve_cents"] = calc.medical_reserve_for_tier(severity_tier)
    recompute_total(reserve)


def apply_indemnity_payment(reserve: Dict[str, Any], amount_cents: int) -> None:
    """indemnity_paid += amount; indemnity_reserve -= amount (floored at 0)."""
    reserve["indemnity_paid_cents"] += amount_cents
    reserve["indemnity_reserve_cents"] = max(0, reserve["indemnity_reserve_cents"] - amount_cents)
    recompute_total(reserve)
    db.bump(reserve)


def reverse_indemnity_payment(reserve: Dict[str, Any], amount_cents: int) -> None:
    """Compensating reversal on void: paid -= amount; reserve += amount."""
    reserve["indemnity_paid_cents"] -= amount_cents
    reserve["indemnity_reserve_cents"] += amount_cents
    recompute_total(reserve)
    db.bump(reserve)


def apply_medical_payment(reserve: Dict[str, Any], amount_cents: int) -> None:
    """medical_paid += amount; medical_reserve -= amount (floored at 0)."""
    reserve["medical_paid_cents"] += amount_cents
    reserve["medical_reserve_cents"] = max(0, reserve["medical_reserve_cents"] - amount_cents)
    recompute_total(reserve)
    db.bump(reserve)
