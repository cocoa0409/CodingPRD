"""Calculation rules (scaffold section 1.3 / PRD section 3)."""

import math
from datetime import timedelta
from decimal import Decimal

from util import dec, money

# --- constants ---
MAX_CORRECTABLE_INCHES = 12
STRUCTURAL_BASE_FEE = Decimal("1500.00")
PIT_RATE_PER_INCH = Decimal("250.00")
OVERHEAD_RATE_PER_INCH = Decimal("150.00")
INCLUDED_FLOORS = 2
PER_FLOOR_FEE = Decimal("750.00")

OVERAGE_SHARE = Decimal("0.50")
CHANGE_ORDER_MARKUP = Decimal("0.10")

BASE_PERMIT_FEE = Decimal("250.00")
PER_FLOOR_PERMIT_FEE = Decimal("50.00")
PLAN_REVIEW_RATE = Decimal("0.015")
ENERGY_RATE = Decimal("0.004")
ACCESSIBILITY_RATE = Decimal("0.007")

HALF_HOUR_RATE = Decimal("60.00")
AFTER_HOURS_MULTIPLIER = Decimal("1.5")
SLA_BREACH_CREDIT = Decimal("100.00")

BASE_RENEWAL_FEE = Decimal("175.00")
LATE_TIER1_MULTIPLIER = Decimal("1.25")
LATE_TIER2_MULTIPLIER = Decimal("1.50")
GRACE_DAYS = 90

PERMIT_VALID_DAYS = 180

CONTRACT_TIERS = {
    "BASIC": {"annual_fee": Decimal("600.00"), "included_visits": 1, "entrapment_sla_minutes": 240},
    "STANDARD": {"annual_fee": Decimal("1200.00"), "included_visits": 2, "entrapment_sla_minutes": 120},
    "PREMIUM": {"annual_fee": Decimal("2400.00"), "included_visits": 4, "entrapment_sla_minutes": 60},
}

PROVISIONAL_BY_TIER = {
    "PREMIUM": Decimal("0.00"),
    "STANDARD": Decimal("150.00"),
    "BASIC": Decimal("300.00"),
}
AD_HOC_PROVISIONAL = Decimal("450.00")
AD_HOC_SLA_MINUTES = 240


def shortfalls(model, survey):
    pit = max(dec(0), dec(model["min_pit_depth_inches"]) - dec(survey["measured_pit_depth_inches"]))
    overhead = max(dec(0), dec(model["min_overhead_clearance_inches"]) - dec(survey["measured_overhead_clearance_inches"]))
    return pit, overhead


def fits_directly(model, survey):
    pit, overhead = shortfalls(model, survey)
    return pit == 0 and overhead == 0


def fits_correctable(model, survey):
    pit, overhead = shortfalls(model, survey)
    return pit <= MAX_CORRECTABLE_INCHES and overhead <= MAX_CORRECTABLE_INCHES


def feasibility_verdict(models, survey):
    """Evaluate against every ACTIVE product model (scaffold: feasibility_verdict)."""
    active = [m for m in models if m["status"] == "ACTIVE"]
    if any(fits_directly(m, survey) for m in active):
        return "FEASIBLE"
    if any(fits_correctable(m, survey) for m in active):
        return "CONDITIONAL"
    return "INFEASIBLE"


def installation_price_quote(model, survey):
    """Returns (requires_structural, structural_estimate, contract_price)."""
    pit, overhead = shortfalls(model, survey)
    if pit > MAX_CORRECTABLE_INCHES or overhead > MAX_CORRECTABLE_INCHES:
        return None  # caller raises ERR_MODEL_DOES_NOT_FIT
    requires_structural = pit > 0 or overhead > 0
    structural_estimate = (
        (STRUCTURAL_BASE_FEE if requires_structural else Decimal("0"))
        + pit * PIT_RATE_PER_INCH
        + overhead * OVERHEAD_RATE_PER_INCH
    )
    floor_fee = max(0, survey["floors_served"] - INCLUDED_FLOORS) * PER_FLOOR_FEE
    contract_price = dec(model["base_price"]) + dec(model["install_labor_price"]) + structural_estimate + floor_fee
    return requires_structural, money(structural_estimate), money(contract_price)


def structural_adjustment(actual_cost, structural_estimate):
    """Homeowner pays half the overage; full credit for underrun."""
    delta = dec(actual_cost) - dec(structural_estimate)
    if delta > 0:
        return money(delta * OVERAGE_SHARE)
    return money(delta)


def change_order_effective_amount(amount, is_first):
    """Chronological markup rule: first APPROVED change order per project has no
    markup; subsequent ones get +10% (round_half_up 2dp)."""
    if is_first:
        return money(amount)
    return money(dec(amount) * (Decimal("1") + CHANGE_ORDER_MARKUP))


