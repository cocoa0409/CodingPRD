"""The specification's calculation rules (SCAFFOLD 1.3 / PRD sections 3.x)."""

from decimal import Decimal
from fractions import Fraction

import constants as K
from numeric import frac, pct, rhu, rhu_cents

BP = K.BASIS_POINTS_DENOMINATOR


# --- risk assessment (two variants) ---------------------------------------

def risk_assessment(exposure_medium, samples):
    """Medium-filtered; central tendency over VALID, RME over VALID+ESTIMATED."""
    in_medium = [s for s in samples if s["medium"] == exposure_medium]
    central = [s for s in in_medium if s["qa_status"] == "VALID"]
    rme = [s for s in in_medium if s["qa_status"] in ("VALID", "ESTIMATED")]
    if not central:
        return None

    total = sum((frac(s["concentration_ug_per_l"]) for s in central), Fraction(0))
    ct_epc = rhu(total / len(central), 3)
    rme_epc = max(s["concentration_ug_per_l"] for s in rme)

    unit_risk = Decimal(K.UNIT_RISK_PER_UG_PER_L)
    ct_risk = rhu(frac(ct_epc) * frac(unit_risk), 7)
    rme_risk = rhu(frac(rme_epc) * frac(unit_risk), 7)
    hazard = rhu(frac(rme_epc) / frac(Decimal(K.REFERENCE_CONCENTRATION_UG_PER_L)), 2)

    exceeded = rme_risk >= Decimal(K.ACTION_LEVEL_RISK) or hazard >= Decimal(
        K.HAZARD_INDEX_LIMIT
    )
    return {
        "central_tendency_epc_ug_per_l": ct_epc,
        "rme_epc_ug_per_l": rhu(rme_epc, 3),
        "central_tendency_risk": ct_risk,
        "rme_risk": rme_risk,
        "hazard_index": hazard,
        "action_level_exceeded": bool(exceeded),
    }


# --- remedy present value and scoring -------------------------------------

def remedy_npv(capital_cost_cents, annual_om_cost_cents, om_years, discount_rate_bp):
    """Each annual term is discounted and rounded to whole cents BEFORE it
    enters the sum; summing first and rounding once is a different answer."""
    rate = Fraction(discount_rate_bp, BP)
    one_plus = 1 + rate
    total = capital_cost_cents
    annual = Fraction(annual_om_cost_cents)
    for year in range(1, om_years + 1):
        total += rhu_cents(annual / (one_plus ** year))
    return total


def cost_score(npv_cents):
    raw = 100 - Fraction(npv_cents, K.NPV_COST_SCORE_DIVISOR)
    clamped = max(Fraction(0), raw)
    clamped = min(Fraction(100), clamped)
    return pct(clamped)


def remedy_score(effectiveness_score, implementability_score, score_cost, exceeded):
    if exceeded:
        we, wi, wc = Fraction(65, 100), Fraction(20, 100), Fraction(15, 100)
    else:
        we, wi, wc = Fraction(45, 100), Fraction(35, 100), Fraction(20, 100)
    total = (
        we * Fraction(effectiveness_score)
        + wi * Fraction(implementability_score)
        + wc * frac(score_cost)
    )
    return pct(total)


def remedy_selector(pool, exceeded):
    """Greatest remedy_score, tie -> lowest npv_cents, still tied -> earliest
    created (never by id)."""
    candidates = list(pool)
    if exceeded:
        candidates = [
            a
            for a in candidates
            if a["effectiveness_score"] >= K.PROTECTIVE_EFFECTIVENESS_MIN
        ]
    if not candidates:
        return None
    candidates.sort(key=lambda a: (-a["remedy_score"], a["npv_cents"], a["created_at"], a["seq"]))
    return candidates[0]


# --- oversight cost reimbursement -----------------------------------------

def oversight_rate_bp(direct_cents):
    """The tier is keyed on the pre-fee direct subtotal, never on the billed
    total; both ceilings are inclusive."""
    if direct_cents <= K.TIER1_CEILING_CENTS:
        return K.INDIRECT_RATE_TIER1_BP
    if direct_cents <= K.TIER2_CEILING_CENTS:
        return K.INDIRECT_RATE_TIER2_BP
    return K.INDIRECT_RATE_TIER3_BP


