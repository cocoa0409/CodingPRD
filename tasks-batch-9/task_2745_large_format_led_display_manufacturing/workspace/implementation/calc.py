"""Pinned constants and calculations (SCAFFOLD section 1.3 / PRD sections 2.5, 3)."""

from decimal import Decimal
from fractions import Fraction

from numeric import (ceil_frac, floor_frac, round_half_up, round_half_up_int,
                     to_fraction)

# --- model_geometry_derivation ---------------------------------------------
VIEWING_DISTANCE_FACTOR_M_PER_MM = Fraction(1)
MIN_WIND_LOAD_KPH = {"STADIUM": 160, "ROADSIDE": 200, "RETAIL": 100}

# --- project_contract_amount_cents ----------------------------------------
ENV_SURCHARGE_PCT = {
    "STADIUM": Fraction(12, 100),
    "ROADSIDE": Fraction(18, 100),
    "RETAIL": Fraction(5, 100),
}
REDUNDANCY_SURCHARGE_PCT = {
    "NONE": Fraction(0),
    "HOT_BACKUP": Fraction(6, 100),
    "DUAL_LINK": Fraction(9, 100),
    "RING": Fraction(14, 100),
}

# --- project_data_load_pct ------------------------------------------------
REDUNDANCY_DERATE_FACTOR = {
    "NONE": Fraction(1),
    "HOT_BACKUP": Fraction(1, 2),
    "DUAL_LINK": Fraction(1, 2),
    "RING": Fraction(3, 4),
}
PLAYER_THROUGHPUT_MBPS = 2500
MAX_DATA_LOAD_PCT = Fraction(100)

# --- module_color_bin_assignment ------------------------------------------
CHROMA_A_BIN_TOLERANCE = Fraction(3, 1000)
CHROMA_CALIBRATED_TOLERANCE = Fraction(8, 1000)
CHROMA_REWORK_TOLERANCE = Fraction(20, 1000)
BRIGHTNESS_BIN_1_FRACTION = Fraction(96, 100)
COLOR_BIN_RANKS = {"A1": 0, "A2": 1, "B1": 2, "B2": 3}

# --- burn-in / on-site acceptance floors ----------------------------------
BURN_IN_MIN_BRIGHTNESS_NITS = 4800
BURN_IN_MIN_UNIFORMITY_PCT = Fraction(92)
ON_SITE_BRIGHTNESS_FLOOR_FRACTION = Fraction(95, 100)
ON_SITE_MIN_UNIFORMITY_PCT = Fraction(90)

# --- cabinet_uniformity_score --------------------------------------------
UNIFORMITY_BRIGHTNESS_WEIGHT = Fraction(15, 10)
UNIFORMITY_CHROMA_WEIGHT = Fraction(2000)
MIN_MODULES_FOR_SCORE = 2

# --- service contract -----------------------------------------------------
TIER_MIN_SPARE_PCT_BP = {"BRONZE": 100, "SILVER": 200, "GOLD": 300}
TIER_RATE_CENTS_PER_SQM = {"BRONZE": 120000, "SILVER": 190000, "GOLD": 268000}
SPARE_CARRY_FEE_CENTS = 4500
DISCOUNT_BREAK_1_CENTS = 2000000
DISCOUNT_BREAK_2_CENTS = 5000000
DISCOUNT_BREAK_3_CENTS = 10000000
TIER_RESPONSE_HOURS = {"BRONZE": 48, "SILVER": 24, "GOLD": 8}
SEVERITY_RESPONSE_MULTIPLIER = {
    "CRITICAL": Fraction(1, 2),
    "MAJOR": Fraction(1),
    "MINOR": Fraction(2),
}
MAX_SLA_BREACHES = 2

# --- warranty credit ------------------------------------------------------
WARRANTY_TERM_MONTHS = 60
GUARANTEED_DEGRADATION_PCT = 50
SEVERITY_CREDIT_MULTIPLIER = Fraction(25, 10)
MAX_CREDIT_FRACTION = Fraction(6, 10)
DAYS_PER_WARRANTY_MONTH = 30

# --- selectors ------------------------------------------------------------
COLOR_BIN_RANK_TOLERANCE = 1

# --- rework ---------------------------------------------------------------
MAX_REWORK_CYCLES = 2

