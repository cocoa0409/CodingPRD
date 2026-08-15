"""Income tier determination (calc: income_tier_determination).

Integer cross-multiplication only — no floats ever participate (PRD §2.6).
"""

FPL_2026_CENTS = {
    1: 1565000, 2: 2115000, 3: 2665000, 4: 3215000,
    5: 3765000, 6: 4315000, 7: 4865000, 8: 5415000,
}
FPL_ADDITIONAL_MEMBER_CENTS = 550000


def fpl_for(household_size):
    return (FPL_2026_CENTS[min(household_size, 8)]
            + max(0, household_size - 8) * FPL_ADDITIONAL_MEMBER_CENTS)


def tier_for(household_size, measure_cents):
    fpl = fpl_for(household_size)
    m100 = measure_cents * 100
    if m100 <= 150 * fpl:
        return "TIER_1"
    if m100 <= 200 * fpl:
        return "TIER_2"
    if m100 <= 250 * fpl:
        return "TIER_3"
    return "INELIGIBLE"


def provisional_tier(application):
    """ANNUALIZED_CURRENT_MONTH variant (creation)."""
    return tier_for(application["household_size"],
                    application["current_month_income_cents"] * 12)


def final_tier(application):
    """ANNUAL_GROSS variant (verify)."""
    return tier_for(application["household_size"],
                    application["gross_annual_income_cents"])


DISCOUNT_PCT = {"TIER_1": 50, "TIER_2": 30, "TIER_3": 15}
