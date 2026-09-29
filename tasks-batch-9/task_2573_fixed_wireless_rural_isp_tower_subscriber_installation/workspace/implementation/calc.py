"""The eight pinned calculations of PRD section 3.

Every quantity is carried as Decimal; every rounding step is applied exactly
where the PRD places it, because several pinned results differ from the naive
rounding order by one unit in the last place (PRD 2.9).
"""
from decimal import Decimal

from util import (
    add_days, add_years, ceil_steps, ceil_to_step, dec, floor_int, q1, q3,
    rhu_int, round_half_up, start_of_day, whole_days_between,
    whole_minutes_between,
)

# ---------------------------------------------------------------------------
# line-of-sight / mast constants (PRD 3.5)
# ---------------------------------------------------------------------------
SAFETY_MARGIN_M = Decimal("0.5")
MAST_STEP_M = Decimal("0.5")
MAX_MAST_HEIGHT_M = Decimal("12.0")
MAX_LINK_DISTANCE_KM = Decimal("15.0")
PARTIAL_OBSTRUCTION_EXTRA_M = Decimal("1.0")
QUALIFICATION_VALID_DAYS = 30

CLEARANCE_NEAR_KM = Decimal("3.0")
CLEARANCE_MID_KM = Decimal("8.0")
CLEARANCE_NEAR_M = Decimal("1.5")
CLEARANCE_MID_M = Decimal("3.0")
CLEARANCE_FAR_M = Decimal("4.5")

MOUNTING_WALL_BRACKET = "WALL_BRACKET"
MOUNTING_NON_PEN_ROOF_TRIPOD = "NON_PEN_ROOF_TRIPOD"
MOUNTING_ROOF_MAST_GUYED = "ROOF_MAST_GUYED"
MOUNTING_GROUND_POLE_MAST = "GROUND_POLE_MAST"

MOUNTING_CEILINGS = {
    MOUNTING_WALL_BRACKET: Decimal("1.0"),
    MOUNTING_NON_PEN_ROOF_TRIPOD: Decimal("3.0"),
    MOUNTING_ROOF_MAST_GUYED: Decimal("6.0"),
    MOUNTING_GROUND_POLE_MAST: Decimal("12.0"),
}
MOUNTING_TYPES = tuple(MOUNTING_CEILINGS.keys())
LIGHT_MOUNTINGS = (MOUNTING_WALL_BRACKET, MOUNTING_NON_PEN_ROOF_TRIPOD)
HEAVY_MOUNTINGS = (MOUNTING_ROOF_MAST_GUYED, MOUNTING_GROUND_POLE_MAST)

# ---------------------------------------------------------------------------
# capacity posture constants (PRD 3.3)
# ---------------------------------------------------------------------------
WATCH_FRACTION = Decimal("0.50")
HOLD_FRACTION = Decimal("0.75")
BACKHAUL_ESCALATION_RATIO = Decimal("12.0")
DEFAULT_MAX_OVERSUBSCRIPTION_RATIO = Decimal("8.0")

POSTURE_OPEN = "OPEN"
POSTURE_WATCH = "WATCH"
POSTURE_HOLD = "HOLD"
POSTURE_FROZEN = "FROZEN"

# ---------------------------------------------------------------------------
# reservation / negotiation / survey limits
# ---------------------------------------------------------------------------
DEFAULT_HOLD_DAYS = 14
MIN_HOLD_DAYS = 1
MAX_HOLD_DAYS = 30
AUTO_PROMOTION_HOLD_DAYS = 14

COORDINATION_ROUND_LIMIT = 3
MIN_AZIMUTH_SEPARATION_DEG = Decimal("60")

RESURVEY_LIMIT = 2

# ---------------------------------------------------------------------------
# usage cycle constants (PRD 3.8)
# ---------------------------------------------------------------------------
CYCLE_DAYS = 30
STICKY_BREACH_CYCLES = 2
MIN_EFFECTIVE_MBPS = Decimal("0.1")

# ---------------------------------------------------------------------------
# install invoice constants (PRD 3.7)
# ---------------------------------------------------------------------------
TRIP_CHARGE_CENTS = 9900
LABOR_CENTS = {
    MOUNTING_WALL_BRACKET: 4900,
    MOUNTING_NON_PEN_ROOF_TRIPOD: 9900,
    MOUNTING_ROOF_MAST_GUYED: 19900,
    MOUNTING_GROUND_POLE_MAST: 34900,
}
MAST_KIT_CENTS_PER_HALF_METRE = 1750
REG_RECOVERY_PCT = Decimal("0.0325")
PROMO_TIERS = ((30000, 5000), (20000, 3000), (10000, 1000))

