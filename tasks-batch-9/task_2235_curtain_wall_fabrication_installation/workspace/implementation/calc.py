"""Deterministic calculations (SCAFFOLD.yaml §1.3 / PRD §2.7).

Every monetary or dimensional figure is derived with decimal.Decimal and
ROUND_HALF_UP.  Multi-element sums round per element and then add.
"""

from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal

# -- system_decision_labor_split -------------------------------------------
UNITIZED_SHOP_HOURS_PER_SQM = Decimal("0.55")
STICK_SHOP_HOURS_PER_SQM = Decimal("0.18")
UNITIZED_CREW_SIZE = 4
STICK_CREW_SIZE = 8

# -- zone_field_labor_cost -------------------------------------------------
UNITIZED_PANELS_PER_CREW_DAY = 12
STICK_PANELS_PER_CREW_DAY = 6
STANDARD_SHIFT_HOURS = Decimal("8.0")
OVERTIME_MULTIPLIER = Decimal("1.5")
HIGH_ELEVATION_FACTOR = Decimal("1.15")
HIGH_ELEVATION_THRESHOLD_M = Decimal("20.0")

# -- glass_procurement_risk_score -----------------------------------------
W_LEAD = Decimal("0.45")
W_CALENDAR = Decimal("0.35")
W_COATING = Decimal("0.20")
RE_FIRE_PENALTY_DAYS = 21
EXPEDITE_RECOVERY_DAYS = 10
NOMINAL_HORIZON_DAYS = 90
EXPEDITE_HORIZON_DAYS = 45
MAX_TOLERATED_REVISIONS = Decimal("2")
RISK_THRESHOLD = Decimal("70.00")

# -- thermal_movement_allowance_mm ----------------------------------------
THERMAL_COEFF_PER_C = Decimal("0.0000234")
SYSTEM_THERMAL_FACTOR = {"UNITIZED": Decimal("1.00"), "STICK_BUILT": Decimal("1.25")}
ANCHOR_THERMAL_FACTOR = {
    "SLOTTED": Decimal("1.30"),
    "PINNED": Decimal("1.15"),
    "FIXED": Decimal("1.00"),
}
HEIGHT_ADDEND_LOW = Decimal("0.00")
HEIGHT_ADDEND_MID = Decimal("1.50")
HEIGHT_ADDEND_HIGH = Decimal("3.00")
HEIGHT_BAND_LOW_M = Decimal("20.0")
HEIGHT_BAND_MID_M = Decimal("40.0")

# -- zone_deflection_limit_mm ---------------------------------------------
UNITIZED_DEFLECTION_DIVISOR = Decimal("240")
STICK_DEFLECTION_DIVISOR = Decimal("175")

# -- earned_value_certified_cents -----------------------------------------
WEATHER_TIGHT_MILESTONE_FACTOR = Decimal("0.95")
RETENTION_RATE = Decimal("0.05")

# -- mockup_test_invoice_cents --------------------------------------------
MOCKUP_BASE_FEE_CENTS = 480000
CHAMBER_HOUR_RATE_CENTS = 21500
RETEST_TIERS = (
    (600000, Decimal("0.02")),
    (800000, Decimal("0.04")),
    (2000000, Decimal("0.06")),
)
RETEST_TOP_RATE = Decimal("0.10")

# -- engineering_posture --------------------------------------------------
RESTRICTED_AT_OPEN_CRITICAL = 1
FROZEN_AT_OPEN_CRITICAL = 2

# -- glass_lite_ledger ----------------------------------------------------
BREAKAGE_STOCK_PCT = Decimal("0.03")
LITES_PER_PANEL = 2

# -- field test pass thresholds -------------------------------------------
AIR_LEAKAGE_LIMIT_CFM = Decimal("0.06")
MOCKUP_DEFLECTION_LIMIT_MM = Decimal("19.00")


def D(value):
    if isinstance(value, Decimal):
        return value
    if value is None:
        return Decimal(0)
    return Decimal(str(value))


