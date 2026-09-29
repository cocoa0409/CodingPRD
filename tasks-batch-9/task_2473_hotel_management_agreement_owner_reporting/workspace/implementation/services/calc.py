"""Calculation rules (scaffold §1.3 / PRD §2.5, §3.2-§3.9).

Every rounding order here is contractual and the three base-fee conventions
deliberately differ from each other; they must not be harmonised.
"""

from money import dec, ffloor, rhu, round_dp

MONTHS_PER_YEAR = 12
DUE_DAY_OF_FOLLOWING_MONTH = 25
CARRYFORWARD_FACTOR = "1.03"
SERVICE_PRIORITY = [
    "RESERVATIONS",
    "REVENUE_MANAGEMENT",
    "IT_HOSTING",
    "PROCUREMENT",
    "TALENT",
]
MANAGER_DISCRETION_CAP_CENTS = 2500000
ASSET_MANAGER_CAP_CENTS = 25000000
TIER1_PCT_INCLUSIVE = "0.05"
TIER2_PCT_INCLUSIVE = "0.15"


# ---------------------------------------------------------------------------
# package_derived_fields
# ---------------------------------------------------------------------------

def gross_revenue(rooms_cents, fnb_cents, other_cents):
    return rooms_cents + fnb_cents + other_cents


def due_date_parts(fiscal_year, period_month):
    """The 25th of the month after the reported period, 00:00:00Z."""
    if period_month < 12:
        return fiscal_year, period_month + 1, DUE_DAY_OF_FOLLOWING_MONTH
    return fiscal_year + 1, 1, DUE_DAY_OF_FOLLOWING_MONTH


# ---------------------------------------------------------------------------
# package_status_rollup
# ---------------------------------------------------------------------------

def package_status_rollup(financial_status, benchmark_status):
    if financial_status == "DISPUTED" or benchmark_status == "CHALLENGED":
        return "CONTESTED"
    if financial_status == "ACCEPTED" and benchmark_status == "ACCEPTED":
        return "COMPLETE"
    if financial_status == "ACCEPTED" or benchmark_status == "ACCEPTED":
        return "PARTIAL"
    return "INCOMPLETE"


# ---------------------------------------------------------------------------
# base_management_fee_per_line
# ---------------------------------------------------------------------------

def base_management_fee_per_line(rooms_cents, fnb_cents, other_cents, base_fee_pct):
    """PINNED: round each revenue line to whole cents, then sum."""
    rate = dec(base_fee_pct)
    return (
        rhu(dec(rooms_cents) * rate)
        + rhu(dec(fnb_cents) * rate)
        + rhu(dec(other_cents) * rate)
    )


# ---------------------------------------------------------------------------
# centralized_services_allocation
# ---------------------------------------------------------------------------

def centralized_cap_cents(gross_revenue_cents, centralized_services_cap_pct):
    return ffloor(dec(gross_revenue_cents) * dec(centralized_services_cap_pct))


def charge_requested_amount(pool_amount_cents, hotel_basis_share):
    return rhu(dec(pool_amount_cents) * dec(hotel_basis_share))


def charge_sort_key(charge):
    try:
        priority = SERVICE_PRIORITY.index(charge["service_code"])
    except ValueError:
        priority = len(SERVICE_PRIORITY)
    return (priority, charge["_seq"])


# ---------------------------------------------------------------------------
# agop_and_provisional_incentive
# ---------------------------------------------------------------------------

def agop_cents(gross_revenue_cents, operating_expenses_cents, base_fee_cents, allocated_centralized_cents):
    """No intermediate rounding inside this subtraction."""
    return (
        gross_revenue_cents
        - operating_expenses_cents
        - base_fee_cents
        - allocated_centralized_cents
    )


def monthly_priority_cents(owner_priority_cents):
    return rhu(dec(owner_priority_cents) / dec(MONTHS_PER_YEAR))


def provisional_incentive_cents(agop, monthly_priority, incentive_fee_pct):
    value = rhu(dec(agop - monthly_priority) * dec(incentive_fee_pct))
    return max(0, value)


# ---------------------------------------------------------------------------
# annual_incentive_true_up
# ---------------------------------------------------------------------------

def final_incentive_fee_cents(annual_agop, owner_priority_cents, tier2_threshold_cents,
                              incentive_fee_pct, incentive_tier2_pct):
    excess = annual_agop - owner_priority_cents
    if excess <= 0:
        return 0, excess
    tier1_base = min(excess, tier2_threshold_cents)
    tier2_base = max(0, excess - tier2_threshold_cents)
    total = rhu(dec(tier1_base) * dec(incentive_fee_pct)) + rhu(
        dec(tier2_base) * dec(incentive_tier2_pct)
    )
    return total, excess


# ---------------------------------------------------------------------------
# budget_agop_derivation
# ---------------------------------------------------------------------------