# --- enum vocabularies ----------------------------------------------------
ENVIRONMENTAL_RATINGS = ("IP65_FRONT_IP54_REAR", "IP65_FULL", "IP43_INDOOR")
INSTALL_ENVIRONMENTS = ("STADIUM", "ROADSIDE", "RETAIL")
REDUNDANCY_MODES = ("NONE", "HOT_BACKUP", "DUAL_LINK", "RING")
CERTIFICATION_LEVELS = ("L1", "L2", "L3")
MOUNTING_TYPES = ("WALL", "FREESTANDING", "ROOF", "GANTRY")
SERVICE_ACCESS_SIDES = ("FRONT", "REAR")
ENGINEERING_STATES = ("DRAFT", "UNDER_REVIEW", "REJECTED", "APPROVED")
PRODUCTION_STATES = ("NOT_STARTED", "IN_ASSEMBLY", "QA_COMPLETE", "INSTALLED",
                     "COMMISSIONED", "BLOCKED")
REVISION_STATES = ("SUBMITTED", "APPROVED", "REJECTED")
CABINET_STATES = ("PLANNED", "IN_ASSEMBLY", "POPULATED", "BURN_IN",
                  "BURN_IN_PASSED", "QA_PASSED", "MOUNTED", "QUARANTINED")
MODULE_STATES = ("MANUFACTURED", "PIXEL_TESTED", "CALIBRATED", "REWORK",
                 "INSTALLED", "RETURNED", "SCRAPPED")
COLOR_BINS = ("A1", "A2", "B1", "B2")
RUN_STATES = ("SCHEDULED", "PASSED", "FAILED", "ABORTED")
VISIT_STATES = ("SCHEDULED", "ON_SITE", "CALIBRATED", "SIGNED_OFF", "ABORTED")
TIERS = ("BRONZE", "SILVER", "GOLD")
CONTRACT_STATES = ("PENDING", "ACTIVE", "SUSPENDED")
CASE_TYPES = ("MODULE_FAULT", "BRIGHTNESS_DEGRADATION")
SEVERITIES = ("CRITICAL", "MAJOR", "MINOR")
CASE_STATES = ("OPEN", "RESPONDED", "APPROVED", "DENIED", "FULFILLED")
ASSESSMENT_BASES = ("PRO_RATA_REMAINING_TERM", "SHORTFALL_SEVERITY")


# =========================================================================
# Model geometry
# =========================================================================
def model_geometry(payload):
    """Return the computed geometry fields for a DisplayModel payload."""
    module_area = round_half_up(
        Fraction(payload["module_width_mm"] * payload["module_height_mm"], 1000000), 4)
    cabinet_area = round_half_up(
        Fraction(payload["cabinet_width_mm"] * payload["cabinet_height_mm"], 1000000), 4)
    module_pixel_count = payload["module_pixel_cols"] * payload["module_pixel_rows"]
    cabinet_pixel_count = payload["modules_per_cabinet"] * module_pixel_count
    viewing = round_half_up(
        to_fraction(payload["pixel_pitch_mm"]) * VIEWING_DISTANCE_FACTOR_M_PER_MM, 1)
    required_load = round_half_up(
        to_fraction(payload["cabinet_weight_kg"]) / to_fraction(cabinet_area), 2)
    return {
        "module_area_sqm": module_area,
        "cabinet_area_sqm": cabinet_area,
        "module_pixel_count": module_pixel_count,
        "cabinet_pixel_count": cabinet_pixel_count,
        "recommended_min_viewing_distance_m": viewing,
        "required_load_kg_per_sqm": required_load,
    }


# =========================================================================
# Project pricing and bandwidth
# =========================================================================
def contract_amount_cents(model, install_environment, redundancy_mode, cabinet_count):
    exact = to_fraction(model["cabinet_area_sqm"]) * model["price_per_sqm_cents"]
    multiplier = (Fraction(1) + ENV_SURCHARGE_PCT[install_environment]
                  + REDUNDANCY_SURCHARGE_PCT[redundancy_mode])
    cabinet_line = round_half_up_int(exact * multiplier)
    return cabinet_line * cabinet_count


def data_load(model, project_inputs, cabinet_count):
    total_pixels = cabinet_count * model["cabinet_pixel_count"]
    required = ceil_frac(Fraction(
        total_pixels * project_inputs["color_depth_bits"] * 3
        * project_inputs["refresh_rate_hz"], 1000000))
    port_capacity = floor_frac(
        Fraction(project_inputs["output_port_count"] * project_inputs["port_bandwidth_mbps"])
        * REDUNDANCY_DERATE_FACTOR[project_inputs["redundancy_mode"]])
    player_capacity = project_inputs["player_count"] * PLAYER_THROUGHPUT_MBPS
    effective = min(port_capacity, player_capacity)
    if effective <= 0:
        return required, effective, None
    pct = round_half_up(Fraction(required, effective) * 100, 2)
    return required, effective, pct


