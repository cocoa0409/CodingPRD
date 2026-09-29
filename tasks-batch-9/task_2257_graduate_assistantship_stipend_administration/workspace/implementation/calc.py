"""Calculation rules (scaffold 1.3 / PRD 3.5, 3.8, 3.9)."""
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP, ROUND_DOWN

# ---- constants -------------------------------------------------------------
FULL_TIME_WEEKLY_HOURS = Decimal(40)
DEFAULT_EFFORT_CAP_PCT = 75
INTERNATIONAL_MAX_WEEKLY_HOURS = Decimal("20.0")
MAX_REMITTED_CREDITS = {"MASTERS": 9, "DOCTORAL": 12}
SUBSIDY_TIER_BREAK_LOW_CENTS = 1200000
SUBSIDY_TIER_BREAK_HIGH_CENTS = 1800000
IMPUTED_WITHHOLDING_RATE = Decimal("0.2200")
RENEWAL_WINDOW_DAYS = 120
MIN_RENEWAL_GPA = Decimal("3.00")

COUNTED_EFFORT_STATUSES = (
    "SUBMITTED", "FUNDING_VERIFIED", "APPROVED", "ACTIVE", "NON_RENEWAL_PENDING",
)
TAX_COUNTED_STATUSES = (
    "APPROVED", "ACTIVE", "NON_RENEWAL_PENDING", "COMPLETED", "TERMINATED",
)
ACTIVE_ALLOCATION_STATUSES = ("PROPOSED", "COMMITTED")


# ---- rounding disciplines (PRD 2.6) ---------------------------------------
def round_half_up(value, places=0):
    quant = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(quant, rounding=ROUND_HALF_UP)


def rhu_cents(value):
    return int(round_half_up(value, 0))


def truncate_cents(value):
    return int(Decimal(value).to_integral_value(rounding=ROUND_DOWN))


def hours_1dp(value):
    return round_half_up(value, 1)


# ---- date helpers ---------------------------------------------------------
def iso_date(value):
    return value.isoformat()


def parse_iso(value):
    parts = value.split("-")
    return date(int(parts[0]), int(parts[1]), int(parts[2]))


def calendar_days(start, end_exclusive):
    if end_exclusive <= start:
        return 0
    return (end_exclusive - start).days


def workdays(start, end_exclusive):
    """Monday-Friday dates in the half-open range [start, end_exclusive)."""
    if end_exclusive <= start:
        return 0
    total = (end_exclusive - start).days
    weeks, remainder = divmod(total, 7)
    count = weeks * 5
    weekday = start.weekday()
    for offset in range(remainder):
        if (weekday + offset) % 7 < 5:
            count += 1
    return count


# ---- appointment_effort_profile -------------------------------------------
def weekly_hours_for(effort_pct):
    return hours_1dp(Decimal(effort_pct) * FULL_TIME_WEEKLY_HOURS / Decimal(100))


def duration_days_for(start_date, end_date):
    return (end_date - start_date).days + 1


def remission_band_pct(effort_pct):
    if effort_pct < 25:
        return 0
    if effort_pct < 50:
        return 50
    if effort_pct < 75:
        return 75
    return 100


def insurance_eligible_for(effort_pct, duration_days, policy):
    return (effort_pct >= policy["insurance_min_effort_pct"]
            and duration_days >= policy["min_insurance_duration_days"])


# ---- stipend_pay_schedule -------------------------------------------------
def pay_schedule(appointment, periods, proration_method):
    """Returns a list of dicts, one per non-skipped PayPeriod in sequence order."""
    start = parse_iso(appointment["start_date"])
    end_exclusive = parse_iso(appointment["end_date"]) + timedelta(days=1)
    monthly = appointment["monthly_stipend_cents"]
    rows = []
    for period in sorted(periods, key=lambda p: (p["sequence_no"], p["_seq"])):
        period_start = parse_iso(period["period_start"])
        period_end = parse_iso(period["period_end_exclusive"])
        overlap_start = max(period_start, start)
        overlap_end = min(period_end, end_exclusive)
        if overlap_end <= overlap_start:
            continue
        if proration_method == "WORKDAY":
            covered_units = workdays(overlap_start, overlap_end)
            period_units = workdays(period_start, period_end)
        else:
            covered_units = calendar_days(overlap_start, overlap_end)
            period_units = calendar_days(period_start, period_end)
        if period_units <= 0:
            gross = 0
        else:
            gross = rhu_cents(Decimal(monthly) * Decimal(covered_units) / Decimal(period_units))
        rows.append({
            "pay_period": period,
            "covered_units": covered_units,
            "period_units": period_units,
            "gross_amount_cents": gross,
        })
    return rows


# ---- cost_share_allocation_split -----------------------------------------
def split_ordering(allocations):
    """(share_pct DESC, plan_sequence ASC) -- the pinned tie-break ordering."""
    return sorted(allocations, key=lambda a: (-a["share_pct"], a["plan_sequence"], a["_seq"]))


def split_by_share(basis_cents, allocations):
    """Truncate per allocation, then hand the whole remainder to the first row."""
    ordered = split_ordering(allocations)
    amounts = {}
    if not ordered:
        return ordered, amounts
    running = 0
    for alloc in ordered:
        amount = truncate_cents(Decimal(basis_cents) * alloc["share_pct"] / Decimal(100))
        amounts[alloc["id"]] = amount
        running += amount
    amounts[ordered[0]["id"]] += basis_cents - running
    return ordered, amounts


def split_remission(total_cents, eligible_allocations, eligible_share_pct):
    """Split tuition_remission_cents over the remission-eligible allocations."""
    ordered = split_ordering(eligible_allocations)
    amounts = {}
    if not ordered or eligible_share_pct <= 0:
        return ordered, amounts
    running = 0
    for alloc in ordered:
        amount = truncate_cents(
            Decimal(total_cents) * alloc["share_pct"] / Decimal(eligible_share_pct))
        amounts[alloc["id"]] = amount
        running += amount
    amounts[ordered[0]["id"]] += total_cents - running
    return ordered, amounts


# ---- insurance_subsidy_and_net_stipend -----------------------------------
def subsidy_tier_pct(gross_term_stipend_cents):
    if gross_term_stipend_cents < SUBSIDY_TIER_BREAK_LOW_CENTS:
        return 90
    if gross_term_stipend_cents < SUBSIDY_TIER_BREAK_HIGH_CENTS:
        return 75
    return 50


def insurance_and_net(gross_term_stipend_cents, insurance_eligible, policy):
    premium = policy["term_insurance_premium_cents"] if insurance_eligible else 0
    tier = subsidy_tier_pct(gross_term_stipend_cents)
    subsidy = rhu_cents(Decimal(premium) * Decimal(tier) / Decimal(100))
    employee = premium - subsidy
    net = gross_term_stipend_cents - employee
    return subsidy, employee, net


# ---- tuition_benefit_tax_assessment --------------------------------------
def withholding(taxable_cents):
    return rhu_cents(Decimal(taxable_cents) * IMPUTED_WITHHOLDING_RATE)