def oversight_figures(direct_cents):
    rate = oversight_rate_bp(direct_cents)
    indirect = rhu_cents(Fraction(direct_cents * rate, BP))
    return rate, indirect, direct_cents + indirect


def cap_utilization_pct(billed_cents, cap_cents):
    if not cap_cents:
        return None
    return pct(Fraction(billed_cents * 100, cap_cents))


# --- stipulated penalty accrual -------------------------------------------

def penalty_cap_cents(oversight_cost_cap_cents):
    return rhu_cents(Fraction(oversight_cost_cap_cents * K.PENALTY_CAP_BP, BP))


def penalty_accrual(first_noncompliance_date, effective_date, per_day_cents, cap_cents):
    """Recomputed in full from first_noncompliance_date on every assessment, so
    the thirty-day rate step is never applied twice."""
    days = (effective_date - first_noncompliance_date).days + 1
    if days < 0:
        days = 0
    flat_days = min(days, K.PENALTY_STEP_DAYS)
    escalated_days = max(0, days - K.PENALTY_STEP_DAYS)
    escalated_rate = rhu_cents(Fraction(per_day_cents * K.PENALTY_ESCALATION_BP, BP))
    gross = flat_days * per_day_cents + escalated_days * escalated_rate
    accrued = min(gross, cap_cents)
    return days, accrued, gross > cap_cents


# --- de minimis -----------------------------------------------------------

def volumetric_share_pct(verified_volume_tons, site_verified_total):
    if not site_verified_total or frac(site_verified_total) == 0:
        return Decimal("0.00")
    return pct(frac(verified_volume_tons) * 100 / frac(site_verified_total))


def de_minimis_eligible(share_pct, max_toxicity_class, verified_volume_tons):
    if not max_toxicity_class:
        return False
    if max_toxicity_class not in K.DE_MINIMIS_TOXICITY_CLASSES:
        return False
    if frac(share_pct) > frac(Decimal(K.DE_MINIMIS_SHARE_CEILING_PCT)):
        return False
    if frac(verified_volume_tons) > frac(Decimal(K.DE_MINIMIS_VOLUME_CEILING_TONS)):
        return False
    return True


def de_minimis_premium_floor(total_response_cost_cents, share_pct_at_offer):
    return rhu_cents(
        frac(total_response_cost_cents)
        * frac(share_pct_at_offer)
        / 100
        * frac(Decimal(K.DE_MINIMIS_PREMIUM_MULTIPLIER))
    )


# --- bid tolerance --------------------------------------------------------

def bid_ceiling_ok(awarded_amount_cents, engineer_estimate_cents):
    ceiling = Fraction(engineer_estimate_cents) * (1 + Fraction(K.BID_TOLERANCE_BP, BP))
    return Fraction(awarded_amount_cents) <= ceiling


# --- gore-factor allocation share arithmetic ------------------------------

def allocation_pcts(weights, rows):
    """`weights` is (wv, wt, wo); `rows` is the candidate parties in
    enumeration order, each a dict with keys vol, tox, own, key.

    Returns (mapping key -> Decimal percentage, has_basis).
    """
    wv, wt, wo = weights
    tv = sum((r["vol"] for r in rows), Fraction(0))
    tt = sum((r["tox"] for r in rows), Fraction(0))
    to = sum((r["own"] for r in rows), Fraction(0))

    has_basis = tv > 0 or tt > 0 or to > 0
    active = []
    if tv > 0:
        active.append(wv)
    if tt > 0:
        active.append(wt)
    if to > 0:
        active.append(wo)
    denom = sum(active)

    out = {}
    running = Fraction(0)
    for row in rows:
        raw = Fraction(0)
        if denom > 0:
            if tv > 0:
                raw += Fraction(wv, denom) * (row["vol"] / tv)
            if tt > 0:
                raw += Fraction(wt, denom) * (row["tox"] / tt)
            if to > 0:
                raw += Fraction(wo, denom) * (row["own"] / to)
        value = pct(raw * 100)
        out[row["key"]] = value
        running += frac(value)

    if rows:
        remainder = Fraction(100) - running
        if remainder != 0:
            winner = max(
                range(len(rows)),
                key=lambda i: (rows[i]["vol"], rows[i]["own"], -i),
            )
            key = rows[winner]["key"]
            out[key] = pct(frac(out[key]) + remainder)
    return out, has_basis
