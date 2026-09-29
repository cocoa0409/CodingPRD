"""The ten pinned calculations. Integer cents, half-up rounding, per-item rounding first."""
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

DEPOSIT_CENTS = 10
ANON_VISIT_CEILING = 144
CENTER_MACHINE_CEILING = 240
CENTER_HAND_CEILING = 50
DEFAULT_RETAILER_CAP = 350
PROVISIONAL_UNIT_CAP = 250
PROVISIONAL_RATE_CENTS = 8
BAG_SERVICE_FEE_CENTS = 50
SHRINK_RATE = Decimal("0.02")
OUT_OF_STATE_THRESHOLD = Decimal("0.1")
VARIANCE_THRESHOLD = Decimal("0.1")
FREIGHT_CENTS_PER_TONNE = Decimal("4500")
INDEX_FACTOR = Decimal("0.9750")
CONTAMINATION_LIMIT = Decimal("0.05")
EXEMPTION_RADIUS_MILES = Decimal("3.50")

BEVERAGE_TYPES = (
    "WATER", "FLAVORED_WATER", "BEER", "MALT_BEVERAGE", "CARBONATED_SOFT_DRINK",
    "HARD_CIDER", "KOMBUCHA", "ENERGY_DRINK", "RTD_COFFEE_TEA", "FRUIT_JUICE",
    "WINE", "DISTILLED_SPIRITS", "MILK", "INFANT_FORMULA", "MEAL_REPLACEMENT",
    "VEGETABLE_JUICE",
)
COVERED_BEVERAGE_TYPES = (
    "WATER", "FLAVORED_WATER", "BEER", "MALT_BEVERAGE", "CARBONATED_SOFT_DRINK",
    "HARD_CIDER", "KOMBUCHA", "ENERGY_DRINK", "RTD_COFFEE_TEA", "FRUIT_JUICE",
)
CONTAINER_MATERIALS = (
    "ALUMINUM", "GLASS", "PET_PLASTIC", "HDPE_PLASTIC", "POUCH", "ASEPTIC_BOX",
    "PAPER_CARTON",
)
COVERED_MATERIALS = ("ALUMINUM", "GLASS", "PET_PLASTIC", "HDPE_PLASTIC")
MIN_FILL_ML = 118
MAX_FILL_ML = 3000


def D(value):
    return Decimal(str(value))


def round_to(value, places):
    exp = Decimal(1).scaleb(-places)
    return D(value).quantize(exp, rounding=ROUND_HALF_UP)


