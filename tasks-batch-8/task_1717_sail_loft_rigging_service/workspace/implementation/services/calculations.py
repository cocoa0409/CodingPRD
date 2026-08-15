"""Calculation rules from scaffold §1.3. All money in integer cents via Decimal."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

# --- Constants from the scaffold ---
CLOTH_PRICE_PER_SQM_CENTS = {
    "CRUISE": 4200,
    "PERFORMANCE": 6800,
    "RACE": 9500,
    "GRAND_PRIX": 14000,
}
OPTION_PRICE = {
    "BATTENS": 18000,
    "REEF_POINTS": 12000,
    "UV_STRIP": 9000,
    "NUMBERS": 4000,
    "LOGO": 6000,
}
CLASS_COMPLEXITY = {
    "NONE": Decimal("1.00"),
    "PHRF": Decimal("1.00"),
    "ORC": Decimal("1.05"),
    "J70": Decimal("1.05"),
    "J105": Decimal("1.08"),
    "TP52": Decimal("1.15"),
}
HEAVY_DUTY_AREA_THRESHOLD = Decimal("150.00")
HEAVY_DUTY_SURCHARGE_PCT = Decimal("0.04")

MANDATORY_REPLACEMENT_MONTHS = 120
RUNNING_REPLACEMENT_HOURS = 2000

WASH_ITEM_PRICE = {
    "MAIN_WASH": 14550,
    "GENOA_WASH": 12350,
    "SPINNAKER_WASH": 9875,
    "RIG_WASH": 21000,
}
SEASON_BASE_UNDER_10M = 180000
SEASON_BASE_10M_TO_15M = 260000
SEASON_BASE_OVER_15M = 390000

BAY_TURNAROUND_GAP_DAYS = 1

CENT = Decimal("1")
TWO_PLACES = Decimal("0.01")


def _dec(v):
    return Decimal(str(v))


def sail_area(i_height_m, j_base_m, p_main_m, e_main_m):
    """0.5*P*E + 0.5*I*J, rounded half-up to 2 decimal places."""
    mainsail = Decimal("0.5") * _dec(p_main_m) * _dec(e_main_m)
    foretriangle = Decimal("0.5") * _dec(i_height_m) * _dec(j_base_m)
    area = (mainsail + foretriangle).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    return float(area)


def sail_price_provisional(design, sheet, boat):
    """Provisional quote at lock-design. Returns integer cents."""
    area = _dec(sheet["measured_area_sqm"])
    base = area * CLOTH_PRICE_PER_SQM_CENTS[design["cloth_tier"]]
    if area > HEAVY_DUTY_AREA_THRESHOLD:
        base = base * (Decimal("1") + HEAVY_DUTY_SURCHARGE_PCT * design["reinforcement_level"])
    options_total = sum(OPTION_PRICE[c] for c in design.get("option_codes", []))
    complexity = CLASS_COMPLEXITY[boat["racing_class"]]
    total = (base + Decimal(options_total)) * complexity
    return int(total.quantize(CENT, rounding=ROUND_HALF_UP))


def final_invoice(work_order, design, qc_passed_jobs, fitted_option_codes):
    """Chronological final invoice at confirm-delivery. Returns integer cents.

    jobs: QC_PASSED ProductionJobs for the work order, pre-sorted by
    (scheduled_start_date ASC, created_at ASC).
    """
    price = CLOTH_PRICE_PER_SQM_CENTS[design["cloth_tier"]]
    subtotal = Decimal("0")
    for job in qc_passed_jobs:
        subtotal += _dec(job["reserved_cloth_sqm"]) * price
    fitted_total = sum(OPTION_PRICE[c] for c in (fitted_option_codes or []))
    total = subtotal + Decimal(fitted_total)
    return int(total.quantize(CENT, rounding=ROUND_HALF_UP))


def whole_months_between(start_dt, end_dt):
    """Whole calendar months between two datetimes (anniversary-day aware)."""
    months = (end_dt.year - start_dt.year) * 12 + (end_dt.month - start_dt.month)
    if end_dt.day < start_dt.day:
        months -= 1
    return months


def add_months(start_dt, months):
    """Add calendar months, clamping day to end of target month."""
    y = start_dt.year + (start_dt.month - 1 + months) // 12
    m = (start_dt.month - 1 + months) % 12 + 1
    # Clamp day
    if m == 12:
        next_month = datetime(y + 1, 1, 1, tzinfo=start_dt.tzinfo)
    else:
        next_month = datetime(y, m + 1, 1, tzinfo=start_dt.tzinfo)
    last_day = (next_month - timedelta(days=1)).day
    d = min(start_dt.day, last_day)
    return start_dt.replace(year=y, month=m, day=d)


def storage_fee(wash_item_codes, hull_length_m):
    """Per-item round-half-up FIRST, then sum, then add the tier base."""
    per_item = [
        int(Decimal(WASH_ITEM_PRICE[c]).quantize(CENT, rounding=ROUND_HALF_UP))
        for c in (wash_item_codes or [])
    ]
    items_total = sum(per_item)
    hull = _dec(hull_length_m)
    if hull < Decimal("10"):
        season_base = SEASON_BASE_UNDER_10M
    elif hull <= Decimal("15"):
        season_base = SEASON_BASE_10M_TO_15M
    else:
        season_base = SEASON_BASE_OVER_15M
    return season_base + items_total


def bay_windows_conflict(start1, end1, start2, end2):
    """Closed-interval + 1-day-turnaround on (bay_code, [start, end] inclusive)."""
    gap = timedelta(days=BAY_TURNAROUND_GAP_DAYS)
    return (start1 <= end2 + gap) and (start2 <= end1 + gap)


def mast_slots_conflict(start1, end1, start2, end2):
    """Half-open interval overlap: E1.start < E2.end AND E2.start < E1.end."""
    return (start1 < end2) and (start2 < end1)