def budget_derived(budgeted_revenue_cents, budgeted_operating_expenses_cents,
                   base_fee_pct, centralized_services_cap_pct):
    """The budgeted base fee is rounded ONCE on the annual total."""
    base_fee = rhu(dec(budgeted_revenue_cents) * dec(base_fee_pct))
    centralized = ffloor(dec(budgeted_revenue_cents) * dec(centralized_services_cap_pct))
    agop = budgeted_revenue_cents - budgeted_operating_expenses_cents - base_fee - centralized
    return base_fee, centralized, agop


# ---------------------------------------------------------------------------
# deadlock_carryforward_amounts
# ---------------------------------------------------------------------------

def carryforward_amount(amount_cents):
    return rhu(dec(amount_cents) * dec(CARRYFORWARD_FACTOR))


# ---------------------------------------------------------------------------
# variance_approval_routing
# ---------------------------------------------------------------------------

def variance_routing(requested_amount_cents, effective_baseline_cents):
    variance_pct = round_dp(dec(requested_amount_cents) / dec(effective_baseline_cents), 6)
    if variance_pct <= dec(TIER1_PCT_INCLUSIVE) and requested_amount_cents <= MANAGER_DISCRETION_CAP_CENTS:
        return variance_pct, "MANAGER_DISCRETION", "AUTO_APPROVED"
    if variance_pct <= dec(TIER2_PCT_INCLUSIVE) and requested_amount_cents <= ASSET_MANAGER_CAP_CENTS:
        return variance_pct, "ASSET_MANAGER", "PENDING"
    return variance_pct, "OWNER_REP", "PENDING"


# ---------------------------------------------------------------------------
# cash_distribution_waterfall
# ---------------------------------------------------------------------------

def waterfall(available, wc_gap_cents, base_due_cents, reserve_due_cents,
              priority_due_cents, incent_due_cents):
    remaining = available
    wc_restoration = min(remaining, wc_gap_cents)
    remaining -= wc_restoration
    base_paid = min(remaining, base_due_cents)
    remaining -= base_paid
    reserve_contribution = min(remaining, reserve_due_cents)
    remaining -= reserve_contribution
    priority_paid = min(remaining, priority_due_cents)
    remaining -= priority_paid
    incentive_paid = min(remaining, incent_due_cents)
    remaining -= incentive_paid
    residual = remaining
    demand_total = (
        wc_gap_cents + base_due_cents + reserve_due_cents + priority_due_cents + incent_due_cents
    )
    allocated_total = (
        wc_restoration + base_paid + reserve_contribution + priority_paid + incentive_paid
    )
    return {
        "wc_restoration_cents": wc_restoration,
        "base_fee_paid_cents": base_paid,
        "reserve_contribution_cents": reserve_contribution,
        "owner_priority_paid_cents": priority_paid,
        "incentive_fee_paid_cents": incentive_paid,
        "residual_to_owner_cents": residual,
        "shortfall_cents": demand_total - allocated_total,
    }


def reserve_due_cents(gross_revenue_cents, ffe_reserve_pct):
    return rhu(dec(gross_revenue_cents) * dec(ffe_reserve_pct))


# ---------------------------------------------------------------------------
# performance_test_evaluation
# ---------------------------------------------------------------------------

def prorated_budget_agop(snapshot_cents, accepted_period_count, test_periods_expected):
    return rhu(dec(snapshot_cents) * dec(accepted_period_count) / dec(test_periods_expected))


def gop_achievement(actual_agop_cents, prorated_cents):
    return round_dp(dec(actual_agop_cents) / dec(prorated_cents), 4)


def benchmark_rpi(hotel_revpar_cents, comp_set_revpar_cents):
    return round_dp(dec(hotel_revpar_cents) / dec(comp_set_revpar_cents) * dec(100), 2)


def rpi_weighted(rows):
    numerator = sum(dec(r["hotel_revpar_cents"]) * dec(r["rooms_available"]) for r in rows)
    denominator = sum(dec(r["comp_set_revpar_cents"]) * dec(r["rooms_available"]) for r in rows)
    return round_dp(dec(100) * numerator / denominator, 2)


def rpi_simple_average(rows):
    total = sum(dec(r["rpi"]) for r in rows)
    return round_dp(total / dec(len(rows)), 2)


# ---------------------------------------------------------------------------
# employment_claim_liability_split
# ---------------------------------------------------------------------------

def employment_split(claim_amount_cents, gross_negligence, employee_model,
                     position_class, manager_indemnity_cap_cents):
    """First matching condition decides the manager's share."""
    if gross_negligence:
        manager_share = min(claim_amount_cents, manager_indemnity_cap_cents)
    elif employee_model == "OWNER_EMPLOYEES":
        manager_share = 0
    elif position_class in ("GM", "EXEC_COMMITTEE"):
        manager_share = min(claim_amount_cents // 2, manager_indemnity_cap_cents)
    else:
        manager_share = 0
    owner_share = claim_amount_cents - manager_share
    return owner_share, manager_share
