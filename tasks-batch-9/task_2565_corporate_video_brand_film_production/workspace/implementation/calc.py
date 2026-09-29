"""Calculation rules (scaffold 1.3 / PRD 2.6, 3.2, 3.3, 3.6, 3.9, 3.10).

All money is whole cents.  ``round_half_up`` rounds a rational to the nearest
integer cent with ties going away from zero.  Every rounding *order* below is a
contract, not an implementation detail.
"""

import math
from decimal import Decimal, ROUND_HALF_UP

# ---- constants -----------------------------------------------------------
MAX_MARKUP_PCT = Decimal("0.35")

BUYOUT_CHANNEL_MULT = {
    1: Decimal("0.50"),
    2: Decimal("0.85"),
    3: Decimal("1.20"),
    4: Decimal("1.60"),
}
AGENT_FEE_PCT = Decimal("0.10")
UNION_PENSION_HEALTH_PCT = Decimal("0.1975")
REUSE_CYCLE_PCT = Decimal("0.35")
REUSE_CYCLE_DAYS = 91

EXTRA_ROUND_LABOR_CENTS = 480000
NEW_DELIVERABLE_LABOR_CENTS = 620000
RUSH_TIER_7_DAY_PCT = Decimal("0.25")
RUSH_TIER_14_DAY_PCT = Decimal("0.15")

STRAIGHT_TIME_HOURS = Decimal("10")
OT1_SPAN_HOURS = Decimal("2")
OT1_MULT = Decimal("1.5")
OT2_MULT = Decimal("2.0")

MIN_CONFIRMED_CREW_FOR_CALL_SHEET = 3
DURATION_TOLERANCE_SECONDS = 1

PREP_WINDOW_HOURS = 48
RETURN_WINDOW_HOURS = 48
CALL_SHEET_LEAD_HOURS = 12

OVERAGE_TOLERANCE_PCT = Decimal("0.05")
RETENTION_MONTH_DAYS = 30


def dec(value):
    return Decimal(str(value))


