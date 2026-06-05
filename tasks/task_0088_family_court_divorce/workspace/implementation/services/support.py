"""Support-order computation orchestration (resolves incomes per variant,
selects payor/payee, invokes the guideline math). Shared by the support-order
create endpoint and the mediation FULL_AGREEMENT cascade (FINAL CHILD recompute).
"""
from __future__ import annotations

from typing import Dict, Any, Optional

import db
from services.calculations import child_support, spousal_support
from services.common import (
    petitioner_of,
    respondent_of,
    verified_disclosure_for_party,
)


def _schedule_for_case(case: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    for g in db.guideline_schedules.values():
        if g["state_code"] == case["state_code"]:
            return g
    return None


def _child_count(case_id: str) -> int:
    return sum(1 for c in db.children.values() if c["case_id"] == case_id)


def _plan_for_case(case_id: str) -> Optional[Dict[str, Any]]:
    for p in db.parenting_plans.values():
        if p["case_id"] == case_id:
            return p
    return None


def _party_time_pct(party: Dict[str, Any], plan: Optional[Dict[str, Any]]) -> float:
    """Parenting-time fraction for a given party using the plan's petitioner_time_pct.

    petitioner -> petitioner_time_pct; respondent -> 1 - petitioner_time_pct.
    With no plan, treat the fraction as 0 (no shared-custody offset applies).
    """
    if plan is None:
        return 0.0
    pet_pct = float(plan["petitioner_time_pct"])
    return pet_pct if party["role"] == "PETITIONER" else (1.0 - pet_pct)


def _income_for(party: Dict[str, Any], variant: str) -> int:
    """Resolve a party's income input by variant.

    TEMPORARY -> declared Party.gross_monthly_income_cents.
    FINAL     -> VERIFIED FinancialDisclosure.net_monthly_income_cents.
    """
    if variant == "TEMPORARY":
        return int(party["gross_monthly_income_cents"])
    disc = verified_disclosure_for_party(party["id"])
    if disc is None or disc.get("net_monthly_income_cents") is None:
        return 0
    return int(disc["net_monthly_income_cents"])


def compute_support(order: Dict[str, Any], case: Dict[str, Any]) -> tuple:
    """Compute (monthly_amount_cents, support_term_months) for a support order.

    Reads payor/payee parties from the order, incomes per variant, and the
    case's guideline schedule + children + parenting plan.
    """
    schedule = _schedule_for_case(case)
    payor = db.parties[order["payor_party_id"]]
    payee = db.parties[order["payee_party_id"]]
    variant = order["variant"]

    payor_income = _income_for(payor, variant)
    payee_income = _income_for(payee, variant)

    if order["support_type"] == "CHILD":
        plan = _plan_for_case(case["id"])
        payor_time_pct = _party_time_pct(payor, plan)
        amount = child_support(
            schedule=schedule,
            child_count=_child_count(case["id"]),
            payor_income=payor_income,
            payee_income=payee_income,
            payor_time_pct=payor_time_pct,
        )
        return amount, 0
    else:  # SPOUSAL
        amount, term = spousal_support(
            schedule=schedule,
            payor_income=payor_income,
            payee_income=payee_income,
            marriage_months=int(case["marriage_months"]),
        )
        return amount, term


def recompute_final_child_orders(case: Dict[str, Any]) -> None:
    """Recompute monthly_amount_cents for every FINAL-variant CHILD support
    order on the case (cascade link 3 after ParentingPlan ADOPTED, PRD §3.5).
    Each recomputed order is version-bumped.
    """
    for so in db.support_orders.values():
        if (
            so["case_id"] == case["id"]
            and so["support_type"] == "CHILD"
            and so["variant"] == "FINAL"
            and so["status"] != "VACATED"
        ):
            amount, term = compute_support(so, case)
            if so["monthly_amount_cents"] != amount or so["support_term_months"] != term:
                so["monthly_amount_cents"] = amount
                so["support_term_months"] = term
                db.bump(so)
