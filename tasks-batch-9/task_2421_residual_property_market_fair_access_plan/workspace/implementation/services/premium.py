"""The annual premium ladder (PRD 3.6) — pinned step order, rounded half-up to
whole cents at each named step.

Four variants share the ladder: PROVISIONAL_QUOTE, VOLUNTARY_EQUIVALENT,
BOUND_FINAL and RENEWAL_FINAL.  They differ only in the rate substituted in
step 1, the rating condition score used in step 5 and the cleared-major count
used in step 6.
"""

from util import D, rhu4, rhu_cents
from services.constants import (
    CAT_SURCHARGE_CAP_PCT,
    CAT_SURCHARGE_FLOOR_RATIO,
    CAT_SURCHARGE_SLOPE,
    CONSTRUCTION_FACTOR,
    IMPROVEMENT_CREDIT_CAP_PCT,
    IMPROVEMENT_CREDIT_PER_MAJOR_PCT,
    MIN_ANNUAL_PREMIUM_CENTS,
    OCCUPANCY_FACTOR,
    PACKAGE_FACTOR,
)


def condition_adjustment_pct(score):
    """Step 5 — a signed adjustment percentage read off the condition score."""
    if score is None:
        score = 0
    if score >= 85:
        return D("-0.10")
    if score >= 70:
        return D("-0.05")
    if score >= 50:
        return D("0.00")
    return D("0.15")


def cat_surcharge_pct(concentration_ratio):
    """Step 3 — surcharge percentage from the territory's four-decimal ratio."""
    ratio = D(concentration_ratio if concentration_ratio is not None else 0)
    excess = ratio - CAT_SURCHARGE_FLOOR_RATIO
    if excess < 0:
        excess = D(0)
    pct = excess * CAT_SURCHARGE_SLOPE
    if pct > CAT_SURCHARGE_CAP_PCT:
        pct = CAT_SURCHARGE_CAP_PCT
    return pct


def improvement_credit_pct(cleared_major_count):
    count = cleared_major_count or 0
    pct = IMPROVEMENT_CREDIT_PER_MAJOR_PCT * D(count)
    if pct > IMPROVEMENT_CREDIT_CAP_PCT:
        pct = IMPROVEMENT_CREDIT_CAP_PCT
    return pct


def compute(rate_per_1000_cents, dwelling_limit_cents, construction_type,
            occupancy, peril_package, concentration_ratio, score,
            cleared_major_count):
    """Return (base_premium_cents, cat_surcharge_cents, annual_premium_cents)."""
    # Step 1 / 2 — base premium.
    thousands = D(dwelling_limit_cents) / D(100000)
    base_raw = (D(rate_per_1000_cents)
                * thousands
                * CONSTRUCTION_FACTOR[construction_type]
                * OCCUPANCY_FACTOR[occupancy]
                * PACKAGE_FACTOR[peril_package])
    base_premium_cents = rhu_cents(base_raw)

    # Step 3 — catastrophe concentration surcharge.
    surcharge_pct = cat_surcharge_pct(concentration_ratio)
    cat_cents = rhu_cents(D(base_premium_cents) * surcharge_pct)

    # Step 4 — pre-credit premium; both later adjustments key off this figure.
    pre_credit_cents = base_premium_cents + cat_cents

    # Step 5 — condition adjustment, signed.
    condition_cents = rhu_cents(D(pre_credit_cents) * condition_adjustment_pct(score))

    # Step 6 — improvement credit.
    credit_cents = rhu_cents(D(pre_credit_cents)
                             * improvement_credit_pct(cleared_major_count))

    # Step 7 — floor.
    annual = pre_credit_cents + condition_cents - credit_cents
    if annual < MIN_ANNUAL_PREMIUM_CENTS:
        annual = MIN_ANNUAL_PREMIUM_CENTS
    return base_premium_cents, cat_cents, annual


def comparison_pct(quoted_cents, voluntary_cents):
    """(quoted - voluntary) / voluntary, half-up to four decimals."""
    if voluntary_cents == 0:
        return rhu4(D(0))
    return rhu4(D(quoted_cents - voluntary_cents) / D(voluntary_cents))


def differential_pct(filed_rate_cents, voluntary_rate_cents):
    return rhu4(D(filed_rate_cents - voluntary_rate_cents) / D(voluntary_rate_cents))