# ---------------------------------------------------------------------------
# equipment settlement constants (PRD 3.8)
# ---------------------------------------------------------------------------
REPLACEMENT_COST_CENTS = 34900
RENTAL_MONTHLY_CENTS = 1000
PURCHASE_PRICE_CENTS = 29900
RENTAL_CREDIT_CAP_PCT = Decimal("0.60")
DAMAGE_CHARGE_PCT = Decimal("0.50")
DEPRECIATION_MONTHS = 36
RESTOCK_FEE_PCT = Decimal("0.15")
RETURN_WINDOW_DAYS = 21
DAYS_PER_SETTLEMENT_MONTH = 30

# ---------------------------------------------------------------------------
# outage credit constants (PRD 3.9)
# ---------------------------------------------------------------------------
SLA_MONTHLY_MINUTES = 43200
SHORTFALL_MULTIPLIER = 10
MAX_CREDIT_PCT_OF_MRC = Decimal("0.50")
MIN_CREDITABLE_MINUTES = 60
SEVERE_WIND_MPH = Decimal("58.0")
PLANNED_NOTICE_MIN_DAYS = 7


# ===========================================================================
# 1. tower_lease_escalation
# ===========================================================================
def lease_years_elapsed(lease_start_date, clock_now):
    """Anniversaries of lease_start_date at or before the clock (inclusive)."""
    years = 0
    while True:
        anniversary = add_years(lease_start_date, years + 1)
        if start_of_day(anniversary) <= clock_now:
            years += 1
        else:
            break
        if years > 1000:
            break
    return years


def lease_rent_series(base_cents, escalator_pct, count):
    """Rent for lease years 0..count, compounding on already-rounded cents."""
    series = [int(base_cents)]
    step = Decimal(1) + dec(escalator_pct)
    for _ in range(int(count)):
        series.append(rhu_int(dec(series[-1]) * step))
    return series


def lease_schedule(tower, clock_now):
    years = lease_years_elapsed(tower["lease_start_date"], clock_now)
    term_years = int(tower["lease_term_months"]) // 12
    needed = max(years, term_years - 1 if term_years > 0 else 0)
    series = lease_rent_series(tower["lease_monthly_base_rent_cents"],
                               tower["lease_escalator_pct"], needed)
    current = series[years]
    total = 0
    for y in range(term_years):
        total += series[y] * 12
    return {
        "years_elapsed": years,
        "current_monthly_rent_cents": current,
        "next_anniversary_date": add_years(tower["lease_start_date"], years + 1),
        "total_committed_cents": total,
    }


def current_monthly_rent_cents(tower, clock_now):
    return lease_schedule(tower, clock_now)["current_monthly_rent_cents"]


# ===========================================================================
# 2. los_qualification_mast_height
# ===========================================================================
def clearance_requirement_m(path_distance_km):
    distance = dec(path_distance_km)
    if distance <= CLEARANCE_NEAR_KM:
        return CLEARANCE_NEAR_M
    if distance <= CLEARANCE_MID_KM:
        return CLEARANCE_MID_M
    return CLEARANCE_FAR_M


def mounting_band_for(mast_height_m):
    height = dec(mast_height_m)
    for name in (MOUNTING_WALL_BRACKET, MOUNTING_NON_PEN_ROOF_TRIPOD,
                 MOUNTING_ROOF_MAST_GUYED, MOUNTING_GROUND_POLE_MAST):
        if height <= MOUNTING_CEILINGS[name]:
            return name
    return None


def los_geometry(tower_ground_elevation_m, tower_antenna_agl_m,
                 premise_ground_elevation_m, obstruction_height_m, roof_height_m,
                 obstruction_class, path_distance_km):
    """Shared clearance arithmetic of PRD 3.5 (desktop and field variants)."""
    tower_antenna_amsl = dec(tower_ground_elevation_m) + dec(tower_antenna_agl_m)
    obstruction_top_amsl = dec(premise_ground_elevation_m) + dec(obstruction_height_m)
    roof_amsl = dec(premise_ground_elevation_m) + dec(roof_height_m)

    clearance = clearance_requirement_m(path_distance_km)
    extra = PARTIAL_OBSTRUCTION_EXTRA_M if obstruction_class == "PARTIAL" else Decimal("0.0")

    required_antenna_amsl = obstruction_top_amsl + clearance + extra + SAFETY_MARGIN_M
    los_margin_m = q1(tower_antenna_amsl - required_antenna_amsl)

    raw_mast = required_antenna_amsl - roof_amsl
    if raw_mast < 0:
        raw_mast = Decimal("0.0")
    required_mast_m = q1(ceil_to_step(raw_mast, MAST_STEP_M))
    mounting_type = mounting_band_for(required_mast_m)
    return {
        "tower_antenna_amsl_m": tower_antenna_amsl,
        "obstruction_top_amsl_m": obstruction_top_amsl,
        "roof_amsl_m": roof_amsl,
        "clearance_m": clearance,
        "extra_m": extra,
        "required_antenna_amsl_m": required_antenna_amsl,
        "los_margin_m": los_margin_m,
        "required_mast_height_m": required_mast_m,
        "mounting_type": mounting_type,
    }