def round_half_up(value):
    return int(Decimal(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


# ---- budget_line_extended_cents -----------------------------------------
def budget_line_extended_cents(quantity, unit_rate_cents, markup_pct):
    """Round the markup on THIS line, then add it to the exact raw amount.

    Summing raw amounts across lines and applying the markup to the sum is
    forbidden (PRD 2.6): it produces different cents.
    """
    raw = dec(quantity) * dec(unit_rate_cents)
    markup = round_half_up(raw * dec(markup_pct))
    extended = raw + Decimal(markup)
    if extended == extended.to_integral_value():
        return int(extended)
    return round_half_up(extended)


# ---- talent_compensation -------------------------------------------------
def talent_compensation(compensation_model, session_fee_cents, session_days,
                        channel_basis_count, term_basis_months):
    """Every component is rounded on its own, THEN the components are summed."""
    base_fee_cents = int(session_fee_cents) * int(session_days)
    result = {
        "channel_basis_count": int(channel_basis_count),
        "term_basis_months": int(term_basis_months),
        "base_fee_cents": base_fee_cents,
        "reuse_cycles": 0,
        "usage_load_cents": 0,
        "reuse_fee_cents": 0,
        "pension_health_cents": 0,
        "agent_fee_cents": 0,
        "total_comp_cents": 0,
    }
    if compensation_model == "USAGE_BUYOUT":
        channel_mult = BUYOUT_CHANNEL_MULT[min(max(int(channel_basis_count), 1), 4)]
        term_mult = _buyout_term_mult(int(term_basis_months))
        usage_load = round_half_up(dec(base_fee_cents) * channel_mult * term_mult)
        agent_fee = round_half_up(dec(base_fee_cents + usage_load) * AGENT_FEE_PCT)
        result["usage_load_cents"] = usage_load
        result["reuse_cycles"] = 0
        result["reuse_fee_cents"] = 0
        result["pension_health_cents"] = 0
        result["agent_fee_cents"] = agent_fee
        result["total_comp_cents"] = base_fee_cents + usage_load + agent_fee
        return result

    # UNION_SESSION_REUSE
    reuse_cycles = _exact_ceil(int(term_basis_months) * 30, REUSE_CYCLE_DAYS)
    beyond_first = max(0, reuse_cycles - 1)
    reuse_fee = round_half_up(dec(base_fee_cents) * REUSE_CYCLE_PCT * Decimal(beyond_first))
    pension_health = round_half_up(dec(base_fee_cents + reuse_fee) * UNION_PENSION_HEALTH_PCT)
    agent_fee = round_half_up(dec(base_fee_cents + reuse_fee) * AGENT_FEE_PCT)
    result["usage_load_cents"] = 0
    result["reuse_cycles"] = reuse_cycles
    result["reuse_fee_cents"] = reuse_fee
    result["pension_health_cents"] = pension_health
    result["agent_fee_cents"] = agent_fee
    result["total_comp_cents"] = base_fee_cents + reuse_fee + pension_health + agent_fee
    return result


def _buyout_term_mult(term_months):
    if term_months <= 12:
        return Decimal("1.00")
    if term_months <= 24:
        return Decimal("1.35")
    if term_months <= 36:
        return Decimal("1.65")
    return Decimal("2.00")


def _exact_ceil(numerator, denominator):
    return -((-numerator) // denominator)


# ---- change_order_amount -------------------------------------------------
def change_order_amount(trigger_reason, additional_rounds_granted, air_date, clock_now):
    if trigger_reason == "REVISION_ROUND_EXCEEDED":
        labor_cents = EXTRA_ROUND_LABOR_CENTS * int(additional_rounds_granted)
    else:
        labor_cents = NEW_DELIVERABLE_LABOR_CENTS

    delta_seconds = (air_date - clock_now).total_seconds()
    days_to_air = int(math.floor(delta_seconds / 86400.0))
    if days_to_air <= 7:
        rush_pct = RUSH_TIER_7_DAY_PCT
    elif days_to_air <= 14:
        rush_pct = RUSH_TIER_14_DAY_PCT
    else:
        rush_pct = Decimal("0.00")
    rush_cents = round_half_up(dec(labor_cents) * rush_pct)
    subtotal_cents = labor_cents + rush_cents

    # The producer fee tier is keyed on subtotal_cents (pre-fee), never on
    # amount_cents.  Keying it on the total diverges by 14400 cents (PRD 3.9).
    if subtotal_cents >= 1000000:
        producer_fee_pct = Decimal("0.12")
    elif subtotal_cents >= 500000:
        producer_fee_pct = Decimal("0.15")
    else:
        producer_fee_pct = Decimal("0.18")
    producer_fee_cents = round_half_up(dec(subtotal_cents) * producer_fee_pct)
    amount_cents = subtotal_cents + producer_fee_cents
    return {
        "labor_cents": labor_cents,
        "rush_pct": float(rush_pct),
        "rush_cents": rush_cents,
        "subtotal_cents": subtotal_cents,
        "producer_fee_pct": float(producer_fee_pct),
        "producer_fee_cents": producer_fee_cents,
        "amount_cents": amount_cents,
    }


# ---- crew_booking_cost ---------------------------------------------------
def crew_booking_cost(call_time, wrap_time, hourly_rate_cents):
    """Components are summed as exact rationals and the SUM is rounded once."""
    seconds = Decimal(int((wrap_time - call_time).total_seconds()))
    hours = (seconds / Decimal(3600)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    rate = dec(hourly_rate_cents)

    straight = min(hours, STRAIGHT_TIME_HOURS) * rate
    ot1_hours = min(max(hours - STRAIGHT_TIME_HOURS, Decimal(0)), OT1_SPAN_HOURS)
    ot1 = ot1_hours * rate * OT1_MULT
    ot2_hours = max(hours - (STRAIGHT_TIME_HOURS + OT1_SPAN_HOURS), Decimal(0))
    ot2 = ot2_hours * rate * OT2_MULT

    cost = round_half_up(straight + ot1 + ot2)
    return {
        "scheduled_hours": float(hours),
        "straight_time_cents": round_half_up(straight),
        "overtime_tier1_cents": round_half_up(ot1),
        "overtime_tier2_cents": round_half_up(ot2),
        "cost_cents": cost,
    }


# ---- equipment_reservation_cost -----------------------------------------
def equipment_reservation_cost(pickup_at, return_at, unit_count, daily_rate_cents):
    span_hours = Decimal(int((return_at - pickup_at).total_seconds())) / Decimal(3600)
    rental_days = max(1, _ceil_decimal(span_hours / Decimal(24)))
    total = int(unit_count) * int(daily_rate_cents) * rental_days
    return {"rental_days": rental_days, "total_cost_cents": total}


def _ceil_decimal(value):
    integral = int(value)
    if Decimal(integral) < value:
        integral += 1
    return integral


# ---- version_qc_evaluation ----------------------------------------------
def version_qc_evaluation(version, deliverable):
    findings = []
    if version["aspect_ratio"] != deliverable["aspect_ratio"]:
        findings.append("ASPECT_RATIO_MISMATCH")
    if abs(int(version["duration_seconds"]) - int(deliverable["target_duration_seconds"])) \
            > DURATION_TOLERANCE_SECONDS:
        findings.append("DURATION_OUT_OF_TOLERANCE")
    requirement = deliverable["caption_requirement"]
    if requirement != "NONE" and (
            version["has_captions"] is False or version["caption_format"] != requirement):
        findings.append("CAPTION_REQUIREMENT_UNMET")
    if requirement == "NONE" and version["has_captions"] is True:
        findings.append("UNREQUESTED_CAPTION_ASSET")
    return findings


# ---- commitment_budget_allowance ---------------------------------------
def commitment_allowance_cents(project):
    ceiling = int(project["budget_ceiling_cents"])
    if project["status"] in ("DRAFT", "SCOPED"):
        return ceiling
    return round_half_up(dec(ceiling) * (Decimal(1) + OVERAGE_TOLERANCE_PCT))
