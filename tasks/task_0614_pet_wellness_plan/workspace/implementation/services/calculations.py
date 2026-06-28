"""Calculation rules (PRD §3.4–§3.9, scaffold §1.3).

All monetary amounts are integer cents (PRD §2.7). Only two calculations have a
fractional intermediate and pin a round-half-up rule: the à-la-carte discount
and the plan-change proration. Everything else is exact integer arithmetic.
"""
from decimal import Decimal, ROUND_HALF_UP

# Constants (scaffold §1.3 / PRD §3.5, §3.6, §3.8, §3.9).
DENTAL_MED_KG = Decimal("10")
DENTAL_LARGE_KG = Decimal("25")
DENTAL_MED_SURCHARGE_CENTS = 1500
DENTAL_LARGE_SURCHARGE_CENTS = 4000
CATALOG_DEFAULT_UNIT_CENTS = {"EXAM": 6000, "VACCINE": 3500, "DENTAL": 22000}
EARLY_TERMINATION_FEE_CENTS = 5000
RENEWAL_WINDOW_DAYS = 7


def round_half_up(value):
    """Round a Decimal to the nearest whole cent, half up -> int."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_alacarte_price(service_code, base_cents, weight_kg, discount_pct):
    """à-la-carte price (PRD §3.5).

    base_cents: PlanService.unit_value_cents for (plan, service_code), or the
    catalogue default when the plan has no inclusion line for that code (caller
    resolves which). surcharge applies only to DENTAL by pet weight. The
    discount is rounded half up FIRST, then subtracted from gross.
    """
    surcharge_cents = 0
    if service_code == "DENTAL":
        w = Decimal(str(weight_kg))
        if w >= DENTAL_LARGE_KG:
            surcharge_cents = DENTAL_LARGE_SURCHARGE_CENTS
        elif w >= DENTAL_MED_KG:
            surcharge_cents = DENTAL_MED_SURCHARGE_CENTS
        else:
            surcharge_cents = 0
    gross_cents = base_cents + surcharge_cents
    # Round the discount to integer cents BEFORE subtracting (order pinned).
    discount_cents = round_half_up(Decimal(gross_cents) * Decimal(str(discount_pct)))
    charged_cents = gross_cents - discount_cents
    return charged_cents


def days_between(start_dt, end_dt):
    """Whole-day count between two datetimes: counting the start day and not the
    end day (PRD §3.6). Computed on the date components."""
    sd = start_dt.date()
    ed = end_dt.date()
    return (ed - sd).days


def compute_plan_change_proration(from_fee_cents, to_fee_cents,
                                  period_start, period_end, now_dt):
    """Daily-rate proration over the current monthly billing window (PRD §3.6).

    days_in_cycle = days between period_start and period_end (start counted,
    end not). days_remaining = days between now date and period_end (>= 0).
    Daily rates kept as exact rationals; product rounded half up ONCE at the
    end. Returns the signed proration_delta_cents.
    """
    days_in_cycle = days_between(period_start, period_end)
    days_remaining = days_between(now_dt, period_end)
    if days_remaining < 0:
        days_remaining = 0
    if days_in_cycle <= 0:
        # Degenerate window; no proration basis.
        return 0
    from_daily = Decimal(from_fee_cents) / Decimal(days_in_cycle)
    to_daily = Decimal(to_fee_cents) / Decimal(days_in_cycle)
    delta = (to_daily - from_daily) * Decimal(days_remaining)
    return round_half_up(delta)
