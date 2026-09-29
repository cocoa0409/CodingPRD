"""Calculation rules (SCAFFOLD 1.3 / PRD 3.x)."""
from decimal import Decimal

from store import db
from util import q2, add_days, whole_days
from services.constants import (
    MARKUP_TIER_1_CEILING, MARKUP_TIER_2_CEILING,
    CONTINGENCY_TIER_1_CEILING, CONTINGENCY_TIER_2_CEILING,
    GENERAL_CONDITIONS_DAY_RATE,
    MARKUP_RATE_LOW, MARKUP_RATE_MID, MARKUP_RATE_HIGH,
    CONTINGENCY_RATE_NONE, CONTINGENCY_RATE_MID, CONTINGENCY_RATE_HIGH,
    FABRICATION_BUFFER_DAYS,
    WARRANTY_BASE_DAYS, SYSTEMS_TRADE_DAYS, SYSTEMS_TRADES, EXCLUDED_CATEGORIES,
)


def change_order_priced_amount(direct_cost, schedule_impact_days):
    """Five pinned steps; the contingency tier is selected from the PRE-contingency
    subtotal and never from priced_amount (PRD 3.3)."""
    base = direct_cost

    if base < MARKUP_TIER_1_CEILING:
        markup_rate = MARKUP_RATE_LOW
    elif base < MARKUP_TIER_2_CEILING:
        markup_rate = MARKUP_RATE_MID
    else:
        markup_rate = MARKUP_RATE_HIGH
    markup = q2(base * markup_rate)

    gc_fee = q2(Decimal(int(schedule_impact_days)) * GENERAL_CONDITIONS_DAY_RATE)

    subtotal = base + markup + gc_fee

    if subtotal <= CONTINGENCY_TIER_1_CEILING:
        contingency_rate = CONTINGENCY_RATE_NONE
    elif subtotal <= CONTINGENCY_TIER_2_CEILING:
        contingency_rate = CONTINGENCY_RATE_MID
    else:
        contingency_rate = CONTINGENCY_RATE_HIGH
    contingency = q2(subtotal * contingency_rate)

    priced_amount = q2(subtotal + contingency)
    return markup_rate, contingency_rate, priced_amount


def selection_total(vendor_quote_amount, freight_amount, install_amount):
    return q2(vendor_quote_amount + freight_amount + install_amount)


def material_ready_at(locked_at, selection_lead_time_days):
    """calculations.schedule_material_readiness - the trade's own lead time never
    enters this formula (PRD 3.2)."""
    return add_days(locked_at, int(selection_lead_time_days) + FABRICATION_BUFFER_DAYS)


def delay_days_for(task):
    if task["actual_finish"] is None or task["planned_finish"] is None:
        return 0
    return max(0, whole_days(task["actual_finish"] - task["planned_finish"]))


def float_days_for(task, predecessor):
    if predecessor is None or predecessor.get("actual_finish") is None:
        return None
    anchor = add_days(predecessor["actual_finish"], task.get("lag_days") or 0)
    return whole_days(task["planned_start"] - anchor)


def warranty_coverage(ticket, project):
    """calculations.warranty_coverage_determination - exclusion test runs first."""
    if ticket["phase"] == "PUNCH":
        return "NONE", None, "NOT_APPLICABLE"

    if ticket["category"] in EXCLUDED_CATEGORIES:
        return "NONE", None, "EXCLUDED"

    if ticket.get("source_schedule_task_id") is None:
        anchor = "WHOLE_HOUSE"
        coverage_end_at = add_days(project.get("warranty_starts_at"), WARRANTY_BASE_DAYS)
    else:
        anchor = "TRADE"
        task = db.schedule_tasks.get(ticket["source_schedule_task_id"])
        trade_days = WARRANTY_BASE_DAYS
        if task is not None:
            sub = db.subcontractors.get(task.get("subcontractor_id"))
            if sub is not None and sub.get("trade") in SYSTEMS_TRADES:
                trade_days = SYSTEMS_TRADE_DAYS
            coverage_end_at = add_days(task.get("actual_finish"), trade_days)
        else:
            coverage_end_at = None

    if coverage_end_at is None:
        return anchor, None, "OUT_OF_COVERAGE"

    result = "COVERED" if ticket["reported_at"] <= coverage_end_at else "OUT_OF_COVERAGE"
    return anchor, coverage_end_at, result


def draw_funding_amounts(included, retainage_pct):
    """Per-line retainage rounding BEFORE summation (PRD 3.6)."""
    requested_amount = q2(sum((e["amount"] for e in included), Decimal("0")))
    retainage_amount = Decimal("0")
    for entry in included:
        retainage_amount += q2(entry["amount"] * retainage_pct)
    retainage_amount = q2(retainage_amount)
    net_funding_amount = q2(requested_amount - retainage_amount)
    return requested_amount, retainage_amount, net_funding_amount
