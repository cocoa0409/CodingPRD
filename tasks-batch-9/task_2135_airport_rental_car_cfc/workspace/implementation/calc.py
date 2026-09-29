"""Calculation rules — PRD sections 2.7, 3.4-3.10."""

import calendar
import datetime
from decimal import Decimal, ROUND_HALF_UP
from fractions import Fraction

BPS_DENOMINATOR = 10000
DS_SHARE_BPS = 6000
OM_SHARE_BPS = 2500
MONTHS_PER_CONTRACT_YEAR = 12
DEFAULT_COVERAGE_REQUIREMENT_BPS = 12500
CREDIT_TIER_HIGH_MIN_CENTS = 5000000
CREDIT_TIER_HIGH_BPS = 300
CREDIT_TIER_MID_MIN_CENTS = 1000000
CREDIT_TIER_MID_BPS = 150


def round_half_up(numerator, denominator):
    """Integer round-half-up of numerator/denominator."""
    return int((Decimal(numerator) / Decimal(denominator)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP))


def bps_of(amount, bps):
    """round_half_up(amount * bps / 10000)."""
    return round_half_up(amount * bps, BPS_DENOMINATOR)


def floor_bps_of(amount, bps):
    """floor(amount * bps / 10000)."""
    return (amount * bps) // BPS_DENOMINATOR


def ratio_4dp(numerator, denominator):
    value = (Decimal(numerator) / Decimal(denominator)).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return float(value)


def last_day_of_month(year, month):
    return datetime.date(year, month, calendar.monthrange(year, month)[1])


def date_of(value):
    return datetime.date(int(value[0:4]), int(value[5:7]), int(value[8:10]))


def iso(day):
    return day.isoformat()


def inclusive_days(start_date, end_date):
    return (date_of(end_date) - date_of(start_date)).days + 1


# --------------------------------------------------------------------------
# 3.5 percentage rent accrual
# --------------------------------------------------------------------------

def percentage_rent_accrual(agreement, report):
    """Runs after hop two's accumulator increments. Mutates agreement + report."""
    months_elapsed = agreement["accepted_report_count"]
    monthly_mag_cents = agreement["mag_annual_cents"] // MONTHS_PER_CONTRACT_YEAR
    if months_elapsed >= MONTHS_PER_CONTRACT_YEAR:
        mag_to_date_cents = agreement["mag_annual_cents"]
    else:
        mag_to_date_cents = monthly_mag_cents * months_elapsed
    pct_ytd_cents = bps_of(agreement["gross_revenue_ytd_cents"],
                           agreement["percentage_rent_rate_bps"])

    if agreement["rent_settlement_basis"] == "CUMULATIVE_YTD":
        rent_due_to_date_cents = max(pct_ytd_cents, mag_to_date_cents)
        installment_cents = rent_due_to_date_cents - agreement["rent_billed_to_date_cents"]
    else:  # MONTHLY_STANDALONE
        pct_month_cents = bps_of(report["audited_gross_revenue_cents"],
                                 agreement["percentage_rent_rate_bps"])
        installment_cents = max(pct_month_cents, monthly_mag_cents)

    agreement["percentage_rent_accrued_cents"] = pct_ytd_cents
    agreement["rent_billed_to_date_cents"] = \
        agreement["rent_billed_to_date_cents"] + installment_cents
    agreement["last_installment_cents"] = installment_cents
    agreement["mag_shortfall_cents"] = max(0, mag_to_date_cents - pct_ytd_cents)
    agreement["rent_tier"] = "PERCENTAGE" if pct_ytd_cents > mag_to_date_cents else "MAG_FLOOR"
    report["period_rent_installment_cents"] = installment_cents
    return installment_cents


# --------------------------------------------------------------------------
# 3.6 CFC trust waterfall
# --------------------------------------------------------------------------

def cfc_trust_waterfall(facility, amount):
    """Split the newly arrived cents across the four buckets. Returns the split."""
    gap_ds = max(0, facility["ds_reserve_requirement_cents"]
                 - facility["trust_debt_service_reserve_cents"]
                 - facility["trust_debt_service_funded_cents"])
    gap_om = max(0, facility["om_reserve_requirement_cents"]
                 - facility["trust_om_reserve_cents"])

    if facility["bond_coverage_status"] == "DEFICIENT":
        to_ds = min(amount, gap_ds)
    else:
        to_ds = min(floor_bps_of(amount, DS_SHARE_BPS), gap_ds)
    r1 = amount - to_ds

    to_om = min(floor_bps_of(r1, OM_SHARE_BPS), gap_om)
    r2 = r1 - to_om

    gap_cap = max(0, facility["capital_fund_cap_cents"] - facility["trust_capital_fund_cents"])
    to_capital = min(r2, gap_cap)
    to_unallocated = r2 - to_capital
    return to_ds, to_om, to_capital, to_unallocated


def recompute_bond_coverage(facility):
    total = facility["trust_debt_service_reserve_cents"] + \
        facility["trust_debt_service_funded_cents"]
    facility["bond_coverage_status"] = \
        "SATISFIED" if total >= facility["ds_reserve_requirement_cents"] else "DEFICIENT"


# --------------------------------------------------------------------------
# 3.7 coverage test
# --------------------------------------------------------------------------

def coverage_available(facility):
    return facility["trust_debt_service_reserve_cents"] + facility["trust_unallocated_cents"]


def coverage_passes(facility, obligation):
    available = coverage_available(facility)
    return (available * BPS_DENOMINATOR) >= \
        (obligation["coverage_requirement_bps"] * obligation["amount_due_cents"])


# --------------------------------------------------------------------------
# 3.9 shuttle cost allocation (largest remainder)
# --------------------------------------------------------------------------

def largest_remainder(total_cost_cents, entries, total_basis_value):
    """entries: list of dicts with 'basis_value' and 'created_at'/'_seq' ordering keys.

    Returns list of (floor_cents, remainder_rank, amount_cents, share_bps) aligned
    with `entries` (which are already in agreement created_at ascending order).
    """
    floors = []
    fracs = []
    for entry in entries:
        exact = Fraction(total_cost_cents * entry["basis_value"], total_basis_value)
        floor_cents = exact.numerator // exact.denominator
        floors.append(floor_cents)
        fracs.append(exact - floor_cents)

    remainder_pool = total_cost_cents - sum(floors)

    order = sorted(range(len(entries)), key=lambda i: (-fracs[i], entries[i]["_order"]))
    ranks = [0] * len(entries)
    for position, index in enumerate(order, start=1):
        ranks[index] = position

    results = []
    for index, entry in enumerate(entries):
        amount = floors[index] + (1 if ranks[index] <= remainder_pool else 0)
        share_bps = round_half_up(entry["basis_value"] * BPS_DENOMINATOR, total_basis_value)
        results.append((floors[index], ranks[index], amount, share_bps))
    return results


# --------------------------------------------------------------------------
# 3.10 true-up settlement
# --------------------------------------------------------------------------

def credit_tier_bps(base_true_up_cents):
    if base_true_up_cents <= 0:
        return 0
    if base_true_up_cents >= CREDIT_TIER_HIGH_MIN_CENTS:
        return CREDIT_TIER_HIGH_BPS
    if base_true_up_cents >= CREDIT_TIER_MID_MIN_CENTS:
        return CREDIT_TIER_MID_BPS
    return 0
