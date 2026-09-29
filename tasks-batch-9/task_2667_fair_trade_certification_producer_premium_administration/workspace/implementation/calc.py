"""The nine calculation rules of the PRD, in the pinned order each states."""
from decimal import Decimal

import common as C
from common import dec, floor_int, money, pct, rhu, vol


# ------------------------------------------------------- 1. minimum price floor
def minimum_price_floor(product_code, is_organic, quality_grade,
                        declared_unit_price_cents_per_kg, volume_kg):
    """PRD 3.3 step one: three additive components, two of them conditional."""
    applied_floor = C.MIN_FOB_PRICE_CENTS_PER_KG[product_code]
    if is_organic:
        applied_floor += C.ORGANIC_DIFFERENTIAL_CENTS_PER_KG
    applied_floor += C.QUALITY_DIFFERENTIAL_CENTS_PER_KG[quality_grade]

    declared = int(declared_unit_price_cents_per_kg)
    settled = declared if declared > applied_floor else applied_floor
    volume = vol(volume_kg)
    return {
        "applied_floor_cents_per_kg": applied_floor,
        "settled_unit_price_cents_per_kg": settled,
        "floor_topup_cents": money(dec(settled - declared) * volume),
        "gross_value_cents": money(dec(settled) * volume),
    }


# ------------------------------------------ 2. community development premium
def community_development_premium(product_code, is_organic, volume_kg,
                                  seller_traceability_mode):
    """PRD 3.3 step two. The mass-balance variant's rounding order is pinned."""
    base = dec(C.PREMIUM_RATE_CENTS_PER_KG[product_code])
    if is_organic:
        base = base * (Decimal(1) + C.ORGANIC_PREMIUM_UPLIFT_PCT)
    volume = vol(volume_kg)

    if seller_traceability_mode == "PHYSICAL":
        basis = "PHYSICAL_TRACEABILITY"
        premium_cents = money(base * volume)
    else:
        basis = "MASS_BALANCE"
        lot = C.MASS_BALANCE_LOT_SIZE_KG
        full_lots = floor_int(volume / lot)
        remainder = volume - dec(full_lots) * lot
        per_lot_cents = money(base * lot * C.MASS_BALANCE_ATTRIBUTION_FACTOR)
        remainder_cents = money(base * remainder * C.MASS_BALANCE_ATTRIBUTION_FACTOR)
        premium_cents = full_lots * per_lot_cents + remainder_cents

    return {
        "premium_basis": basis,
        "premium_volume_kg": volume,
        "premium_cents": premium_cents,
    }


# ---------------------------------------------------- 3. label licence fee
def label_license_fee(licensed_volume_kg):
    """PRD 3.8: marginal tiers, each rounded to a whole cent before summing."""
    volume = vol(licensed_volume_kg)
    cap1 = C.LICENSE_TIER_1_CAP_KG
    cap2 = C.LICENSE_TIER_2_CAP_KG

    tier1_volume = volume if volume < cap1 else cap1
    capped2 = volume if volume < cap2 else cap2
    tier2_volume = capped2 - cap1
    if tier2_volume < 0:
        tier2_volume = Decimal(0)
    tier3_volume = volume - cap2
    if tier3_volume < 0:
        tier3_volume = Decimal(0)

    tier1_cents = money(tier1_volume * C.LICENSE_TIER_1_RATE_CENTS_PER_KG)
    tier2_cents = money(tier2_volume * C.LICENSE_TIER_2_RATE_CENTS_PER_KG)
    tier3_cents = money(tier3_volume * C.LICENSE_TIER_3_RATE_CENTS_PER_KG)

    subtotal = C.LICENSE_BASE_FEE_CENTS + tier1_cents + tier2_cents + tier3_cents
    surcharge = money(dec(subtotal) * C.LICENSE_ADMIN_SURCHARGE_PCT)

    if volume <= cap1:
        tier = "TIER_1"
    elif volume <= cap2:
        tier = "TIER_2"
    else:
        tier = "TIER_3"
    return {"license_tier": tier, "license_fee_cents": subtotal + surcharge}


def license_fee_settled(paid_cents, fee_cents):
    return paid_cents >= fee_cents and fee_cents > 0


# ------------------------------------------------------- 4. proposal tally
def proposal_vote_tally(counted_ballots, member_count):
    """PRD 3.5. Turnout's denominator is the elected membership; approval's is
    the ballots cast, abstentions included."""
    ballot_count = len(counted_ballots)
    approve_count = len([v for v in counted_ballots if v["ballot"] == "APPROVE"])
    turnout = pct(dec(ballot_count) / dec(member_count) * 100)
    if ballot_count == 0:
        approval = pct(0)
        turnout = pct(0)
    else:
        approval = pct(dec(approve_count) / dec(ballot_count) * 100)
    return {"turnout_pct": turnout, "approval_pct": approval,
            "ballot_count": ballot_count, "approve_count": approve_count}


def tally_outcome(turnout, approval, quorum_pct):
    if turnout < dec(quorum_pct):
        return "REVISION_REQUESTED"
    if approval >= C.APPROVAL_PCT:
        return "APPROVED"
    return "REJECTED"


# --------------------------------------------- 5. reconciliation variance
def reconciliation_variance(declared_volume_kg, counterparty_volume_kg):
    counterparty = vol(counterparty_volume_kg)
    if counterparty == 0:
        return counterparty, pct(0)
    variance = pct((vol(declared_volume_kg) - counterparty) / counterparty * 100)
    return counterparty, variance


def reconciliation_outcome(variance_pct):
    magnitude = variance_pct if variance_pct >= 0 else -variance_pct
    if magnitude > C.MAX_VARIANCE_HARD_PCT:
        return "EXCEEDED"
    if magnitude <= C.VARIANCE_TOLERANCE_PCT:
        return "MATCHED"
    return "VARIANCE_FLAGGED"


# ----------------------------------- 6. compliance score / cap deadline
def score_from_counts(critical, major, minor):
    score = (100
             - C.SCORE_WEIGHT_CRITICAL * critical
             - C.SCORE_WEIGHT_MAJOR * major
             - C.SCORE_WEIGHT_MINOR * minor)
    return score if score > 0 else 0


def grade_counts(findings):
    """Counts under the open filter of PRD 3.6 step one."""
    critical = major = minor = 0
    for finding in findings:
        if finding["status"] not in C.NC_OPEN_STATUSES:
            continue
        if finding["grade"] == "CRITICAL":
            critical += 1
        elif finding["grade"] == "MAJOR":
            major += 1
        elif finding["grade"] == "MINOR":
            minor += 1
    return critical, major, minor


def cap_allowance(score_before):
    """PRD 3.6 step two."""
    if score_before >= 90:
        return Decimal("1.5"), 14
    if score_before >= 70:
        return Decimal("1.0"), 7
    return Decimal("0.5"), 0


def cap_deadline_days(grade, multiplier):
    """PRD 3.6 step three: base allowance times multiplier, truncated down."""
    return floor_int(dec(C.BASE_CAP_DAYS[grade]) * multiplier)


def audit_interval_months(score_after):
    """PRD 3.6 step five."""
    if score_after >= 90:
        return 24
    if score_after >= 70:
        return 12
    return 6


# ----------------------------------------------- 7. mass balance credit
def available_credit(node):
    return vol(dec(node["certified_input_kg"])
               - dec(node["claimed_output_kg"])
               - dec(node["reserved_output_kg"]))


def conversion_adjusted(volume_kg, conversion_ratio):
    return vol(dec(volume_kg) * dec(conversion_ratio))