def to_cents(value):
    return int(D(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def ceil_int(value):
    return int(D(value).to_integral_value(rounding=ROUND_CEILING))


def ratio_4dp(numerator, denominator):
    """Rounded to 4 decimal places; 0 when the denominator is 0."""
    if not denominator:
        return Decimal("0.0000")
    return round_to(D(numerator) / D(denominator), 4)


# --- 1. container coverage and deposit -------------------------------------

def coverage(beverage_type, container_material, fill_volume_ml):
    if beverage_type not in COVERED_BEVERAGE_TYPES:
        return "NOT_COVERED", "EXCLUDED_BEVERAGE_TYPE", 0
    if container_material not in COVERED_MATERIALS:
        return "NOT_COVERED", "EXCLUDED_MATERIAL", 0
    if fill_volume_ml < MIN_FILL_ML or fill_volume_ml > MAX_FILL_ML:
        return "NOT_COVERED", "VOLUME_OUT_OF_RANGE", 0
    return "COVERED", "COVERED_STANDARD", DEPOSIT_CENTS


# --- 2. retailer daily limit ----------------------------------------------

def retailer_daily_limit(store_area_sqft):
    return 50 if store_area_sqft >= 5000 else 24


# --- 3. per-visit ceiling -------------------------------------------------

def visit_base_ceiling(site_type, channel, retailer_daily_limit_containers):
    if site_type == "RETAILER":
        return int(retailer_daily_limit_containers or 0)
    if channel == "MACHINE_COUNT":
        return CENTER_MACHINE_CEILING
    return CENTER_HAND_CEILING


def visit_limit(base_ceiling, has_account):
    if has_account:
        return int(base_ceiling)
    return min(int(base_ceiling), ANON_VISIT_CEILING)


# --- 4. shrink ------------------------------------------------------------

def shrink_adjustment(capped_count, channel):
    if channel != "HAND_COUNT":
        return 0
    return ceil_int(D(capped_count) * SHRINK_RATE)


# --- 5. bag-drop provisional credit --------------------------------------

def provisional_credit(declared_count):
    units = min(int(declared_count), PROVISIONAL_UNIT_CAP)
    return units, units * PROVISIONAL_RATE_CENTS


# --- 6. bag-drop final valuation -----------------------------------------

def bag_final(counted_quantities, declared_count, provisional_credit_cents):
    counted_lines = len(counted_quantities)
    counted_total = sum(counted_quantities)
    gross_final = counted_total * DEPOSIT_CENTS
    final_credit = max(0, gross_final - BAG_SERVICE_FEE_CENTS)
    adjustment = final_credit - provisional_credit_cents
    variance = ratio_4dp(counted_total - declared_count, declared_count)
    flag = abs(variance) > VARIANCE_THRESHOLD
    return {
        "counted_lines": counted_lines,
        "counted_total": counted_total,
        "gross_final_cents": gross_final,
        "final_credit_cents": final_credit,
        "adjustment_cents": adjustment,
        "variance_pct": float(variance),
        "variance_flag": flag,
    }


# --- 7. material sale revenue --------------------------------------------

def gross_weight(bale_weights_kg):
    total = sum((D(w) for w in bale_weights_kg), Decimal("0"))
    return round_to(total, 2)


def material_sale(bale_weights_kg, gross_weight_kg, contamination_pct,
                  pricing_mode, quoted_price_cents_per_tonne):
    quoted = D(quoted_price_cents_per_tonne)
    if pricing_mode == "INDEX":
        effective = to_cents(quoted * INDEX_FACTOR)
    else:
        effective = int(quoted)
    clean = Decimal("1") - D(contamination_pct)
    gross = 0
    for weight in bale_weights_kg:
        tonnes = D(weight) / Decimal("1000")
        gross += to_cents(tonnes * D(effective) * clean)
    freight = to_cents(D(gross_weight_kg) / Decimal("1000") * FREIGHT_CENTS_PER_TONNE)
    net = max(0, gross - freight)
    return {
        "effective_price_cents_per_tonne": effective,
        "gross_revenue_cents": gross,
        "freight_cents": freight,
        "net_revenue_cents": net,
    }


# --- 8. handling fee ------------------------------------------------------

def handling_fee(containers_redeemed_count):
    n = int(containers_redeemed_count)
    if n < 0:
        n = 0
    fee = 3 * min(n, 50000)
    fee += 2 * max(0, min(n, 150000) - 50000)
    fee += 1 * max(0, n - 150000)
    return fee


# --- 9. funding settlement -----------------------------------------------

def funding_settlement(deposits_initiated_cents, redemptions_paid_cents,
                       material_revenue_cents, containers_redeemed_count,
                       operating_cost_cents):
    fee = handling_fee(containers_redeemed_count)
    gross_unredeemed = max(0, deposits_initiated_cents - redemptions_paid_cents)
    admin_shortfall = max(0, operating_cost_cents + fee - material_revenue_cents)
    sweep = min(gross_unredeemed, admin_shortfall)
    unredeemed = gross_unredeemed - sweep
    balance = material_revenue_cents + sweep - operating_cost_cents - fee
    status = "SURPLUS" if balance >= 0 else "SHORTFALL"
    return {
        "handling_fee_cents": fee,
        "gross_unredeemed_cents": gross_unredeemed,
        "admin_shortfall_cents": admin_shortfall,
        "sweep_to_funding_cents": sweep,
        "unredeemed_deposit_cents": unredeemed,
        "funding_balance_cents": balance,
        "funding_status": status,
    }


# --- 10. exemption distance ---------------------------------------------

def planar_distance(x1, y1, x2, y2):
    dx = D(x1) - D(x2)
    dy = D(y1) - D(y2)
    return round_to((dx * dx + dy * dy).sqrt(), 2)
