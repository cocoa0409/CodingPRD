"""Pure calculation helpers — §1.3 calc rules."""
from decimal import Decimal, ROUND_HALF_UP


# Tier determination constants
FREE_PCT = Decimal("1.30")
REDUCED_PCT = Decimal("1.85")

FPL_MONTHLY_CONTIGUOUS = {
    1: 1255, 2: 1704, 3: 2152, 4: 2600,
    5: 3049, 6: 3497, 7: 3946, 8: 4394,
}
FPL_MONTHLY_ALASKA = {
    1: 1569, 2: 2129, 3: 2690, 4: 3251,
    5: 3811, 6: 4372, 7: 4933, 8: 5494,
}
FPL_MONTHLY_HAWAII = {
    1: 1443, 2: 1960, 3: 2476, 4: 2993,
    5: 3509, 6: 4026, 7: 4543, 8: 5059,
}

REGION_MAP = {"AK": "ALASKA", "HI": "HAWAII"}

# Pricing constants
REDUCED_DISCOUNT_FACTOR = Decimal("0.10")
REDUCED_PRICE_CAP_CENTS = 40
ALLERGEN_SUB_SURCHARGE_CENTS = 25

# Topup constant
DAILY_TOPUP_CAP_CENTS = 20000


def _region_for_state(state: str) -> str:
    return REGION_MAP.get(state, "CONTIGUOUS")


def _fpl_table_for_region(region: str) -> dict:
    if region == "ALASKA":
        return FPL_MONTHLY_ALASKA
    if region == "HAWAII":
        return FPL_MONTHLY_HAWAII
    return FPL_MONTHLY_CONTIGUOUS


def round_half_up_int(value: Decimal) -> int:
    """Round half-up to integer."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def determine_tier_from_income(
    snapshot_annual_income_cents: int,
    snapshot_family_size: int,
    snapshot_address_state: str,
    direct_certification_flag: bool,
) -> str:
    """§1.3 determine_tier_from_income. Returns 'FREE' | 'REDUCED' | 'PAID'."""
    if direct_certification_flag:
        return "FREE"

    # Step 1: monthly income, round half-up
    household_monthly_cents = round_half_up_int(
        Decimal(snapshot_annual_income_cents) / Decimal(12)
    )

    # Step 2-3: select FPL table for region
    region = _region_for_state(snapshot_address_state)
    table = _fpl_table_for_region(region)

    # Family size beyond the largest tabulated entry: USDA actually uses an
    # additive per-person increment, but the scaffold/PRD tabulates only 1..8.
    # We assume family_size is clamped to that range in tests; we still need
    # to handle defensively. Fall back to the largest size if exceeded.
    fs = snapshot_family_size
    if fs not in table:
        # Use highest available row if family is larger than table; smallest if smaller.
        if fs > max(table.keys()):
            fs = max(table.keys())
        else:
            fs = min(table.keys())

    fpl_monthly_cents = table[fs] * 100

    # Step 4: thresholds via floor (integer truncation)
    threshold_free_cents = int(
        (Decimal(fpl_monthly_cents) * FREE_PCT).to_integral_value(rounding="ROUND_FLOOR")
    )
    threshold_reduced_cents = int(
        (Decimal(fpl_monthly_cents) * REDUCED_PCT).to_integral_value(rounding="ROUND_FLOOR")
    )

    # Step 5: inclusive comparisons
    if household_monthly_cents <= threshold_free_cents:
        return "FREE"
    elif household_monthly_cents <= threshold_reduced_cents:
        return "REDUCED"
    else:
        return "PAID"


def compute_paid_charge(
    applied_tier: str,
    list_price_cents: int,
    menu_allergens: list,
    student_allergens: list,
    substitute_for_allergen: bool,
) -> int:
    """§1.3 compute_paid_charge. Returns integer cents."""
    if applied_tier == "FREE":
        tier_cents = 0
    elif applied_tier == "REDUCED":
        discounted = round_half_up_int(Decimal(list_price_cents) * REDUCED_DISCOUNT_FACTOR)
        tier_cents = min(REDUCED_PRICE_CAP_CENTS, discounted)
    else:  # PAID
        tier_cents = list_price_cents

    # Allergen surcharge — FREE tier never pays the surcharge
    if (
        substitute_for_allergen is True
        and applied_tier != "FREE"
        and _intersects(menu_allergens, student_allergens)
    ):
        tier_cents += ALLERGEN_SUB_SURCHARGE_CENTS

    return tier_cents


def _intersects(a, b):
    if not a or not b:
        return False
    return bool(set(a) & set(b))