# =========================================================================
# Module colour bin
# =========================================================================
def chroma_error(measured_x, measured_y, model):
    dx = abs(to_fraction(measured_x) - to_fraction(model["reference_color_x"]))
    dy = abs(to_fraction(measured_y) - to_fraction(model["reference_color_y"]))
    return max(dx, dy)


def color_bin_for(err, measured_brightness, model):
    letter = "A" if err <= CHROMA_A_BIN_TOLERANCE else "B"
    floor_nits = ceil_frac(
        Fraction(model["rated_brightness_nits"]) * BRIGHTNESS_BIN_1_FRACTION)
    digit = "1" if measured_brightness >= floor_nits else "2"
    return letter + digit


# =========================================================================
# Cabinet quality aggregates
# =========================================================================
def dead_pixel_ppm(total_dead, cabinet_pixel_count):
    return round_half_up(Fraction(total_dead * 1000000, cabinet_pixel_count), 2)


def uniformity_score(samples):
    """samples: list of (brightness_nits, color_x, color_y). None if < 2 samples."""
    if len(samples) < MIN_MODULES_FOR_SCORE:
        return None
    brightness = [to_fraction(s[0]) for s in samples]
    xs = [to_fraction(s[1]) for s in samples]
    ys = [to_fraction(s[2]) for s in samples]
    mean = sum(brightness) / len(brightness)
    if mean == 0:
        return None
    spread = round_half_up((max(brightness) - min(brightness)) / mean * 100, 4)
    chroma = round_half_up((max(xs) - min(xs)) + (max(ys) - min(ys)), 6)
    score = round_half_up(Fraction(100)
                          - UNIFORMITY_BRIGHTNESS_WEIGHT * to_fraction(spread)
                          - UNIFORMITY_CHROMA_WEIGHT * to_fraction(chroma), 2)
    if score < 0:
        score = Decimal("0.00")
    return score


# =========================================================================
# Service contract fees
# =========================================================================
def spare_required_count(module_count, spare_pct_bp):
    return ceil_frac(Fraction(module_count * spare_pct_bp, 10000))


def annual_fee(total_area_sqm, tier, spares):
    gross = round_half_up_int(to_fraction(total_area_sqm) * TIER_RATE_CENTS_PER_SQM[tier])
    spare_carry = spares * SPARE_CARRY_FEE_CENTS
    subtotal = gross + spare_carry
    if subtotal < DISCOUNT_BREAK_1_CENTS:
        pct = Fraction(0)
    elif subtotal < DISCOUNT_BREAK_2_CENTS:
        pct = Fraction(4, 100)
    elif subtotal < DISCOUNT_BREAK_3_CENTS:
        pct = Fraction(7, 100)
    else:
        pct = Fraction(10, 100)
    discount = round_half_up_int(Fraction(subtotal) * pct)
    return {
        "gross_fee_cents": gross,
        "subtotal_fee_cents": subtotal,
        "volume_discount_pct": round_half_up(pct, 2),
        "annual_fee_cents": subtotal - discount,
    }


# =========================================================================
# Warranty credit
# =========================================================================
def cabinet_value_cents(model):
    return round_half_up_int(
        to_fraction(model["cabinet_area_sqm"]) * model["price_per_sqm_cents"])


def elapsed_warranty_months(seconds):
    if seconds < 0:
        seconds = 0
    days = seconds // 86400
    return days // DAYS_PER_WARRANTY_MONTH


def degradation_figures(model, measured_brightness, months):
    allowed = round_half_up(
        Fraction(GUARANTEED_DEGRADATION_PCT * months, WARRANTY_TERM_MONTHS), 2)
    rated = model["rated_brightness_nits"]
    degradation = round_half_up(
        Fraction(rated - measured_brightness, rated) * 100, 2)
    shortfall = round_half_up(to_fraction(degradation) - to_fraction(allowed), 2)
    if shortfall < 0:
        shortfall = Decimal("0.00")
    return allowed, degradation, shortfall


def credit_cents(basis, value_cents, months, shortfall_pct):
    if basis == "PRO_RATA_REMAINING_TERM":
        return round_half_up_int(
            Fraction(value_cents * (WARRANTY_TERM_MONTHS - months), WARRANTY_TERM_MONTHS))
    fraction = min(to_fraction(shortfall_pct) / 100 * SEVERITY_CREDIT_MULTIPLIER,
                   MAX_CREDIT_FRACTION)
    return round_half_up_int(Fraction(value_cents) * fraction)