# ===========================================================================
# 3. sector_capacity_posture
# ===========================================================================
def oversubscription_ratio(committed_mbps, capacity_mbps):
    capacity = dec(capacity_mbps)
    if capacity <= 0:
        capacity = Decimal(1)
    return q3(dec(committed_mbps) / capacity)


def remaining_allowance_mbps(capacity_mbps, max_ratio, committed_mbps):
    ceiling = floor_int(dec(capacity_mbps) * dec(max_ratio))
    remaining = ceiling - int(committed_mbps)
    return remaining if remaining > 0 else 0


def capacity_posture(sector_status, tower_status, backhaul_accepted_mbps,
                     ratio, max_ratio, committed_mbps):
    if sector_status == "DISABLED" or tower_status == "DECOMMISSIONED":
        return POSTURE_FROZEN
    if int(backhaul_accepted_mbps) == 0:
        return POSTURE_FROZEN
    ceiling = dec(max_ratio)
    if dec(ratio) >= ceiling:
        return POSTURE_FROZEN
    if dec(ratio) >= HOLD_FRACTION * ceiling:
        provisional = POSTURE_HOLD
    elif dec(ratio) >= WATCH_FRACTION * ceiling:
        provisional = POSTURE_WATCH
    else:
        provisional = POSTURE_OPEN
    divisor = dec(backhaul_accepted_mbps)
    if divisor < 1:
        divisor = Decimal(1)
    transport_ratio = q3(dec(committed_mbps) / divisor)
    if transport_ratio >= BACKHAUL_ESCALATION_RATIO and provisional in (POSTURE_OPEN, POSTURE_WATCH):
        provisional = POSTURE_HOLD
    return provisional


# ===========================================================================
# 4. usage_cycle_deprioritization
# ===========================================================================
def cycle_window(cycle_start_date):
    if cycle_start_date is None:
        return None, None
    return cycle_start_date, add_days(cycle_start_date, CYCLE_DAYS)


def in_window(usage_date, cycle_start_date):
    start, end = cycle_window(cycle_start_date)
    if start is None:
        return False
    return start <= usage_date < end


def accumulate_cycle_usage(records):
    """Running total rounded half up to one decimal place after each record."""
    running = Decimal("0.0")
    for record in sorted(records, key=lambda r: (r["usage_date"], r["ingest_sequence"])):
        running = q1(running + dec(record["downstream_gb"]) + dec(record["upstream_gb"]))
    return q1(running)


def effective_downstream(plan, priority):
    downstream = dec(plan["downstream_mbps"])
    if priority != "DEPRIORITIZED":
        return downstream
    shaped = downstream * dec(plan["deprioritization_factor"])
    if shaped < MIN_EFFECTIVE_MBPS:
        shaped = MIN_EFFECTIVE_MBPS
    return q1(shaped)


# ===========================================================================
# 5. install_invoice_total
# ===========================================================================
def install_invoice_total_cents(approved_mounting_type, installed_mast_height_m):
    labor = LABOR_CENTS.get(approved_mounting_type, 0)
    sections = ceil_steps(installed_mast_height_m, MAST_STEP_M)
    mast_kit = MAST_KIT_CENTS_PER_HALF_METRE * sections
    subtotal = TRIP_CHARGE_CENTS + labor + mast_kit
    promo = 0
    for threshold, amount in PROMO_TIERS:
        if subtotal >= threshold:
            promo = amount
            break
    net = subtotal - promo
    fee = rhu_int(dec(net) * REG_RECOVERY_PCT)
    return {
        "labor_cents": labor,
        "mast_sections": sections,
        "mast_kit_cents": mast_kit,
        "subtotal_cents": subtotal,
        "promo_cents": promo,
        "net_cents": net,
        "regulatory_fee_cents": fee,
        "total_cents": net + fee,
    }


# ===========================================================================
# 6. equipment_settlement
# ===========================================================================
def months_in_service(deployed_at, settlement_instant):
    if deployed_at is None or settlement_instant is None:
        return 0
    days = whole_days_between(deployed_at, settlement_instant)
    if days < 0:
        return 0
    return days // DAYS_PER_SETTLEMENT_MONTH


