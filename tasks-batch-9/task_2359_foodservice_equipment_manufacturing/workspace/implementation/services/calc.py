"""Constants and the eight calculations (PRD Section 2.6 and Section 3)."""
from decimal import Decimal, ROUND_HALF_UP

# --- certification posture -------------------------------------------------
SCOPE_ORDER = ("SANITATION", "GAS", "ELECTRICAL")
AGENCY_SCOPES = {
    "AGENCY_ALPHA": ("SANITATION",),
    "AGENCY_BETA": ("GAS", "ELECTRICAL"),
    "AGENCY_GAMMA": ("SANITATION", "GAS", "ELECTRICAL"),
}
AGENCY_CODES = ("AGENCY_ALPHA", "AGENCY_BETA", "AGENCY_GAMMA")
LISTING_TERM_DAYS = 365
MAX_LISTING_REVISIONS = 3

CATEGORIES = ("FRYER", "COMBI_OVEN", "GRIDDLE", "DISHWASHER", "HOLDING_CABINET")
ENERGY_TYPES = ("GAS", "ELECTRIC", "DUAL")
CONTROLS_PACKAGES = ("STANDARD_DIAL", "TOUCH_PRO", "CONNECT_PLUS")
BRANDING_KITS = ("NONE", "LOGO_BADGE", "FULL_WRAP")
OPTION_CODES = ("SPLIT_TANK", "HIGH_ALT", "LEFT_HINGE", "ENERGY_SAVER")

# --- configuration pricing -------------------------------------------------
OPTION_PCT = {
    "SPLIT_TANK": Decimal("0.075"),
    "HIGH_ALT": Decimal("0.0325"),
    "LEFT_HINGE": Decimal("0.015"),
    "ENERGY_SAVER": Decimal("0.0425"),
}
CONTROLS_UPLIFT_CENTS = {"STANDARD_DIAL": 0, "TOUCH_PRO": 185000, "CONNECT_PLUS": 340000}
BRANDING_KIT_CENTS = {"NONE": 0, "LOGO_BADGE": 42000, "FULL_WRAP": 156000}
VOLUME_TIERS = ((500, Decimal("0.12")), (200, Decimal("0.08")), (50, Decimal("0.04")))

# --- performance validation ------------------------------------------------
WINDOW_SIZE = 3
MIN_RUNS = 3
HOLD_TEMP_TOLERANCE_C = Decimal("2.0")
RETEST_LIMIT = 3

# --- delivery commitment ---------------------------------------------------
TRANSIT_DAYS = 7
AT_RISK_GRACE_DAYS = 3

# --- production ------------------------------------------------------------
CHANGEOVER_BUFFER_HOURS = 12
ENERGY_TYPE_MEMBERS = ("GAS", "ELECTRIC", "DUAL")

# --- connected fleet -------------------------------------------------------
FAULT_WEIGHT = 7
HEARTBEAT_WEIGHT = 3
FIRMWARE_CURRENT_BONUS = 5
INITIAL_FIRMWARE_VERSION = "1.0.0"
COVERAGE_TERM_DAYS = {"BASE": 365, "EXTENDED_PLUS": 730}
EXTENSION_TERM_DAYS = 365
GRACE_PERIOD_DAYS = 30
RESERVE_BY_TIER = {"BASE": 250000, "EXTENDED_PLUS": 600000}
EXTENSION_RESERVE_CENTS = 300000
SERVICE_TIERS = ("BASE", "EXTENDED_PLUS")
MAX_CONCURRENT_CAMPAIGNS_PER_MODEL = 2
COHORT_SIZE = {"CANARY": 3, "BROAD": 5}
COHORT_SCOPES = ("CANARY", "BROAD")
MIN_SUCCESS_RATE = Decimal("0.80")

# --- service network / warranty -------------------------------------------
MIN_CERTIFIED_TECHS_PER_MODEL = 2
MIN_TRAINING_HOURS = 24
PASS_SCORE = 80
CERT_TERM_DAYS = 730
PARTS_STOCKING_LEVELS = ("BASIC", "FULL")
PARTS_CAP_CENTS = 180000
LABOR_RATE_CENTS_BY_TIER = {"BASE": 9000, "EXTENDED_PLUS": 11000}


