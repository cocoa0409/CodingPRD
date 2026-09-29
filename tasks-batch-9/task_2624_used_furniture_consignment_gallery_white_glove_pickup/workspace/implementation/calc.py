"""Every calculation in the PRD, with the rounding points pinned (PRD 2.6)."""

from decimal import Decimal, ROUND_HALF_UP

ONE = Decimal(1)

# --- photo screening -------------------------------------------------------
WEIGHT_SURFACE = Decimal("0.45")
WEIGHT_STRUCTURE = Decimal("0.30")
WEIGHT_COMPLETENESS = Decimal("0.25")
REJECT_BELOW = Decimal("3.00")
GRADE_A_MIN = Decimal("8.50")
GRADE_B_MIN = Decimal("6.50")
GRADE_C_MIN = Decimal("4.50")

# --- list price ------------------------------------------------------------
GRADE_FACTOR = {
    "A": Decimal("0.85"),
    "B": Decimal("0.70"),
    "C": Decimal("0.55"),
    "D": Decimal("0.40"),
}
CATEGORY_FACTOR = {
    "SOFA": Decimal("0.95"),
    "DINING": Decimal("1.05"),
    "CASEGOOD": Decimal("1.00"),
    "RUG": Decimal("1.10"),
    "ART": Decimal("1.20"),
    "OUTDOOR": Decimal("0.85"),
}
BUNDLE_FACTOR = Decimal("0.90")
CLEARANCE_THRESHOLD_CENTS = 50000

GRADE_RANK = {"A": 4, "B": 3, "C": 2, "D": 1, "REJECTED": 0}

# --- markdown --------------------------------------------------------------
DISCOUNT_ELECTION_EXTRA_PCT = Decimal("0.10")
ELECTION_EXTENSION_DAYS = 30

# --- pickup surcharge ------------------------------------------------------
BASE_CENTS = 12000
VOLUME_BLOCK_CENTS = 2500
VOLUME_BLOCK_CUFT = 10
STAIR_FLIGHT_CENTS = 4500
STAIR_FLIGHT_CAP = 6
EXTREME_CLIMB_CENTS = 8000
ELEVATOR_FLAT_CENTS = 3000
BULKY_ITEM_CENTS = 5500
BULKY_VOLUME_CUFT = 60
CREW_MULTIPLIER = {"2": Decimal("1.00"), "3": Decimal("1.25"), "4_PLUS": Decimal("1.45")}
CAP_PCT = Decimal("0.35")

# --- consignor split ------------------------------------------------------
CATEGORY_BASE = {
    "SOFA": Decimal("0.50"),
    "DINING": Decimal("0.55"),
    "CASEGOOD": Decimal("0.55"),
    "RUG": Decimal("0.60"),
    "ART": Decimal("0.65"),
    "OUTDOOR": Decimal("0.45"),
}
PRICE_BONUS_LOW_CENTS = 50000
PRICE_BONUS_HIGH_CENTS = 150000
TENURE_PENALTY = Decimal("0.05")
TENURE_PENALTY_SEQUENCE = 3
PCT_FLOOR = Decimal("0.40")
PCT_CEILING = Decimal("0.70")

# --- shrinkage / payout / damage / delivery -------------------------------
SHRINKAGE_CREDIT_PCT = Decimal("0.60")
TIER_MID_CENTS = 100000
TIER_HIGH_CENTS = 500000
METHOD_FEE = {"ACH": 0, "CHECK": 250, "STORE_CREDIT": 0}
MIN_PAYOUT_CENTS = 2000
GALLERY_DEDUCTIBLE_CENTS = 5000
SHARED_FAULT_PCT = Decimal("0.50")
BASE_DELIVERY_CENTS = 7500
ASSEMBLY_CENTS = 4000
ASSEMBLY_CATEGORIES = ("DINING", "CASEGOOD")

SALE_FLOOR_PCT = Decimal("0.80")
DISPOSAL_FEE_RETURN_CENTS = 4000
DISPOSAL_FEE_DONATION_CENTS = 2500
SUSPEND_BELOW_CENTS = -50000
DONATE_PRICE_CEILING_CENTS = 200000
CLAIM_WINDOW_DAYS = 5
TURNAROUND_SECONDS = 45 * 60
DORMANT_DAYS = 365
ESCHEAT_DAYS = 545
TIGHT_RATIO = Decimal("0.75")
FULL_RATIO = Decimal("1.00")