def settle_equipment(assignment, outcome, months):
    """outcome is 'UNRETURNED' or 'RETURNED'."""
    mode = assignment["acquisition_mode"]
    replacement = int(assignment["replacement_cost_cents"])
    if mode == "RENTAL":
        if outcome == "UNRETURNED":
            cap = floor_int(dec(replacement) * RENTAL_CREDIT_CAP_PCT)
            credit = int(assignment["monthly_rental_cents"]) * int(months)
            if credit > cap:
                credit = cap
            return replacement - credit, "RENTAL_CREDIT_OFFSET"
        if assignment.get("return_condition") == "DAMAGED":
            return rhu_int(dec(replacement) * DAMAGE_CHARGE_PCT), "RENTAL_DAMAGE"
        return 0, "NONE"
    # PURCHASE
    if outcome == "UNRETURNED":
        return 0, "NONE"
    remaining = DEPRECIATION_MONTHS - int(months)
    if remaining < 0:
        remaining = 0
    residual = rhu_int(dec(assignment["purchase_price_cents"]) * Decimal(remaining)
                       / Decimal(DEPRECIATION_MONTHS))
    restock = rhu_int(dec(residual) * RESTOCK_FEE_PCT)
    return -(residual - restock), "DEPRECIATED_REFUND"


# ===========================================================================
# 7. outage credit helpers
# ===========================================================================
def outage_sla_excluded(cause, peak_wind_mph, planned_notice_days):
    if cause == "WEATHER_WIND":
        wind = dec(peak_wind_mph) if peak_wind_mph is not None else Decimal("0.0")
        return wind >= SEVERE_WIND_MPH
    if cause in ("WEATHER_ICE", "WEATHER_FLOOD"):
        return True
    if cause == "PLANNED_MAINTENANCE":
        notice = int(planned_notice_days) if planned_notice_days is not None else 0
        return notice >= PLANNED_NOTICE_MIN_DAYS
    return False


def clipped_minutes(outage, window_start, window_end):
    """Whole minutes of the outage's half-open interval inside the window."""
    if window_start is None or outage.get("ended_at") is None:
        return 0
    start = outage["started_at"]
    end = outage["ended_at"]
    lower = start if start > window_start else window_start
    upper = end if end < window_end else window_end
    if upper <= lower:
        return 0
    return whole_minutes_between(lower, upper)


def creditable_minutes(outage, window_start, window_end):
    if outage.get("sla_excluded"):
        return 0
    if outage.get("status") != "CLOSED":
        return 0
    minutes = clipped_minutes(outage, window_start, window_end)
    if minutes < MIN_CREDITABLE_MINUTES:
        return 0
    return minutes


def credit_cap_cents(monthly_price_cents):
    return floor_int(dec(monthly_price_cents) * MAX_CREDIT_PCT_OF_MRC)


def sla_shortfall_amounts(plan, cycle_outage_minutes):
    allowance = Decimal(SLA_MONTHLY_MINUTES)
    measured = q3(Decimal(100) * (allowance - Decimal(int(cycle_outage_minutes))) / allowance)
    shortfall = dec(plan["sla_uptime_pct"]) - measured
    if shortfall < 0:
        shortfall = Decimal("0")
    shortfall = q3(shortfall)
    gross = rhu_int(dec(plan["monthly_price_cents"]) * shortfall / Decimal(100)
                    * Decimal(SHORTFALL_MULTIPLIER))
    cap = credit_cap_cents(plan["monthly_price_cents"])
    if gross > cap:
        gross = cap
    return measured, shortfall, gross


def per_incident_amount(plan, minutes):
    gross = rhu_int(dec(plan["monthly_price_cents"]) * Decimal(int(minutes))
                    / Decimal(SLA_MONTHLY_MINUTES))
    cap = credit_cap_cents(plan["monthly_price_cents"])
    if gross > cap:
        gross = cap
    return gross


# ===========================================================================
# 8. guard-band geometry (PRD 3.4)
# ===========================================================================
def circular_separation_deg(azimuth_a, azimuth_b):
    separation = abs(dec(azimuth_a) - dec(azimuth_b))
    if separation > Decimal(180):
        separation = Decimal(360) - separation
    return separation


def guard_band_clear(requesting_azimuth, neighbor_azimuth, proposed_lower,
                     proposed_upper, guard_band_mhz, neighbor_lower, neighbor_upper):
    separation = circular_separation_deg(requesting_azimuth, neighbor_azimuth)
    if separation >= MIN_AZIMUTH_SEPARATION_DEG:
        return True
    guard = dec(guard_band_mhz)
    inflated_lower = dec(proposed_lower) - guard
    inflated_upper = dec(proposed_upper) + guard
    if inflated_upper <= dec(neighbor_lower):
        return True
    if inflated_lower >= dec(neighbor_upper):
        return True
    return False


def channel_edges(center_mhz, width_mhz):
    half = dec(width_mhz) / Decimal(2)
    return dec(center_mhz) - half, dec(center_mhz) + half
