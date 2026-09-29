"""Deterministic calculations (PRD section 2.6 / 3.x).

Every monetary and percentage computation uses ``decimal.Decimal`` with
ROUND_HALF_UP.  No float arithmetic anywhere.
"""

from decimal import Decimal, ROUND_HALF_UP

from db import add_days, months_between

ZERO = Decimal("0")
ONE = Decimal("1")

# ---- discount / add-on / fee constants -----------------------------------
NONPROFIT_BONUS_DISCOUNT_PCT = Decimal("0.0300")
MAX_TOTAL_DISCOUNT_PCT = Decimal("0.2000")
AGGREGATE_ADD_ON_CAP_PCT = Decimal("0.1500")
FEE_REBATE_BY_TIER = {
    0: Decimal("0.0000"),
    1: Decimal("0.1000"),
    2: Decimal("0.2500"),
}
BPS_DIVISOR = Decimal("10000")

# ---- performance constants ----------------------------------------------
DEDUCTION_POINTS_BY_SEVERITY = {
    "MINOR": Decimal("2.50"),
    "MAJOR": Decimal("7.50"),
    "CRITICAL": Decimal("20.00"),
}
VARIANCE_DEDUCTION_POINTS = Decimal("5.00")
DELINQUENCY_DEDUCTION_POINTS = Decimal("3.00")
VARIANCE_FLAG_THRESHOLD_PCT = Decimal("15.00")
PERFORMANCE_PREFERRED_MIN = Decimal("85.00")
PERFORMANCE_STANDARD_MIN = Decimal("70.00")

# ---- piggyback constants -------------------------------------------------
PIGGYBACK_AUTHORIZED_MIN = Decimal("85.00")
PIGGYBACK_CONDITIONAL_MIN = Decimal("60.00")
ANALYSIS_VALIDITY_DAYS = 365

STRICT_POINTS = {
    "OUT_OF_STATE_LEAD": Decimal("30.00"),
    "SHORT_NOTICE_CAP": Decimal("25.00"),
    "SHORT_NOTICE_PER_DAY": Decimal("5.00"),
    "TERM_EXCEEDS_STATE_MAX": Decimal("20.00"),
    "NONPROFIT_NOT_PERMITTED": Decimal("40.00"),
}
LIBERAL_POINTS = {
    "OUT_OF_STATE_LEAD": Decimal("15.00"),
    "SHORT_NOTICE_CAP": Decimal("10.00"),
    "SHORT_NOTICE_PER_DAY": Decimal("2.00"),
    "TERM_EXCEEDS_STATE_MAX": Decimal("5.00"),
    "NONPROFIT_NOT_PERMITTED": Decimal("40.00"),
}

# ---- compliance constants ------------------------------------------------
DELINQUENCY_COUNT_THRESHOLD = 2
DELINQUENCY_AMOUNT_THRESHOLD_CENTS = 500000
FEE_DUE_DAYS = 30

# ---- amendment constants -------------------------------------------------
ESCALATION_CAP_BY_INDEX = {
    "CPI_U": Decimal("0.0400"),
    "PPI_COMMODITY": Decimal("0.0600"),
}
PRICE_STABILITY_BUFFER_DAYS = 90
EXPANSION_SCOPE_MIN_PCT = Decimal("0.8000")
MAX_TOTAL_TERM_MONTHS = 60
MAX_RENEWAL_EXTENSION_MONTHS = 12

# ---- audit package -------------------------------------------------------
BASE_AUDIT_DOC_CODES = [
    "NOTICE_OF_SOLICITATION",
    "SPECIFICATION_PACKAGE",
    "PROCUREMENT_METHOD_JUSTIFICATION",
    "ADDENDA_LOG",
    "RESPONSE_TABULATION",
    "EVALUATION_SCORESHEET",
    "AWARD_RECOMMENDATION",
    "CONTRACT_EXECUTION",
]
AMENDMENT_LOG_CODE = "AMENDMENT_LOG"

APPEAL_WINDOW_DAYS = 14


def D(value):
    """Coerce a stored JSON number / string into an exact Decimal."""
    if isinstance(value, Decimal):
        return value
    if value is None:
        return ZERO
    return Decimal(str(value))


def rhu(value, places):
    """ROUND_HALF_UP quantize to ``places`` decimal digits."""
    quantum = Decimal(1).scaleb(-places)
    return D(value).quantize(quantum, rounding=ROUND_HALF_UP)


def cents(value):
    """Round to whole cents (integer)."""
    return int(rhu(value, 0))


def pct2(value):
    """Two-decimal percentage as a Decimal."""
    return rhu(value, 2)


def num(value):
    """Render a Decimal for JSON output."""
    if value is None:
        return None
    return float(value)


# =========================================================================
# net_unit_price  (PRD 3.6)
# =========================================================================

