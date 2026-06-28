"""Calculation rules (SCAFFOLD §1.3 / PRD §2.7, §3.3, §3.5, §3.6, §3.7).

All monetary amounts are integer cents. Non-integer intermediates round
half-up to whole cents (PRD §2.7). Never use float for money rounding — use
Decimal with ROUND_HALF_UP.
"""
import math
from calendar import monthrange
from decimal import Decimal, ROUND_HALF_UP

# ---- compute_monthly_storage (PRD §3.3) ----
TIER_BASE_CENTS = {"SMALL": 20000, "MEDIUM": 35000, "LARGE": 52500}
OVERSIZE_BAND_FT = Decimal("0.5")
OVERSIZE_SURCHARGE_PCT = Decimal("0.15")

# ---- compute_seasonal_factor (PRD §3.7) ----
PEAK_START_MONTH = 5
PEAK_END_MONTH = 9
PEAK_MULTIPLIER = Decimal("1.20")
OFF_MULTIPLIER = Decimal("1.00")

# ---- compute_launch_fee (PRD §3.5) ----
LAUNCH_BASE_CENTS = 4500
LAUNCH_PER_FOOT_CENTS = 250
LAUNCH_HEAVY_SURCHARGE_CENTS = 3000
HEAVY_WEIGHT_LBS = 8000
SPLASH_FEE_CENTS = 6000

# ---- compute_service_total (PRD §3.6) ----
WINTERIZATION_FEE_CENTS = 25000
HAUL_OUT_FEE_CENTS = 18000

# ---- compute_account_balance (PRD §3.1/§3.7) ----
DELINQUENCY_THRESHOLD_CENTS = 50000


def _round_half_up(value):
    """Round a Decimal to a whole integer of cents using round-half-up."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_monthly_storage(tier_size_class, vessel_loa_ft, rack_max_loa_ft):
    """Returns (monthly_base_cents, oversize_surcharge_applied).

    Oversize surcharge applies when rack.max_loa_ft - vessel.loa_ft <= 0.5 ft.
    When oversize, base * 1.15 round-half-up; else exactly the base.
    Seasonal multiplier is NOT folded in here (applied at invoice time)."""
    base = TIER_BASE_CENTS[tier_size_class]
    diff = Decimal(str(rack_max_loa_ft)) - Decimal(str(vessel_loa_ft))
    oversize = diff <= OVERSIZE_BAND_FT
    if oversize:
        monthly_base = _round_half_up(Decimal(base) * (Decimal("1") + OVERSIZE_SURCHARGE_PCT))
        return monthly_base, True
    return base, False


def compute_seasonal_factor(monthly_base_cents, period_start_dt):
    """Seasonal monthly amount = monthly_base_cents * factor, round-half-up.
    Factor is PEAK (1.20) for months May(5)-Sep(9) inclusive, else OFF (1.00)."""
    m = period_start_dt.month
    factor = PEAK_MULTIPLIER if (PEAK_START_MONTH <= m <= PEAK_END_MONTH) else OFF_MULTIPLIER
    return _round_half_up(Decimal(monthly_base_cents) * factor)


def days_in_month_of(dt):
    return monthrange(dt.year, dt.month)[1]


def day_count_inclusive(period_start_dt, period_end_dt):
    """Inclusive day span across the half-open period [period_start, period_end).
    The billable-days count is the number of whole days from start up to (not
    including) end, measured as the day difference."""
    delta = period_end_dt - period_start_dt
    return delta.days


def compute_invoice_amount(source_kind, variant, agreement=None, launch=None,
                           service_order=None, period_start_dt=None, period_end_dt=None):
    """compute_invoice_amount (PRD §3.7)."""
    if source_kind == "STORAGE_AGREEMENT":
        seasonal_monthly = compute_seasonal_factor(agreement["monthly_base_cents"], period_start_dt)
        if variant == "PROVISIONAL":
            # Forward-looking: bill full seasonal monthly, ignore period_end.
            return seasonal_monthly
        # FINAL: chronological proration over actual occupancy days.
        days_in_month = days_in_month_of(period_start_dt)
        billable_days = day_count_inclusive(period_start_dt, period_end_dt)
        return _round_half_up(Decimal(seasonal_monthly) * Decimal(billable_days) / Decimal(days_in_month))
    if source_kind == "LAUNCH_REQUEST":
        return launch["launch_fee_cents"]
    if source_kind == "SERVICE_ORDER":
        return service_order["total_cents"]
    return 0


def compute_launch_fee(vessel_loa_ft, vessel_dry_weight_lbs, with_valet_splash):
    """Combinatorial: base + per-foot(ceil LOA) + heavy surcharge + optional splash.
    All whole-cent constants and per-foot * whole feet, so no rounding needed."""
    per_foot_component = LAUNCH_PER_FOOT_CENTS * int(math.ceil(vessel_loa_ft))
    weight_surcharge = LAUNCH_HEAVY_SURCHARGE_CENTS if vessel_dry_weight_lbs > HEAVY_WEIGHT_LBS else 0
    splash = SPLASH_FEE_CENTS if with_valet_splash else 0
    return LAUNCH_BASE_CENTS + per_foot_component + weight_surcharge + splash


def compute_service_total(service_kind, fuel_gallons=0, fuel_price_cents_per_gal=0):
    """Round-each-line-then-sum (single line for all kinds here)."""
    if service_kind == "FUEL":
        fuel_line = _round_half_up(Decimal(str(fuel_gallons)) * Decimal(fuel_price_cents_per_gal))
        return fuel_line
    if service_kind == "VALET_SPLASH":
        return SPLASH_FEE_CENTS
    if service_kind == "WINTERIZATION":
        return WINTERIZATION_FEE_CENTS
    if service_kind == "HAUL_OUT":
        return HAUL_OUT_FEE_CENTS
    return 0


def compute_waitlist_priority(entry, clock_now_dt, joined_at_dt):
    """priority_score = (DEPOSIT_WEIGHT if deposit_paid else 0) + days_waiting,
    where days_waiting = floor((clock - joined_at) / 86400 seconds)."""
    DEPOSIT_WEIGHT = 100000
    elapsed_seconds = (clock_now_dt - joined_at_dt).total_seconds()
    days_waiting = int(math.floor(elapsed_seconds / 86400))
    if days_waiting < 0:
        days_waiting = 0
    deposit_bonus = DEPOSIT_WEIGHT if entry.get("deposit_paid") else 0
    return deposit_bonus + days_waiting
