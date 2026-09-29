"""Arithmetic primitives and the pure calculations — PRD §2.5 and §3.

Money is integer cents, share quantities integer `_e4` units (1 share =
10000), rates integer basis points (10000 bps = 100%).  `round_half_up`
resolves an exact tie away from zero; `floor` truncates toward negative
infinity.  Wherever a total is the sum of independently rounded components,
each component is reduced to whole cents on its own first.
"""

BPS_SCALE = 10000
SHARE_UNIT_SCALE = 10000
FULL_COVERAGE_BPS = 10000
CONCENTRATION_LIMIT_BPS = 1000
STRICT_CONCENTRATION_STATES = ("OH", "MA", "NM", "IA", "AL")
MINIMUM_INITIAL_INVESTMENT_CENTS = 250000
MINIMUM_ADDITIONAL_INVESTMENT_CENTS = 50000
NAV_VARIANCE_ESCALATION_BPS = 500
MONTHS_PER_YEAR = 12
MONTHLY_REPURCHASE_CAP_BPS = 200
QUARTERLY_REPURCHASE_CAP_BPS = 500
EARLY_REPURCHASE_DEDUCTION_BPS = 200
EARLY_REPURCHASE_MIN_HOLDING_DAYS = 365
REPURCHASE_PERIOD_BLACKOUT_DAYS = 5
QUORUM_DIVISOR = 2
AUTO_SUSPEND_MINOR_THRESHOLD = 3
AUTO_SUSPEND_MAJOR_THRESHOLD = 1