def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rhu(value):
    """Round half up to a whole cent."""
    return int(dec(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu2(value):
    """Round half up to two decimal places (the photo score)."""
    return dec(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def ceil_div(numerator, denominator):
    return -((-int(numerator)) // int(denominator))


# ---------------------------------------------------------------------------
# photo_screening_score
# ---------------------------------------------------------------------------
def photo_score(surface, structure, completeness):
    raw = (
        WEIGHT_SURFACE * dec(surface)
        + WEIGHT_STRUCTURE * dec(structure)
        + WEIGHT_COMPLETENESS * dec(completeness)
    )
    return rhu2(raw)


def grade_from_score(score):
    score = dec(score)
    if score < REJECT_BELOW:
        return "REJECTED"
    if score >= GRADE_A_MIN:
        return "A"
    if score >= GRADE_B_MIN:
        return "B"
    if score >= GRADE_C_MIN:
        return "C"
    return "D"


# ---------------------------------------------------------------------------
# item_list_price -- two separately rounded steps, never collapsed
# ---------------------------------------------------------------------------
def item_list_price(declared_value_cents, condition_grade, category):
    if condition_grade not in GRADE_FACTOR:
        return None
    step1_cents = rhu(dec(declared_value_cents) * GRADE_FACTOR[condition_grade])
    return rhu(dec(step1_cents) * CATEGORY_FACTOR[category])


# ---------------------------------------------------------------------------
# lot_bundle_list_price
# ---------------------------------------------------------------------------
def lot_bundle_list_price(component_prices):
    component_sum = 0
    for price in component_prices:
        component_sum += int(price or 0)
    return rhu(dec(component_sum) * BUNDLE_FACTOR)


def worst_grade(grades):
    best = None
    for grade in grades:
        if grade is None:
            continue
        if best is None or GRADE_RANK.get(grade, 0) < GRADE_RANK.get(best, 0):
            best = grade
    return best


# ---------------------------------------------------------------------------
# markdown_price
# ---------------------------------------------------------------------------
def governing_step(steps, days_on_floor):
    """The LAST step whose start_day_offset <= days_on_floor."""
    chosen = None
    for step in sorted(steps, key=lambda s: s["sequence"]):
        if step["start_day_offset"] <= days_on_floor:
            chosen = step
    return chosen


def markdown_price(list_price_cents, step, discount_elected):
    """Returns (markdown_sequence, current_price_cents)."""
    if step is None:
        return None, None
    pct = dec(step["markdown_pct"])
    base = dec(list_price_cents) * (ONE - pct)
    if discount_elected:
        base = base * (ONE - DISCOUNT_ELECTION_EXTRA_PCT)
    stepped_cents = rhu(base)
    current = max(stepped_cents, int(step["min_price_cents"]))
    return int(step["sequence"]), current


# ---------------------------------------------------------------------------
# pickup_surcharge
# ---------------------------------------------------------------------------
def crew_bucket(crew_size):
    if crew_size <= 2:
        return "2"
    if crew_size == 3:
        return "3"
    return "4_PLUS"


def access_fee(stair_flights, elevator):
    if elevator:
        return ELEVATOR_FLAT_CENTS
    flights = int(stair_flights or 0)
    fee = min(flights, STAIR_FLIGHT_CAP) * STAIR_FLIGHT_CENTS
    if flights > STAIR_FLIGHT_CAP:
        fee += EXTREME_CLIMB_CENTS
    return fee


def pickup_surcharge(items, stair_flights, elevator, crew_size):
    total_volume = 0
    declared_total = 0
    bulky = 0
    for item in items:
        total_volume += int(item["volume_cuft"])
        declared_total += int(item["declared_value_cents"])
        if item["category"] in ("SOFA", "DINING") and int(item["volume_cuft"]) >= BULKY_VOLUME_CUFT:
            bulky += 1
    volume_fee = ceil_div(total_volume, VOLUME_BLOCK_CUFT) * VOLUME_BLOCK_CENTS
    bulky_fee = BULKY_ITEM_CENTS * bulky
    subtotal = BASE_CENTS + volume_fee + access_fee(stair_flights, elevator) + bulky_fee
    raw = rhu(dec(subtotal) * CREW_MULTIPLIER[crew_bucket(int(crew_size))])
    cap = rhu(CAP_PCT * dec(declared_total))
    return min(raw, cap)


# ---------------------------------------------------------------------------
# consignor_split
# ---------------------------------------------------------------------------
def price_bonus(sale_price_cents):
    if sale_price_cents < PRICE_BONUS_LOW_CENTS:
        return Decimal("0.00")
    if sale_price_cents < PRICE_BONUS_HIGH_CENTS:
        return Decimal("0.05")
    return Decimal("0.10")


def consignor_split(category, sale_price_cents, markdown_sequence):
    pct = CATEGORY_BASE[category] + price_bonus(int(sale_price_cents))
    if int(markdown_sequence or 0) >= TENURE_PENALTY_SEQUENCE:
        pct = pct - TENURE_PENALTY
    pct = min(max(pct, PCT_FLOOR), PCT_CEILING)
    consignor_share = rhu(dec(sale_price_cents) * pct)
    gallery_share = int(sale_price_cents) - consignor_share
    return pct, consignor_share, gallery_share


def sale_floor_cents(current_price_cents):
    return rhu(dec(current_price_cents or 0) * SALE_FLOOR_PCT)


# ---------------------------------------------------------------------------
# shrinkage_write_off
# ---------------------------------------------------------------------------
def shrinkage_credit(current_price_cents):
    return rhu(dec(current_price_cents or 0) * SHRINKAGE_CREDIT_PCT)


# ---------------------------------------------------------------------------
# payout_disbursement
# ---------------------------------------------------------------------------
def payout_disbursement(available_cents, payout_method):
    if available_cents < TIER_MID_CENTS:
        withholding_pct = Decimal("0.00")
    elif available_cents < TIER_HIGH_CENTS:
        withholding_pct = Decimal("0.02")
    else:
        withholding_pct = Decimal("0.03")
    withholding_cents = rhu(dec(available_cents) * withholding_pct)
    processing_fee_cents = METHOD_FEE[payout_method]
    net_payout_cents = int(available_cents) - withholding_cents - processing_fee_cents
    return withholding_cents, processing_fee_cents, net_payout_cents


# ---------------------------------------------------------------------------
# damage_allocation
# ---------------------------------------------------------------------------
def damage_allocation(claim_amount_cents, sale_price_cents, fault_party):
    adjudicated = min(int(claim_amount_cents), int(sale_price_cents))
    if fault_party in ("GALLERY", "BUYER"):
        return adjudicated, adjudicated, 0
    gallery_bucket = min(adjudicated, GALLERY_DEDUCTIBLE_CENTS)
    remainder = adjudicated - gallery_bucket
    if fault_party == "CONSIGNOR":
        consignor_debited = remainder
    else:
        consignor_debited = rhu(dec(remainder) * SHARED_FAULT_PCT)
    gallery_absorbed = adjudicated - consignor_debited
    return adjudicated, gallery_absorbed, consignor_debited


# ---------------------------------------------------------------------------
# delivery_fee
# ---------------------------------------------------------------------------
def delivery_fee(stair_flights, elevator_used, category):
    fee = BASE_DELIVERY_CENTS + access_fee(stair_flights, elevator_used)
    if category in ASSEMBLY_CATEGORIES:
        fee += ASSEMBLY_CENTS
    return fee


# ---------------------------------------------------------------------------
# floor_zone_utilization
# ---------------------------------------------------------------------------
def utilization_state(occupied_sqft, capacity_sqft):
    if not capacity_sqft:
        return "FULL" if occupied_sqft else "NORMAL"
    ratio = dec(occupied_sqft) / dec(capacity_sqft)
    if ratio >= FULL_RATIO:
        return "FULL"
    if ratio >= TIGHT_RATIO:
        return "TIGHT"
    return "NORMAL"