def rhu(value, places=0):
    quantum = Decimal(1).scaleb(-places)
    return D(value).quantize(quantum, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(rhu(value, 0))


def ceil_int(value):
    return int(D(value).to_integral_value(rounding=ROUND_CEILING))


def floor_int(value):
    return int(D(value).to_integral_value(rounding=ROUND_FLOOR))


def clamp01(value):
    if value < 0:
        return Decimal(0)
    if value > 1:
        return Decimal(1)
    return value


# --------------------------------------------------------------------------
# 1. system_decision_labor_split
# --------------------------------------------------------------------------
def labor_split(system_type, total_area_sqm):
    if system_type == "UNITIZED":
        hours = D(total_area_sqm) * UNITIZED_SHOP_HOURS_PER_SQM
        crew = UNITIZED_CREW_SIZE
    else:
        hours = D(total_area_sqm) * STICK_SHOP_HOURS_PER_SQM
        crew = STICK_CREW_SIZE
    return rhu(hours, 2), crew


def panels_per_crew_day(system_type):
    return (
        UNITIZED_PANELS_PER_CREW_DAY
        if system_type == "UNITIZED"
        else STICK_PANELS_PER_CREW_DAY
    )


# --------------------------------------------------------------------------
# 2. zone_field_labor_cost
# --------------------------------------------------------------------------
def provisional_labor_cost_cents(
    system_type, planned_panel_count, planned_field_crew_size, base_rate_cents
):
    per_day = panels_per_crew_day(system_type)
    crew_days = ceil_int(D(planned_panel_count) / D(per_day))
    planned_hours = D(crew_days) * D(planned_field_crew_size) * STANDARD_SHIFT_HOURS
    return rhu_int(planned_hours * D(base_rate_cents))


def crew_day_hours(crew_size, shift_hours):
    hours = D(shift_hours)
    straight = D(crew_size) * min(hours, STANDARD_SHIFT_HOURS)
    overtime = D(crew_size) * max(hours - STANDARD_SHIFT_HOURS, Decimal(0))
    return straight, overtime


def crew_day_cost_cents(crew_size, shift_hours, base_rate_cents, zone_height_m):
    straight, overtime = crew_day_hours(crew_size, shift_hours)
    rate = D(base_rate_cents)
    base = straight * rate + overtime * rate * OVERTIME_MULTIPLIER
    factor = (
        HIGH_ELEVATION_FACTOR
        if D(zone_height_m) > HIGH_ELEVATION_THRESHOLD_M
        else Decimal("1.00")
    )
    return rhu_int(base * factor)


# --------------------------------------------------------------------------
# 3. glass_procurement_risk_score
# --------------------------------------------------------------------------
def risk_score(
    quoted_lead_time_days,
    coating_revision_count,
    expedite_tier,
    days_to_deadline,
):
    nominal = expedite_tier == 0 and coating_revision_count == 0
    variant = "NOMINAL" if nominal else "EXPEDITE_ADJUSTED"
    horizon = NOMINAL_HORIZON_DAYS if nominal else EXPEDITE_HORIZON_DAYS
    effective = (
        int(quoted_lead_time_days)
        + RE_FIRE_PENALTY_DAYS * int(coating_revision_count)
        - EXPEDITE_RECOVERY_DAYS * int(expedite_tier)
    )
    if effective < 0:
        effective = 0
    denominator = days_to_deadline if days_to_deadline >= 1 else 1
    lead_pressure = clamp01(D(effective) / D(denominator))
    float_days = int(days_to_deadline) - effective
    calendar_pressure = clamp01(Decimal(1) - D(float_days) / D(horizon))
    coating_pressure = clamp01(D(coating_revision_count) / MAX_TOLERATED_REVISIONS)
    score = rhu(
        Decimal(100)
        * (
            W_LEAD * lead_pressure
            + W_CALENDAR * calendar_pressure
            + W_COATING * coating_pressure
        ),
        2,
    )
    return score, effective, variant, score >= RISK_THRESHOLD


# --------------------------------------------------------------------------
# 4. thermal_movement_allowance_mm
# --------------------------------------------------------------------------
def thermal_movement_allowance_mm(
    system_type, anchor_type, span_mm, design_temp_delta_c, height_m
):
    if system_type not in SYSTEM_THERMAL_FACTOR:
        return None
    height = D(height_m)
    if height <= HEIGHT_BAND_LOW_M:
        addend = HEIGHT_ADDEND_LOW
    elif height <= HEIGHT_BAND_MID_M:
        addend = HEIGHT_ADDEND_MID
    else:
        addend = HEIGHT_ADDEND_HIGH
    value = (
        D(span_mm)
        * THERMAL_COEFF_PER_C
        * D(design_temp_delta_c)
        * SYSTEM_THERMAL_FACTOR[system_type]
        * ANCHOR_THERMAL_FACTOR.get(anchor_type, Decimal("1.00"))
    )
    return rhu(value + addend, 2)


# --------------------------------------------------------------------------
# 5. zone_deflection_limit_mm
# --------------------------------------------------------------------------
def deflection_limit_mm(system_type, span_mm):
    if system_type == "UNITIZED":
        divisor = UNITIZED_DEFLECTION_DIVISOR
    elif system_type == "STICK_BUILT":
        divisor = STICK_DEFLECTION_DIVISOR
    else:
        return None
    return rhu(D(span_mm) / divisor, 2)


# --------------------------------------------------------------------------
# 6. earned_value_certified_cents
# --------------------------------------------------------------------------
def certified_line_cents(area_sqm, unit_rate_cents_per_sqm):
    return rhu_int(
        D(area_sqm) * D(unit_rate_cents_per_sqm) * WEATHER_TIGHT_MILESTONE_FACTOR
    )


def retention_cents(subtotal_cents):
    return rhu_int(D(subtotal_cents) * RETENTION_RATE)


# --------------------------------------------------------------------------
# 7. mockup_test_invoice_cents
# --------------------------------------------------------------------------
def chamber_hours(window_start, window_end, chambers_required):
    seconds = D((window_end - window_start).total_seconds())
    elapsed = ceil_int(seconds / D(3600))
    return elapsed * int(chambers_required)


def mockup_invoice_cents(window_start, window_end, chambers_required, is_retest):
    hours = chamber_hours(window_start, window_end, chambers_required)
    subtotal = MOCKUP_BASE_FEE_CENTS + hours * CHAMBER_HOUR_RATE_CENTS
    if not is_retest:
        return hours, subtotal, 0, subtotal
    rate = RETEST_TOP_RATE
    for ceiling, tier_rate in RETEST_TIERS:
        if subtotal <= ceiling:
            rate = tier_rate
            break
    surcharge = rhu_int(D(subtotal) * rate)
    return hours, subtotal, surcharge, subtotal + surcharge


# --------------------------------------------------------------------------
# 9. glass_lite_ledger
# --------------------------------------------------------------------------
def breakage_stock_lites(received_lites):
    return floor_int(D(received_lites) * BREAKAGE_STOCK_PCT)
