"""Premium, bond, loss-ratio and renewal pricing calculations.

All money is integer cents. Round-half-up is applied after each
multiplication step for policy premiums; the bond premium rounds each tier
contribution before summing (PRD section 2.6).
"""

from decimal import Decimal, ROUND_HALF_UP

from db import db

MIN_PREMIUM_CENTS = 25000

BASE_RATE = {
    "GENERAL_LIABILITY": Decimal("0.0120"),
    "EQUIPMENT": Decimal("0.0185"),
    "CAST": Decimal("0.0275"),
    "ERRORS_OMISSIONS": Decimal("0.0350"),
    "FOREIGN_TRAVEL": Decimal("0.0420"),
}

RISK_MULTIPLIER = {
    "FEATURE": Decimal("1.00"),
    "EPISODIC": Decimal("1.15"),
    "DOCUMENTARY": Decimal("0.85"),
    "COMMERCIAL": Decimal("0.90"),
    "MUSIC_VIDEO": Decimal("1.05"),
}

STUNT_LOADING_PER_STUNT = Decimal("0.10")
STUNT_LOADING_CAP = Decimal("1.50")
ESSENTIAL_ELEMENT_LOADING = Decimal("1.20")
FOREIGN_TRAVEL_LOADING_PER_TRAVELER = Decimal("0.05")
FOREIGN_TRAVEL_LOADING_CAP = Decimal("1.40")

# Bond premium tiers: (tier_lower_cents, tier_upper_cents or None, rate)
BOND_TIERS = [
    (0, 100000000, Decimal("0.0200")),
    (100000000, 500000000, Decimal("0.0150")),
    (500000000, 2500000000, Decimal("0.0110")),
    (2500000000, None, Decimal("0.0085")),
]
BOND_COVER_MIN_PCT = 50


def _rh(value):
    """Round a Decimal half-up to whole cents, returning int."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def premium_calculate(prod, policy, payroll_cents):
    """Tiered policy premium (provisional and final variants share the formula).

    Round half up after each multiplication step, in factor order; the
    minimum-premium floor applies after rounding.
    """
    line = policy["coverage_line"]
    result = Decimal(payroll_cents)
    result = Decimal(_rh(result * BASE_RATE[line]))
    result = Decimal(_rh(result * RISK_MULTIPLIER[prod["production_type"]]))

    if line == "CAST":
        stunt_count = sum(
            1 for cm in db.cast_members.values()
            if cm["production_id"] == prod["id"] and cm["role_tier"] == "STUNT"
        )
        stunt_loading = min(
            Decimal("1.0") + STUNT_LOADING_PER_STUNT * stunt_count,
            STUNT_LOADING_CAP,
        )
        result = Decimal(_rh(result * stunt_loading))

        has_essential = any(
            cm["production_id"] == prod["id"] and cm["essential_element"]
            for cm in db.cast_members.values()
        )
        essential_loading = ESSENTIAL_ELEMENT_LOADING if has_essential else Decimal("1.00")
        result = Decimal(_rh(result * essential_loading))

    if line == "FOREIGN_TRAVEL":
        travelers = sum(
            ext["travelers_count"]
            for ext in db.travel_extensions.values()
            if ext["production_id"] == prod["id"]
        )
        ft_loading = min(
            Decimal("1.0") + FOREIGN_TRAVEL_LOADING_PER_TRAVELER * travelers,
            FOREIGN_TRAVEL_LOADING_CAP,
        )
        result = Decimal(_rh(result * ft_loading))

    premium = int(result)
    if premium < MIN_PREMIUM_CENTS:
        premium = MIN_PREMIUM_CENTS
    return premium


def bond_min_amount_cents(budget_cents):
    """Minimum bond amount: half the budget, rounded up to whole cents."""
    return -(-(budget_cents * BOND_COVER_MIN_PCT) // 100)


def bond_premium_calculate(bond_amount_cents):
    """Tiered bond premium: round each tier contribution, then sum."""
    total = 0
    for lower, upper, rate in BOND_TIERS:
        if bond_amount_cents <= lower:
            continue
        top = bond_amount_cents if upper is None else min(bond_amount_cents, upper)
        tier_base = top - lower
        if tier_base <= 0:
            continue
        total += _rh(Decimal(tier_base) * rate)
    return total


def loss_ratio_calculate(policy):
    """Incurred losses vs provisional earned premium, in basis-points-of-percent."""
    incurred = 0
    for cl in db.claims.values():
        if cl["policy_id"] != policy["id"]:
            continue
        if cl["status"] not in ("ADJUSTED", "SETTLED", "CLOSED"):
            continue
        if not (policy["effective_date"] <= cl["occurrence_date"] <= policy["expiry_date"]):
            continue
        incurred += cl["loss_amount_cents"] - cl["deductible_applied_cents"]
    earned = policy["provisional_premium_cents"] or 0
    if earned == 0:
        return 0
    return _rh(Decimal(incurred) * Decimal(10000) / Decimal(earned))


def renewal_premium_quote(base_premium_cents, loss_ratio_pct):
    """Renewal offered premium from prior premium and loss-ratio loading."""
    if loss_ratio_pct < 3000:
        factor = Decimal("0.90")
    elif loss_ratio_pct < 6000:
        factor = Decimal("1.00")
    elif loss_ratio_pct < 9000:
        factor = Decimal("1.15")
    else:
        factor = Decimal("1.40")
    return _rh(Decimal(base_premium_cents or 0) * factor)