def select_discount_tier(discount_tiers, spend_basis_cents):
    """Highest tier whose min_annual_spend_cents does not exceed the basis."""
    chosen = None
    for tier in discount_tiers:
        if int(tier["min_annual_spend_cents"]) <= int(spend_basis_cents):
            if chosen is None or int(tier["min_annual_spend_cents"]) >= int(
                    chosen["min_annual_spend_cents"]):
                chosen = tier
    if chosen is None:
        chosen = discount_tiers[0]
    return chosen


def net_unit_price(base_unit_price_cents, price_floor_cents, discount_tiers,
                   spend_basis_cents, member_category):
    tier = select_discount_tier(discount_tiers, spend_basis_cents)
    base_pct = D(tier["discount_pct"])
    bonus = NONPROFIT_BONUS_DISCOUNT_PCT if member_category == "NONPROFIT_501C3" else ZERO
    total_pct = base_pct + bonus
    if total_pct > MAX_TOTAL_DISCOUNT_PCT:
        total_pct = MAX_TOTAL_DISCOUNT_PCT
    raw = cents(D(base_unit_price_cents) * (ONE - total_pct))
    floor = int(price_floor_cents)
    net = raw if raw >= floor else floor
    return {
        "tier_index": int(tier["tier_index"]),
        "total_discount_pct": rhu(total_pct, 4),
        "raw_unit_price_cents": raw,
        "net_unit_price_cents": net,
        "floor_binding": floor > raw,
    }


# =========================================================================
# add_on_charges  (PRD 3.6)
# =========================================================================

def add_on_charges(permitted_add_ons, elected_codes, subtotal_cents):
    subtotal = D(subtotal_cents)
    detail = []
    per_code_sum = 0
    elected = set(elected_codes or [])
    for entry in permitted_add_ons or []:
        if entry["code"] not in elected:
            continue
        raw = cents(subtotal * D(entry["rate_pct"]))
        cap = int(entry["cap_cents"])
        capped = raw if raw <= cap else cap
        detail.append({
            "code": entry["code"],
            "raw_cents": raw,
            "capped_cents": capped,
        })
        per_code_sum += capped
    aggregate_cap = cents(subtotal * AGGREGATE_ADD_ON_CAP_PCT)
    charges = per_code_sum if per_code_sum <= aggregate_cap else aggregate_cap
    return {
        "add_on_detail": detail,
        "per_code_sum_cents": per_code_sum,
        "aggregate_cap_cents": aggregate_cap,
        "add_on_charges_cents": charges,
        "aggregate_add_on_cap_binding": aggregate_cap < per_code_sum,
    }


# =========================================================================
# member_usage_total  (PRD 3.6)
# =========================================================================

def member_usage_total(contract, line_item, member, quantity, elected_codes,
                       spend_basis_cents):
    priced = net_unit_price(
        line_item["base_unit_price_cents"],
        line_item["price_floor_cents"],
        contract["discount_tiers"],
        spend_basis_cents,
        member["member_category"],
    )
    subtotal = priced["net_unit_price_cents"] * int(quantity)
    addons = add_on_charges(contract["permitted_add_ons"], elected_codes, subtotal)
    chargeable_base = subtotal + addons["add_on_charges_cents"]
    rebate = FEE_REBATE_BY_TIER.get(priced["tier_index"], ZERO)
    effective_bps = cents(D(contract["admin_fee_rate_bps"]) * (ONE - rebate))
    admin_fee = cents(D(chargeable_base) * D(effective_bps) / BPS_DIVISOR)
    total = chargeable_base + admin_fee
    result = {
        "spend_basis_cents": int(spend_basis_cents),
        "discount_tier_index": priced["tier_index"],
        "total_discount_pct": priced["total_discount_pct"],
        "net_unit_price_cents": priced["net_unit_price_cents"],
        "subtotal_cents": subtotal,
        "add_on_detail": addons["add_on_detail"],
        "add_on_charges_cents": addons["add_on_charges_cents"],
        "chargeable_base_cents": chargeable_base,
        "effective_fee_rate_bps": effective_bps,
        "admin_fee_cents": admin_fee,
        "total_cents": total,
        "floor_binding": priced["floor_binding"],
        "aggregate_add_on_cap_binding": addons["aggregate_add_on_cap_binding"],
    }
    return result


# =========================================================================
# admin_fee_assessment  (PRD 3.7)
# =========================================================================

def reported_fee(reported_chargeable_cents, admin_fee_rate_bps):
    return cents(D(reported_chargeable_cents) * D(admin_fee_rate_bps) / BPS_DIVISOR)


def variance(reported_fee_cents, audited_fee_cents):
    true_up = int(audited_fee_cents) - int(reported_fee_cents)
    rebate = int(reported_fee_cents) - int(audited_fee_cents)
    if int(audited_fee_cents) == 0:
        pct = pct2(ZERO)
    else:
        pct = pct2(Decimal(100) * abs(D(true_up)) / D(audited_fee_cents))
    return {
        "fee_true_up_cents": true_up,
        "fee_rebate_cents": rebate,
        "variance_pct": pct,
        "variance_flagged": pct > VARIANCE_FLAG_THRESHOLD_PCT,
    }


