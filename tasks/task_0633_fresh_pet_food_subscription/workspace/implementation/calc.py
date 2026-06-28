"""Calculation rules per PRD §3 / SCAFFOLD §1.3.

All monetary math is integer cents. Rounding is round-half-up, applied only at
the designated final step of each rule. Decimal is used so the .5 boundary
rounds away from zero exactly.
"""
import math
from decimal import Decimal, ROUND_HALF_UP

# --- Constants ------------------------------------------------------------
# daily_calorie_target
RER_COEFF = {"DOG": 70.0, "CAT": 60.0}
NEUTER_MULT = 1.0
INTACT_MULT = 1.2
ACTIVITY_MULT = {"LOW": 1.0, "MODERATE": 1.2, "HIGH": 1.5}
STAGE_MULT = {"PUPPY_KITTEN": 1.6, "ADULT": 1.0, "SENIOR": 0.9}
GOAL_MULT = {"LOSE": 0.8, "MAINTAIN": 1.0, "GAIN": 1.15}

# cycle_price volume tiers
# pack_total_grams < 4000 -> 0.00; 4000 <= g < 8000 -> 0.05; g >= 8000 -> 0.10
# shipping
SHIP_BASE_CENTS = 999
FREE_SHIP_THRESHOLD_CENTS = 8000

# coolant
COOLANT_GRAMS_PER_PACK = 4000
COOLANT_FREE_DAYS = 2
COOLANT_MIN = 1

# referral
REFERRED_FLAT_CENTS = 2000
REFERRER_FLAT_CENTS = 1500
REFERRER_ANNUAL_CAP_CENTS = 9000

# subscription / billing
TRANSITION_CYCLES = 2
MAX_FAILED_CHARGES = 3


def round_half_up(value, ndigits=0):
    """Round half up (away from zero at the .5 boundary)."""
    q = Decimal(1) if ndigits == 0 else Decimal(1).scaleb(-ndigits)
    return Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP)


# --- Life stage (PRD §3.3) ------------------------------------------------
def life_stage(birth_date, clock_now):
    """PUPPY_KITTEN if age_years < 1; SENIOR if age_years >= 8; else ADULT.

    age_years = floor((clock_date - birth_date) days / 365).
    """
    days = (clock_now - birth_date).days
    age_years = days // 365
    if age_years < 1:
        return "PUPPY_KITTEN"
    if age_years >= 8:
        return "SENIOR"
    return "ADULT"


# --- Daily calorie target (PRD §3.3, calc daily_calorie_target) -----------
def daily_calorie_target(pet, clock_now):
    """Evaluation order pinned: life_stage, RER_basis, four multipliers L->R,
    then round once at the final step. No intermediate rounding.
    """
    species = pet["species"]
    stage = life_stage(pet["birth_date"], clock_now)

    neuter_mult = NEUTER_MULT if pet["neutered"] else INTACT_MULT
    activity_mult = ACTIVITY_MULT[pet["activity_level"]]
    stage_mult = STAGE_MULT[stage]
    goal_mult = GOAL_MULT[pet["body_condition_goal"]]

    if pet["body_condition_goal"] in ("LOSE", "GAIN"):
        basis_weight = pet["ideal_weight_kg"]
    else:
        basis_weight = pet["current_weight_kg"]

    rer_basis = RER_COEFF[species] * (basis_weight ** 0.75)
    raw = rer_basis * neuter_mult * activity_mult * stage_mult * goal_mult
    return int(round_half_up(raw, 0)), stage


# --- Pack & cycle price (PRD §3.5, calc cycle_price) ----------------------
def volume_discount(pack_total_grams):
    if pack_total_grams < 4000:
        return Decimal("0.00")
    if pack_total_grams < 8000:
        return Decimal("0.05")
    return Decimal("0.10")


def pack_and_price(daily_cal, kcal_per_gram, cadence_days, price_per_100g_cents):
    """Round grams-per-day first (whole grams), THEN scale; round price once at end.

    Returns (pack_grams_per_day, pack_total_grams, cycle_price_cents).
    """
    pack_grams_per_day = int(round_half_up(daily_cal / kcal_per_gram, 0))
    pack_total_grams = pack_grams_per_day * cadence_days
    hundreds = Decimal(pack_total_grams) / Decimal(100)
    discount = volume_discount(pack_total_grams)
    tier_rate_cents = Decimal(price_per_100g_cents) * (Decimal(1) - discount)
    cycle_price_cents = int(round_half_up(hundreds * tier_rate_cents, 0))
    return pack_grams_per_day, pack_total_grams, cycle_price_cents


# --- Shipping (PRD §3.7, calc shipping_fee) -------------------------------
def shipping_fee(food_subtotal_cents):
    if food_subtotal_cents >= FREE_SHIP_THRESHOLD_CENTS:
        return 0
    return SHIP_BASE_CENTS


# --- Order charge settlement (PRD §3.7, calc order_charge_settlement) ------
def settle_charge(food_subtotal_cents, wallet_credit_cents):
    """Pinned: shipping from pre-credit subtotal, then credit applied to gross.

    Returns (shipping_cents, credit_applied_cents, total_charged_cents).
    Integer arithmetic, no rounding.
    """
    shipping_cents = shipping_fee(food_subtotal_cents)
    gross = food_subtotal_cents + shipping_cents
    credit_applied_cents = min(wallet_credit_cents, gross)
    total_charged_cents = gross - credit_applied_cents
    return shipping_cents, credit_applied_cents, total_charged_cents


# --- Coolant (PRD §3.9, calc coolant_packs) -------------------------------
def coolant_packs(food_grams, transit_days):
    mass_units = math.ceil(food_grams / COOLANT_GRAMS_PER_PACK)
    day_units = max(0, transit_days - COOLANT_FREE_DAYS)
    return max(COOLANT_MIN, mass_units + day_units)


# --- Referral credit (PRD §3.8, calc referral_credit) ---------------------
def referrer_grant_cents(referrer_lifetime_cents):
    room = max(0, REFERRER_ANNUAL_CAP_CENTS - referrer_lifetime_cents)
    return min(REFERRER_FLAT_CENTS, room)


def referred_grant_cents():
    return REFERRED_FLAT_CENTS
