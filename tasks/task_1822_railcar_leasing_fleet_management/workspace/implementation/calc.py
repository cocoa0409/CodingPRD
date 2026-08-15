"""Calculation rules (scaffold section 1.3). Integer cents; ROUND_HALF_UP at
exactly the steps each rule pins."""
import calendar
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

HIGH_MILEAGE_THRESHOLD = 120000
EXCESS_RATE_PCT = 80
CREDIT_CAP_PCT = 80
WEAR_ALLOWANCE_CENTS = 25000
WEAR_EXCESS_LESSEE_PCT = 40
LABOR_RATE_CENTS = 14500
BETTERMENT_AGE_YEARS = 30
BETTERMENT_PCT = 25
SEVERITY_MULT = {"MINOR": Decimal("1.00"), "MODERATE": Decimal("1.25"), "SEVERE": Decimal("1.50")}


def rhu(value):
    """Round half-up a Decimal to whole cents -> int."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def month_bounds(month):
    """'YYYY-MM' -> (first date, last date)."""
    y, m = int(month[:4]), int(month[5:7])
    return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])


def month_of(d):
    return f"{d.year:04d}-{d.month:02d}"


# ---------------------------------------------------------------------------
# calc_mileage_credit
# ---------------------------------------------------------------------------
def mileage_credit(m, m_prev, r):
    """Returns (uncapped_credit_cents, tier_excess_miles)."""
    full_miles = min(m, max(0, HIGH_MILEAGE_THRESHOLD - m_prev))
    excess_miles = m - full_miles
    uncapped = full_miles * r + rhu(Decimal(excess_miles * r) * EXCESS_RATE_PCT / 100)
    return uncapped, excess_miles


# ---------------------------------------------------------------------------
# calc_car_hire_settlement
# ---------------------------------------------------------------------------
def days_on_lease_in_month(assignment, month):
    """Calendar days of month the assignment was on lease:
    max(actual_on, month_first) .. min(actual_off exclusive, month_last) inclusive."""
    first, last = month_bounds(month)
    on = assignment.get("actual_on_lease_date")
    if on is None:
        return 0
    start = max(on, first)
    off = assignment.get("actual_off_lease_date")
    end_incl = min(off - timedelta(days=1), last) if off else last
    if end_incl < start:
        return 0
    return (end_incl - start).days + 1


def settlement(days_on_lease, daily_rate, lessor_share_pct, m, m_prev, r):
    """Shared settlement formula. Returns a dict of measured fields.
    Pinned rounding order: lessor share, then excess-miles term (inside
    mileage_credit), then the credit cap."""
    gross = days_on_lease * daily_rate
    lessor_share = rhu(Decimal(gross) * lessor_share_pct / 100)
    credit_raw, tier_excess = mileage_credit(m, m_prev, r)
    credit_cap = rhu(Decimal(gross) * CREDIT_CAP_PCT / 100)
    credit = min(credit_raw, credit_cap)
    net = lessor_share - credit
    return {
        "days_on_lease": days_on_lease,
        "gross_car_hire_cents": gross,
        "loaded_miles_used": m,
        "tier_excess_miles": tier_excess,
        "mileage_credit_cents": credit,
        "net_cents": net,
    }


# ---------------------------------------------------------------------------
# calc_repair_responsibility_split
# ---------------------------------------------------------------------------
def repair_split(lease_type, defect_cause, cost_cents):
    """Returns (lessee_share, lessor_share)."""
    if defect_cause == "LESSEE_DAMAGE":
        lessee = cost_cents
    elif lease_type == "NET":
        lessee = cost_cents
    elif defect_cause == "PRE_EXISTING":
        lessee = 0
    else:  # FULL_SERVICE + WEAR_AND_TEAR
        excess = max(0, cost_cents - WEAR_ALLOWANCE_CENTS)
        lessee = rhu(Decimal(excess) * WEAR_EXCESS_LESSEE_PCT / 100)
    return lessee, cost_cents - lessee


# ---------------------------------------------------------------------------
# calc_damage_billing_schedule
# ---------------------------------------------------------------------------
def damage_totals(line_items, car_age_years):
    """Per-line rounding (twice per line), then sum. Returns (total, lessee_liable)."""
    total = 0
    liable = 0
    for line in line_items:
        raw = Decimal(line["parts_cents"]) + (
            Decimal(str(line["labor_hours"]))
            * LABOR_RATE_CENTS
            * SEVERITY_MULT[line["severity"]]
        )
        line_cost = rhu(raw)
        if (
            line["cause"] == "LESSEE_DAMAGE"
            and line["replaced"] is True
            and car_age_years >= BETTERMENT_AGE_YEARS
        ):
            line_lessee = rhu(Decimal(line_cost) * (100 - BETTERMENT_PCT) / 100)
        elif line["cause"] == "LESSEE_DAMAGE":
            line_lessee = line_cost
        else:
            line_lessee = 0
        total += line_cost
        liable += line_lessee
    return total, liable


# ---------------------------------------------------------------------------
# calc_lease_proration
# ---------------------------------------------------------------------------
def proration(assignment, shop_repairs, lease, current_terminated_fee):
    """shop_repairs: COMPLETED requires_shop repairs on this assignment.
    Returns (billable_days, final_rent_cents, termination_fee_cents)."""
    on = assignment["actual_on_lease_date"]
    off = assignment["actual_off_lease_date"]
    excluded = 0
    for rep in shop_repairs:
        if rep["lessor_share_cents"] and rep["lessor_share_cents"] > 0:
            start = max(rep["shop_entry_date"], on)
            end = min(rep["completion_date"], off)
            if end > start:
                excluded += (end - start).days
    raw_days = (off - on).days
    billable = raw_days - excluded
    final_rent = billable * lease["base_daily_rate_cents"]
    fee = current_terminated_fee if lease["status"] == "TERMINATED" else 0
    return billable, final_rent, fee or 0


def early_termination_fee(lease, current_date):
    """min(max(0, end - current in days), 90) * base_daily_rate_cents * 50% rhu."""
    remaining = max(0, (lease["end_date"] - current_date).days)
    days = min(remaining, 90)
    return rhu(Decimal(days * lease["base_daily_rate_cents"]) * 50 / 100)


# ---------------------------------------------------------------------------
# calc_retrofit_penalty (both variants, computed on read)
# ---------------------------------------------------------------------------
def retrofit_penalty(directive, current_date):
    """Returns (accrued_cents, assessed_cents, days_since_effective)."""
    days = max(0, (current_date - directive["effective_date"]).days)
    accrued = days * directive["daily_penalty_cents"]
    beyond = max(0, days - directive["grace_days"])
    assessed = min(beyond * directive["daily_penalty_cents"], directive["penalty_cap_cents"])
    return accrued, assessed, days


# ---------------------------------------------------------------------------
# calc_fleet_utilization
# ---------------------------------------------------------------------------
def utilization_pct(on_lease_days, eligible_days):
    if eligible_days == 0:
        return 0.0
    val = (Decimal(100) * on_lease_days / eligible_days).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return float(val)