# =========================================================================
# composite_score  (PRD 3.2)
# =========================================================================

def score_responses(responses, technical_weight_pct, price_weight_pct):
    """Score and rank the RESPONSIVE set.  ``responses`` is created_at ASC."""
    if not responses:
        return []
    lowest = min(int(r["proposed_annual_value_cents"]) for r in responses)
    tech_weight = D(technical_weight_pct)
    price_weight = D(price_weight_pct)
    scored = []
    for response in responses:
        price_score = pct2(Decimal(100) * D(lowest) /
                           D(response["proposed_annual_value_cents"]))
        weighted_tech = pct2(D(response["technical_score"]) * tech_weight / Decimal(100))
        weighted_price = pct2(price_score * price_weight / Decimal(100))
        composite = pct2(weighted_tech + weighted_price)
        scored.append({
            "response": response,
            "price_score": price_score,
            "composite_score": composite,
        })
    ranking = sorted(
        range(len(scored)),
        key=lambda i: (-scored[i]["composite_score"], i),
    )
    for rank, index in enumerate(ranking, start=1):
        scored[index]["award_rank"] = rank
    return scored


# =========================================================================
# piggyback_authority  (PRD 3.5)
# =========================================================================

def total_term_months(base_term_start, current_term_end):
    return months_between(base_term_start, current_term_end)


def piggyback_authority(rule, solicitation, contract, member,
                        base_term_start, current_term_end):
    doctrine = rule["piggyback_doctrine"]
    points = STRICT_POINTS if doctrine == "STATUTORY_STRICT" else LIBERAL_POINTS
    detail = []

    lead_state = solicitation["lead_agency_state_code"]
    member_state = member["state_code"]

    if doctrine == "STATUTORY_STRICT":
        if rule["requires_lead_agency_in_state"] and lead_state != member_state:
            detail.append(("OUT_OF_STATE_LEAD", points["OUT_OF_STATE_LEAD"]))
    else:
        if lead_state != member_state and lead_state not in (
                rule.get("reciprocity_state_codes") or []):
            detail.append(("OUT_OF_STATE_LEAD", points["OUT_OF_STATE_LEAD"]))

    notice_days = solicitation.get("notice_days")
    min_notice = int(rule["min_notice_days"])
    if notice_days is not None and int(notice_days) < min_notice:
        shortfall = min_notice - int(notice_days)
        raw = points["SHORT_NOTICE_PER_DAY"] * Decimal(shortfall)
        capped = raw if raw < points["SHORT_NOTICE_CAP"] else points["SHORT_NOTICE_CAP"]
        detail.append(("SHORT_NOTICE", pct2(capped)))

    term_months = total_term_months(base_term_start, current_term_end)
    if term_months > int(rule["max_contract_term_months"]):
        detail.append(("TERM_EXCEEDS_STATE_MAX", points["TERM_EXCEEDS_STATE_MAX"]))

    if member["member_category"] == "NONPROFIT_501C3" and not rule[
            "allows_nonprofit_participation"]:
        detail.append(("NONPROFIT_NOT_PERMITTED", points["NONPROFIT_NOT_PERMITTED"]))

    total_points = sum((p for _, p in detail), ZERO)
    score = pct2(Decimal(100) - total_points)
    if score < ZERO:
        score = pct2(ZERO)

    if score >= PIGGYBACK_AUTHORIZED_MIN:
        determination = "AUTHORIZED"
    elif score >= PIGGYBACK_CONDITIONAL_MIN:
        determination = "CONDITIONAL"
    else:
        determination = "DENIED"

    return {
        "doctrine_applied": doctrine,
        "authority_score": score,
        "determination": determination,
        "deduction_detail": [
            {"reason_code": code, "points": num(pct2(pts))} for code, pts in detail
        ],
        "total_term_months": term_months,
    }


def analysis_expiry(determined_at, current_term_end):
    horizon = add_days(determined_at, ANALYSIS_VALIDITY_DAYS)
    if current_term_end <= horizon:
        return current_term_end, True
    return horizon, False


# =========================================================================
# supplier_performance_score  (PRD 3.9)
# =========================================================================

def performance_tier(score):
    if score >= PERFORMANCE_PREFERRED_MIN:
        return "PREFERRED"
    if score >= PERFORMANCE_STANDARD_MIN:
        return "STANDARD"
    return "PROBATION"


# =========================================================================
# price_adjustment_ceiling  (PRD 3.8)
# =========================================================================

def price_ceiling(base_unit_price_cents, contract_cap_pct, price_index,
                  index_change_pct):
    index_cap = ESCALATION_CAP_BY_INDEX[price_index]
    effective = min(D(contract_cap_pct), index_cap, D(index_change_pct))
    return cents(D(base_unit_price_cents) * (ONE + effective)), rhu(effective, 4)
