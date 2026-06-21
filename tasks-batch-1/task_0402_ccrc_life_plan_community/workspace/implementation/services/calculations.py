"""Calculation rules (scaffold §1.3 / PRD §3.6-3.7).

Everything is integer cents and basis points. floor() toward zero is realized
with Python integer floor division on non-negative operands (all bps products
here are non-negative), matching "floor on each bps product (round toward zero)".
"""
from __future__ import annotations

import math
from typing import Dict

BPS_DENOM = 10000
FIFTY_FLOOR_BPS = 5000
NINETY_FLOOR_BPS = 9000
ACTUARIAL_HORIZON_MONTHS = 240


def entrance_fee_refund(plan: Dict, gross: int, occupied_months: int, reason: str) -> int:
    """Compute refundable_cents per the plan refund tier + termination variant.

    Evaluation order is PINNED: per_month = floor(G * declining_monthly_bps /
    10000) is computed ONCE, then multiplied by m. This differs from
    floor(G * bps * m / 10000) whenever G*bps is not a multiple of 10000.

    DEATH variant: FIFTY_REFUNDABLE / NINETY_REFUNDABLE pay the full floor with
    no amortization subtraction; DECLINING is identical to VOLUNTARY.
    """
    G = gross
    m = occupied_months
    monthly_bps = plan["declining_monthly_bps"]
    per_month = (G * monthly_bps) // BPS_DENOM  # floor first, then multiply by m
    refund_plan = plan["refund_plan"]

    if refund_plan == "DECLINING":
        nonref = (G * plan["declining_nonrefundable_bps"]) // BPS_DENOM
        refundable = G - nonref - per_month * m
        return max(0, refundable)

    if refund_plan == "FIFTY_REFUNDABLE":
        floor_cents = (G * FIFTY_FLOOR_BPS) // BPS_DENOM
        if reason == "DEATH":
            return floor_cents
        return max(floor_cents, G - per_month * m)

    if refund_plan == "NINETY_REFUNDABLE":
        floor_cents = (G * NINETY_FLOOR_BPS) // BPS_DENOM
        if reason == "DEATH":
            return floor_cents
        return max(floor_cents, G - per_month * m)

    # Unreachable: refund_plan is validated on plan creation.
    return 0


def monthly_invoice_total(plan: Dict, residency: Dict, skilled_days: int):
    """Return (base_service_fee, second_person_fee, care_surcharge, total).

    Order is pinned: ASSISTED surcharge folds into base BEFORE second-person;
    second-person is a flat plan amount, never scaled by care level. For TYPE_B
    the residency's skilled_days_used is read BEFORE this invoice's increment.
    """
    base = plan["monthly_service_fee_cents"]
    if residency["care_level"] == "ASSISTED":
        base += plan["assisted_monthly_surcharge_cents"]

    second = plan["second_person_fee_cents"] if residency["has_second_person"] else 0

    d = skilled_days
    if residency["care_level"] != "SKILLED":
        care_surcharge = 0
    else:
        ctype = plan["contract_type"]
        if ctype == "TYPE_A":
            care_surcharge = 0
        elif ctype == "TYPE_B":
            remaining_free = max(0, plan["typeb_discounted_days"] - residency["skilled_days_used"])
            billable_days = max(0, d - remaining_free)
            care_surcharge = billable_days * plan["skilled_per_diem_cents"]
        else:  # TYPE_C
            care_surcharge = d * plan["skilled_per_diem_cents"]

    total = base + second + care_surcharge
    return base, second, care_surcharge, total


def present_value_factor(monthly_rate: float, remaining: int) -> float:
    if monthly_rate > 0:
        return (1 - (1 + monthly_rate) ** (-remaining)) / monthly_rate
    return remaining


def actuarial_reserve_disclosure(community: Dict, active_residencies_sorted, plan_of):
    """Compute the disclosure figures over ACTIVE residencies (already sorted by
    created_at ASC). plan_of(residency) -> plan dict.

    Returns a dict with future_obligation_cents, refund_liability_cents,
    total_obligation_cents, funded_ratio_bps, is_deficient, reserve_assets_cents.
    """
    monthly_rate = community["actuarial_discount_rate_bps"] / BPS_DENOM / 12
    future_obligation = 0
    refund_liability = 0

    for r in active_residencies_sorted:
        plan = plan_of(r)
        remaining = max(0, ACTUARIAL_HORIZON_MONTHS - r["occupied_months"])
        pv_factor = present_value_factor(monthly_rate, remaining)
        liability = math.floor(plan["monthly_service_fee_cents"] * pv_factor)
        future_obligation += liability
        refund_liability += entrance_fee_refund(
            plan, r["entrance_fee_paid_cents"], r["occupied_months"], "VOLUNTARY"
        )

    total_obligation = future_obligation + refund_liability
    if total_obligation > 0:
        funded_ratio_bps = (community["reserve_assets_cents"] * BPS_DENOM) // total_obligation
    else:
        funded_ratio_bps = BPS_DENOM

    is_deficient = funded_ratio_bps < community["target_funded_ratio_bps"]
    return {
        "future_obligation_cents": future_obligation,
        "refund_liability_cents": refund_liability,
        "total_obligation_cents": total_obligation,
        "funded_ratio_bps": funded_ratio_bps,
        "is_deficient": is_deficient,
        "reserve_assets_cents": community["reserve_assets_cents"],
    }