def permit_fee(contract_price, floors_served):
    """Pinned rounding order: round each percentage component, then sum; no
    rounding after summation."""
    plan_review = money(PLAN_REVIEW_RATE * dec(contract_price))
    energy = money(ENERGY_RATE * dec(contract_price))
    accessibility = money(ACCESSIBILITY_RATE * dec(contract_price))
    floor_component = PER_FLOOR_PERMIT_FEE * floors_served
    return BASE_PERMIT_FEE + floor_component + plan_review + energy + accessibility


def current_contract_value(project):
    return dec(project["contract_price"]) + dec(project["approved_change_order_total"])


def grant_provisional_award(program, project):
    value = current_contract_value(project)
    coverage = money(dec(program["coverage_percent"]) * value)
    return min(dec(program["max_award"]), coverage)


def grant_final_award(program, project):
    value = current_contract_value(project)
    coverage = money(dec(program["coverage_percent"]) * value)
    return min(coverage, dec(program["max_award"]), dec(program["remaining_pool"]))


def funding_posture(project, applications):
    """committed = sum(final_award over APPROVED/DISBURSED applications)."""
    committed = sum(
        (dec(a["final_award"]) for a in applications if a["status"] in ("APPROVED", "DISBURSED") and a["final_award"] is not None),
        Decimal("0"),
    )
    if project["contract_price"] is None:
        return "UNFUNDED"
    value = current_contract_value(project)
    if committed >= value and value > 0:
        return "FULLY_FUNDED"
    if committed > 0:
        return "PARTIALLY_FUNDED"
    return "UNFUNDED"


def renewal_fee(days_late):
    """days_late = max(0, floor((clock - expiration_date) in whole days))."""
    if days_late <= 0:
        return money(BASE_RENEWAL_FEE)
    if days_late <= 30:
        return money(BASE_RENEWAL_FEE * LATE_TIER1_MULTIPLIER)
    return money(BASE_RENEWAL_FEE * LATE_TIER2_MULTIPLIER)


def days_late(clock, expiration_date):
    if clock <= expiration_date:
        return 0
    return int((clock - expiration_date).total_seconds() // 86400)


def provisional_estimate(contract):
    if contract is None:
        return AD_HOC_PROVISIONAL
    return PROVISIONAL_BY_TIER[contract["tier"]]


def final_billable(call, contract, parts_cost):
    """entrapment_billing (final): half-hour rounding up, after-hours 1.5x on
    labor, tier discount, SLA breach credit floored at zero."""
    arrived = call["arrived_at"]
    resolved = call["resolved_at"]
    minutes = Decimal(str((resolved - arrived).total_seconds())) / Decimal("60")
    units = Decimal(math.ceil(minutes / Decimal("30")))
    labor = units * HALF_HOUR_RATE
    if arrived.hour >= 18 or arrived.hour < 7:
        labor = money(labor * AFTER_HOURS_MULTIPLIER)
    gross = labor + dec(parts_cost)
    if contract is not None:
        if contract["tier"] == "PREMIUM" and call["call_type"] == "ENTRAPMENT":
            gross = Decimal("0.00")
        elif contract["tier"] == "STANDARD":
            gross = money(gross * Decimal("0.50"))
        # BASIC: no discount
    if call["call_type"] == "ENTRAPMENT" and call.get("sla_breached"):
        gross = max(Decimal("0.00"), gross - SLA_BREACH_CREDIT)
    return money(gross)


def grant_disbursement_waterfall(project, applications):
    """APPROVED applications only, approved_at ASC then created_at ASC. The
    running balance starts at final_invoice; each disburses min(final_award,
    remaining balance). Returns (disbursed_grants, homeowner_balance)."""
    eligible = [a for a in applications if a["status"] == "APPROVED"]
    eligible.sort(key=lambda a: (a["approved_at"], a["created_at"], a["_seq"]))
    balance = dec(project["final_invoice"])
    disbursed_total = Decimal("0")
    for app in eligible:
        pay = min(dec(app["final_award"]), balance)
        app["disbursed"] = money(pay)
        app["status"] = "DISBURSED"
        balance -= pay
        disbursed_total += pay
    return money(disbursed_total), money(balance), eligible


def windows_overlap(start1, end1, start2, end2):
    """Pure half-open overlap: adjacency (end == start) is allowed."""
    return start1 < end2 and start2 < end1


def inspector_buffer_conflict(new_start, new_end, existing_start, existing_end):
    """45-minute buffered conflict: a new window may not begin within 45 minutes
    of another SCHEDULED inspection; adjacency without a full 45-minute gap is
    rejected."""
    buffer = timedelta(minutes=45)
    return new_start < existing_end + buffer and existing_start < new_end + buffer