def round_half_up(numerator, denominator):
    """Nearest integer, exact ties away from zero."""
    if denominator == 0:
        return 0
    if denominator < 0:
        numerator, denominator = -numerator, -denominator
    if numerator >= 0:
        return (2 * numerator + denominator) // (2 * denominator)
    return -((2 * (-numerator) + denominator) // (2 * denominator))


def floor_div(numerator, denominator):
    """Floor toward negative infinity."""
    if denominator == 0:
        return 0
    if denominator < 0:
        numerator, denominator = -numerator, -denominator
    return numerator // denominator


# --- calculations.investor_concentration_limit -----------------------------

def concentration_basis_cents(state_code, net_worth_cents, annual_income_cents):
    if state_code in STRICT_CONCENTRATION_STATES:
        return min(net_worth_cents, annual_income_cents)
    return net_worth_cents


def concentration_limit_cents(state_code, net_worth_cents, annual_income_cents):
    basis = concentration_basis_cents(state_code, net_worth_cents, annual_income_cents)
    return floor_div(basis * CONCENTRATION_LIMIT_BPS, BPS_SCALE)


# --- calculations.subscription_load_and_shares -----------------------------

def subscription_figures(gross_investment_cents, commission_bps, dealer_bps, price_cents):
    commission = round_half_up(gross_investment_cents * commission_bps, BPS_SCALE)
    dealer = round_half_up(gross_investment_cents * dealer_bps, BPS_SCALE)
    net = gross_investment_cents - commission - dealer
    shares = floor_div(net * SHARE_UNIT_SCALE, price_cents) if price_cents else 0
    applied = floor_div(shares * price_cents, SHARE_UNIT_SCALE)
    return {
        "upfront_selling_commission_cents": commission,
        "dealer_manager_fee_cents": dealer,
        "net_invested_cents": net,
        "shares_issued_e4": shares,
        "unapplied_cash_cents": net - applied,
    }


# --- calculations.nav_per_share -------------------------------------------

def nav_per_share(gross_asset_value_cents, other_liabilities_cents,
                  accrued_distribution_payable_cents, shares_outstanding_e4,
                  initial_offering_price_cents):
    pre = gross_asset_value_cents - other_liabilities_cents
    post = pre - accrued_distribution_payable_cents
    if shares_outstanding_e4 == 0:
        return initial_offering_price_cents, initial_offering_price_cents
    return (
        round_half_up(pre * SHARE_UNIT_SCALE, shares_outstanding_e4),
        round_half_up(post * SHARE_UNIT_SCALE, shares_outstanding_e4),
    )


# --- calculations.nav_variance -------------------------------------------

def nav_variance_bps(nav_per_share_cents, prior_nav_per_share_cents):
    if prior_nav_per_share_cents in (None, 0):
        return 0
    delta = abs(nav_per_share_cents - prior_nav_per_share_cents)
    return floor_div(delta * BPS_SCALE, prior_nav_per_share_cents)


# --- calculations.aggregate_nav ------------------------------------------

def class_nav_contribution_cents(price_cents, shares_outstanding_e4):
    return round_half_up(price_cents * shares_outstanding_e4, SHARE_UNIT_SCALE)


# --- calculations.distribution_declaration_total_and_coverage -------------

def declaration_total_cents(declared_per_share_cents, class_share_counts):
    total = 0
    for shares in class_share_counts:
        total += round_half_up(declared_per_share_cents * shares, SHARE_UNIT_SCALE)
    return total


def coverage_bps(basis_cents, total_declared_cents):
    if total_declared_cents == 0:
        return 0
    return floor_div(basis_cents * BPS_SCALE, total_declared_cents)


def return_of_capital_bps(coverage):
    return max(0, FULL_COVERAGE_BPS - coverage)


# --- calculations.distribution_fee_accrual_and_conversion ------------------

def lot_value_cents(price_cents, remaining_shares_e4):
    return round_half_up(price_cents * remaining_shares_e4, SHARE_UNIT_SCALE)


def monthly_distribution_fee_cents(lot_value, annual_distribution_fee_bps):
    return round_half_up(lot_value * annual_distribution_fee_bps,
                         BPS_SCALE * MONTHS_PER_YEAR)


def converted_shares_e4(remaining_shares_e4, from_price_cents, to_price_cents):
    if not to_price_cents:
        return remaining_shares_e4
    return floor_div(remaining_shares_e4 * from_price_cents, to_price_cents)


# --- calculations.repurchase_capacity ------------------------------------

def repurchase_capacity(aggregate_nav_cents, quarter_used_cents):
    monthly = floor_div(aggregate_nav_cents * MONTHLY_REPURCHASE_CAP_BPS, BPS_SCALE)
    quarterly_ceiling = floor_div(
        aggregate_nav_cents * QUARTERLY_REPURCHASE_CAP_BPS, BPS_SCALE)
    quarterly_remaining = max(0, quarterly_ceiling - quarter_used_cents)
    return monthly, quarterly_remaining, min(monthly, quarterly_remaining)


# --- calculations.early_repurchase_deduction -----------------------------

def early_repurchase_deduction_cents(lot_gross_cents, holding_days):
    if holding_days >= EARLY_REPURCHASE_MIN_HOLDING_DAYS:
        return 0
    return round_half_up(lot_gross_cents * EARLY_REPURCHASE_DEDUCTION_BPS, BPS_SCALE)


# --- calculations.vote_tally ---------------------------------------------

def vote_outcome(votes_for_e4, votes_against_e4, votes_abstain_e4,
                 record_date_shares_e4):
    shares_cast = votes_for_e4 + votes_against_e4 + votes_abstain_e4
    quorum_threshold = floor_div(record_date_shares_e4, QUORUM_DIVISOR)
    quorum_met = shares_cast >= quorum_threshold
    approved = quorum_met and (2 * votes_for_e4) > record_date_shares_e4
    return quorum_met, approved


# --- calculations.repurchase_period_window -------------------------------

def quarter_key(year, month):
    quarter = floor_div(month - 1, 3) + 1
    return "%04d-Q%d" % (year, quarter)


# --- calculations.nav_period_coverage ------------------------------------

def periods_overlap(start_a, end_a, start_b, end_b):
    """Closed intervals on both ends: a shared calendar date is an overlap."""
    return start_a <= end_b and start_b <= end_a