def dec(value):
    return Decimal(str(value))


def rhu_cents(amount):
    """Round half up to a whole cent."""
    return int(Decimal(amount).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round2(amount):
    return Decimal(amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def round4(amount):
    return Decimal(amount).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def required_scopes_for(energy_type):
    scopes = ["SANITATION"]
    if energy_type in ("GAS", "DUAL"):
        scopes.append("GAS")
    if energy_type in ("ELECTRIC", "DUAL"):
        scopes.append("ELECTRICAL")
    return scopes


def sort_scopes(scopes):
    return [s for s in SCOPE_ORDER if s in scopes]


def volume_discount_pct(contracted_unit_volume):
    for threshold, pct in VOLUME_TIERS:
        if contracted_unit_volume >= threshold:
            return pct
    return Decimal("0")


def configuration_prices(base_price_cents, option_codes, controls_package, branding_kit,
                         contracted_unit_volume):
    """Returns (indicative_unit_price_cents, firm_unit_price_cents) (PRD Section 3.3)."""
    base = Decimal(int(base_price_cents))
    option_uplift = 0
    for code in OPTION_CODES:  # fixed order, each contribution rounded independently
        if code in option_codes:
            option_uplift += rhu_cents(base * OPTION_PCT[code])
    controls_uplift = CONTROLS_UPLIFT_CENTS[controls_package]
    discountable_subtotal = int(base) + option_uplift + controls_uplift
    pct = volume_discount_pct(contracted_unit_volume)
    discount = rhu_cents(Decimal(discountable_subtotal) * pct)
    discounted = discountable_subtotal - discount
    branding = BRANDING_KIT_CENTS[branding_kit]
    return discounted, discounted + branding


def measured_throughput(test_runs):
    """Returns (certified, as_tested) as Decimals rounded to 2dp (PRD Section 3.4)."""
    runs = sorted(test_runs, key=lambda r: r["run_index"])
    total_units = sum(dec(r["units_produced"]) for r in runs)
    total_minutes = sum(dec(r["minutes"]) for r in runs)
    as_tested = round2(total_units * 60 / total_minutes)
    best = None
    for i in range(0, len(runs) - WINDOW_SIZE + 1):
        window = runs[i:i + WINDOW_SIZE]
        units = sum(dec(r["units_produced"]) for r in window)
        minutes = sum(dec(r["minutes"]) for r in window)
        rate = units * 60 / minutes
        if best is None or rate > best:
            best = rate
    certified = round2(best) if best is not None else None
    return certified, as_tested


def hold_temp_within_tolerance(test_runs, hold_temp_target_c):
    target = dec(hold_temp_target_c)
    for run in test_runs:
        if abs(dec(run["hold_temp_c"]) - target) > HOLD_TEMP_TOLERANCE_C:
            return False
    return True


def coinsurance_for(claims_paid_cents, reserve_initial_cents):
    """Exact rational utilisation bands, lower bounds inclusive (PRD Section 3.9)."""
    if reserve_initial_cents <= 0:
        utilisation = Decimal("0")
    else:
        utilisation = Decimal(int(claims_paid_cents)) / Decimal(int(reserve_initial_cents))
    if utilisation < Decimal("0.60"):
        return Decimal("0.00")
    if utilisation < Decimal("0.85"):
        return Decimal("0.10")
    return Decimal("0.25")


def adjudicated_amount(parts_cost_cents, labor_hours, service_tier, coinsurance_pct):
    covered_parts = min(int(parts_cost_cents), PARTS_CAP_CENTS)
    labor = rhu_cents(dec(labor_hours) * Decimal(LABOR_RATE_CENTS_BY_TIER[service_tier]))
    gross = covered_parts + labor
    withheld = rhu_cents(Decimal(gross) * coinsurance_pct)
    return gross - withheld


def span_days(window_start, window_end):
    """Closed-interval span in days: floor(day difference) + 1."""
    from timeutil import floor_day_diff
    return floor_day_diff(window_end, window_start) + 1
