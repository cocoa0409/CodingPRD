"""Deterministic calculations (PRD sections 3.3, 3.5, 3.6, 3.4, 3.8).

Every monetary and ratio computation is done with decimal.Decimal and
ROUND_HALF_UP. Floats never take part in the arithmetic.
"""

from decimal import Decimal, ROUND_HALF_UP

from services.constants import (
    ATTACHMENT_FACTOR,
    BIND_ATTACHMENT_FACTOR,
    BROKERAGE_LOAD,
    CONTINGENCY_TIER,
    CONTROL_CREDIT,
    CUMULATIVE_RISK_BUDGET_UGL,
    ESCALATION_RATE_PER_YEAR,
    HIGH_EXCEEDANCE_ADDER,
    HIGH_EXCEEDANCE_THRESHOLD,
    LIMIT_ROUNDING_STEP_CENTS,
    LIMIT_SHARE_OF_ESTIMATE,
    MEDIA_ATTENUATION_DIVISOR,
    MEDIA_FACTOR,
    MIN_PREMIUM_CENTS,
    OVERSIGHT_CAP_CENTS,
    OVERSIGHT_RATE,
    PRACTICAL_QUANT_FLOOR_UGL,
    RATE_BAND_LOW,
    RATE_BAND_MID,
    RATE_HIGH,
    RATE_LOW,
    RATE_MID,
    SCENARIO_MULTIPLIER,
    UNDERWRITING_CONTINGENCY_FLOOR,
    UNDERWRITING_ESCALATION_YEARS,
)


def D(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rhu(value, places=0):
    quant = Decimal(1).scaleb(-places)
    return D(value).quantize(quant, rounding=ROUND_HALF_UP)


def rhu_cents(value):
    return int(rhu(value, 0))


def as_float(value, places):
    return float(rhu(value, places))


# ------------------------------------------------- risk-based cleanup goal


def derive_goal(screening_level_ugl, basis, control_credit_type, media,
                intended_reuse, distinct_count):
    """Full five-step derivation. Rounding happens exactly once, at the end."""
    scenario = "RESIDENTIAL" if basis == "UNRESTRICTED" else intended_reuse
    scenario_goal = D(screening_level_ugl) * SCENARIO_MULTIPLIER[scenario]
    if basis == "RESTRICTED":
        credited = scenario_goal * CONTROL_CREDIT[control_credit_type]
    else:
        credited = scenario_goal
    attenuated = credited / MEDIA_ATTENUATION_DIVISOR[media]
    divisor = distinct_count if distinct_count > 1 else 1
    cap = CUMULATIVE_RISK_BUDGET_UGL / D(divisor)
    candidate = cap if cap < attenuated else attenuated
    selected = candidate if candidate > PRACTICAL_QUANT_FLOOR_UGL else PRACTICAL_QUANT_FLOOR_UGL
    goal_ugl = float(rhu(selected, 2))
    cap_applied = bool(cap < attenuated and cap > PRACTICAL_QUANT_FLOOR_UGL)
    return goal_ugl, cap_applied


def exceedance_factor(max_concentration_ugl, screening_level_ugl):
    return float(rhu(D(max_concentration_ugl) / D(screening_level_ugl), 2))


# ------------------------------------------------ remediation cost estimate


def line_value_cents(line):
    """One design cost line, rounded half up to whole cents."""
    return rhu_cents(
        D(line["quantity"]) * D(line["unit_cost_cents"]) * MEDIA_FACTOR[line["media"]]
    )


def line_values(cost_lines):
    return [line_value_cents(line) for line in cost_lines]


def cost_estimate(cost_lines, delineation_confidence, max_exceedance_factor,
                  years_to_construction_start, variant):
    """variant is 'DESIGN' or 'UNDERWRITING'."""
    direct = sum(line_values(cost_lines))
    years = (years_to_construction_start if variant == "DESIGN"
             else UNDERWRITING_ESCALATION_YEARS)
    escalation = rhu_cents(D(direct) * ESCALATION_RATE_PER_YEAR * D(years))
    pct = CONTINGENCY_TIER[delineation_confidence]
    if D(max_exceedance_factor) >= HIGH_EXCEEDANCE_THRESHOLD:
        pct = pct + HIGH_EXCEEDANCE_ADDER
    if variant == "UNDERWRITING" and pct < UNDERWRITING_CONTINGENCY_FLOOR:
        pct = UNDERWRITING_CONTINGENCY_FLOOR
    contingency = rhu_cents((D(direct) + D(escalation)) * pct)
    subtotal = direct + escalation + contingency
    oversight = rhu_cents(D(subtotal) * OVERSIGHT_RATE)
    if oversight > OVERSIGHT_CAP_CENTS:
        oversight = OVERSIGHT_CAP_CENTS
    total = direct + escalation + contingency + oversight
    return {
        "direct_cost_cents": direct,
        "escalation_cents": escalation,
        "contingency_pct": float(rhu(pct, 2)),
        "contingency_cents": contingency,
        "oversight_cents": oversight,
        "total_estimate_cents": total,
    }


# ---------------------------------------------------- cost cap underwriting


def _ceil_to_step(value, step):
    if value <= 0:
        return 0
    whole = -(-int(value) // int(step))
    return whole * int(step)


def cost_cap_terms(underwriting_estimate_cents):
    ue = int(underwriting_estimate_cents)
    attachment = rhu_cents(D(ue) * ATTACHMENT_FACTOR)
    buffer_layer = attachment - ue
    raw_limit = rhu_cents(D(ue) * LIMIT_SHARE_OF_ESTIMATE)
    limit = _ceil_to_step(raw_limit, LIMIT_ROUNDING_STEP_CENTS)
    ratio = D(limit) / D(ue) if ue else D(0)
    if ratio <= RATE_BAND_LOW:
        rate = RATE_LOW
    elif ratio <= RATE_BAND_MID:
        rate = RATE_MID
    else:
        rate = RATE_HIGH
    base_premium = rhu_cents(D(limit) * rate)
    premium = rhu_cents(D(base_premium) * BROKERAGE_LOAD)
    if premium < MIN_PREMIUM_CENTS:
        premium = MIN_PREMIUM_CENTS
    return {
        "underwriting_estimate_cents": ue,
        "attachment_point_cents": attachment,
        "buffer_layer_cents": buffer_layer,
        "limit_cents": limit,
        "rate_applied": float(rhu(rate, 3)),
        "premium_cents": premium,
    }


def bind_attachment_floor(total_estimate_cents):
    return rhu_cents(D(total_estimate_cents) * BIND_ATTACHMENT_FACTOR)


# --------------------------------------------------------- funding waterfall


def share_cap_cents(eligible_base_cents, max_share_pct):
    return rhu_cents(D(eligible_base_cents) * D(max_share_pct))


def local_match_cents(allocated_cents, match_requirement_pct):
    return rhu_cents(D(allocated_cents) * D(match_requirement_pct))


# ------------------------------------------------------------------- BFPP


def compliance_ratio(current_weight, satisfied_weight, at_risk_weight,
                     total_weight):
    if total_weight == 0:
        return float(D("1.0"))
    numerator = D(current_weight) + D(satisfied_weight) + D("0.5") * D(at_risk_weight)
    return float(rhu(numerator / D(total_weight), 4))
