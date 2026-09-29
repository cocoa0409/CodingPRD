"""The ten calculation rules (SCAFFOLD §1.3 / PRD §2.5, §3.4, §3.5, §3.7).

Rounding discipline (PRD §2.5):
  * floor  — permissible-investment coverage, ownership attribution hops, the
             class-multiplier step of the bond, the weighted oversight score.
  * round half up — renewal assessment step, call-report assessment fee, the
             per-line whole-dollar rounding of the annual assessment invoice.
  * exact integer — the obligation aggregate.
Evaluation order is normative wherever it is pinned.
"""

from decimal import ROUND_HALF_UP, Decimal

# ---------------------------------------------------------------- enums / sets
LICENSE_CLASSES = ("MONEY_TRANSMISSION", "PAYMENT_INSTRUMENTS", "VIRTUAL_CURRENCY")
ASSET_CLASSES = (
    "CASH",
    "US_TREASURY",
    "AGENCY_BOND",
    "MONEY_MARKET_FUND",
    "RECEIVABLE_FROM_DELEGATE",
    "CORPORATE_DEBT",
)
ROLE_TITLES = ("CEO", "CFO", "COO", "CCO", "DIRECTOR", "ENTITY_HOLDER", "PASSIVE_INVESTOR")
OFFICER_TITLES = ("CEO", "CFO", "COO", "CCO")

# permissible investment coverage constants
NON_PERMISSIBLE_CLASSES = ("CORPORATE_DEBT",)
HAIRCUT_BPS = {
    "CASH": 0,
    "US_TREASURY": 200,
    "AGENCY_BOND": 500,
    "MONEY_MARKET_FUND": 300,
    "RECEIVABLE_FROM_DELEGATE": 1000,
}
RECEIVABLE_MAX_AGE_DAYS = 5
CONCENTRATION_CAP_BPS = 1000
CONCENTRATION_CAPPED_CLASSES = ("AGENCY_BOND", "MONEY_MARKET_FUND", "RECEIVABLE_FROM_DELEGATE")

# posture constants
COVERAGE_PASS_BPS = 10000
COVERAGE_WATCH_FLOOR_BPS = 9500
FROZEN_FAILED_TEST_COUNT = 2

# ownership attribution constants
CONTROL_THRESHOLD_BPS = 2500
MAX_CHAIN_DEPTH = 5

# surety bond constants — PRD §3.4 tier thresholds
VOLUME_TIER_1_MAX_CENTS = 1000000000       # one billion cents == ten million dollars
VOLUME_TIER_2_MAX_CENTS = 10000000000      # ten billion cents
TIER_BOND_CENTS = (2500000, 10000000, 25000000)
CLASS_MULTIPLIER_BPS = {
    "MONEY_TRANSMISSION": 10000,
    "PAYMENT_INSTRUMENTS": 12000,
    "VIRTUAL_CURRENCY": 15000,
}

# renewal constants
DELEGATE_RENEWAL_FEE_CENTS = 25000
RENEWAL_TIER_1_MAX_CENTS = 100000
RENEWAL_TIER_2_MAX_CENTS = 250000
RENEWAL_TIER_BPS = (500, 350, 200)

# oversight constants
WEIGHT_TRAINING_BPS = 4000
WEIGHT_AML_TEST_BPS = 3500
WEIGHT_RECORDKEEPING_BPS = 2500
OVERSIGHT_MIN_SCORE = 70

# misc
REOPEN_WINDOW_DAYS = 5
CALL_REPORT_DUE_DAYS = 45
DOLLAR_CENTS = 100

# licence statuses that keep a licence inside the obligation aggregate set
AGGREGATE_LICENSE_STATUSES = ("PENDING_BOND", "ACTIVE", "SUSPENDED", "SURRENDER_REQUESTED")


# ------------------------------------------------------------------- rounding
def floor_div(numerator, denominator):
    """Floor (round down toward zero) division on integers."""
    if denominator == 0:
        return 0
    q = abs(numerator) // abs(denominator)
    if (numerator < 0) != (denominator < 0):
        return -q
    return q


def round_half_up(value):
    """Round a Decimal/int/Fraction-like value half up to a whole integer."""
    return int(Decimal(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def round_half_up_div(numerator, denominator):
    return round_half_up(Decimal(numerator) / Decimal(denominator))


# ------------------------------------------- 1. licensee_obligation_aggregate
def licensee_obligation_aggregate(licenses):
    """Exact integer-cent sum over licences still inside the aggregate set."""
    return sum(
        lic["outstanding_obligations_cents"]
        for lic in licenses
        if lic["license_status"] in AGGREGATE_LICENSE_STATUSES
    )


# ------------------------------------------ 2. permissible_investment_coverage
def concentration_cap_cents(obligations_cents):
    return floor_div(obligations_cents * CONCENTRATION_CAP_BPS, 10000)


def book_value_total(holdings):
    """BOOK_VALUE variant: carrying value, no haircut / ageing / concentration cap."""
    return sum(
        h["book_value_cents"]
        for h in holdings
        if h["status"] == "HELD" and h["asset_class"] not in NON_PERMISSIBLE_CLASSES
    )


def eligible_market_total(holdings, obligations_cents):
    """ELIGIBLE_MARKET variant.  Pinned order: per-holding haircut (floor) ->
    per-counterparty grouping -> per-group cap -> one final sum."""
    cap = concentration_cap_cents(obligations_cents)
    uncapped_total = 0
    groups = {}
    for h in holdings:
        if h["status"] != "HELD":
            continue
        asset_class = h["asset_class"]
        if asset_class in NON_PERMISSIBLE_CLASSES:
            continue
        if asset_class == "RECEIVABLE_FROM_DELEGATE" and h.get("age_days", 0) > RECEIVABLE_MAX_AGE_DAYS:
            continue
        adjusted = floor_div(h["market_value_cents"] * (10000 - HAIRCUT_BPS[asset_class]), 10000)
        if asset_class in CONCENTRATION_CAPPED_CLASSES:
            key = h["counterparty_name"]
            groups[key] = groups.get(key, 0) + adjusted
        else:
            uncapped_total += adjusted
    return uncapped_total + sum(min(total, cap) for total in groups.values())


def investment_value_for_method(holdings, obligations_cents, method):
    if method == "BOOK_VALUE":
        return book_value_total(holdings)
    return eligible_market_total(holdings, obligations_cents)


def ratio_bps(investment_value_cents, obligations_cents):
    if obligations_cents == 0:
        return 10000
    return floor_div(investment_value_cents * 10000, obligations_cents)


# ----------------------------------------------- 3. licensee_coverage_posture
def coverage_posture(coverage_ratio_bps, consecutive_failed_test_count):
    if consecutive_failed_test_count >= FROZEN_FAILED_TEST_COUNT:
        return "FROZEN"
    if coverage_ratio_bps >= COVERAGE_PASS_BPS:
        return "COMPLIANT"
    if coverage_ratio_bps >= COVERAGE_WATCH_FLOOR_BPS:
        return "WATCH"
    return "DEFICIENT"


# --------------------------------- 4. control_person_ownership_attribution
def ownership_attribution(direct_ownership_bps, parent):
    """Returns (effective_ownership_bps, attributed_ownership_bps).

    A REMOVED ancestor contributes zero to both figures.
    """
    if parent is None:
        return direct_ownership_bps, direct_ownership_bps
    if parent.get("status") == "REMOVED":
        return 0, 0
    effective = floor_div(direct_ownership_bps * parent["effective_ownership_bps"], 10000)
    if parent["direct_ownership_bps"] >= CONTROL_THRESHOLD_BPS:
        attributed = direct_ownership_bps
    else:
        attributed = floor_div(direct_ownership_bps * parent["attributed_ownership_bps"], 10000)
    return effective, attributed


def control_determination(attributed_ownership_bps, role_title):
    if attributed_ownership_bps >= CONTROL_THRESHOLD_BPS or role_title in OFFICER_TITLES:
        return "CONTROL"
    return "NON_CONTROL"


# ------------------------------------------------- 5. surety_bond_requirement
def surety_bond_requirement(jurisdiction, volume_cents, license_class, delegate_count):
    if volume_cents <= VOLUME_TIER_1_MAX_CENTS:
        tier_bond = TIER_BOND_CENTS[0]
    elif volume_cents <= VOLUME_TIER_2_MAX_CENTS:
        tier_bond = TIER_BOND_CENTS[1]
    else:
        tier_bond = TIER_BOND_CENTS[2]
    raw = max(
        jurisdiction["base_bond_cents"],
        tier_bond + delegate_count * jurisdiction["per_delegate_bond_cents"],
    )
    adjusted = floor_div(raw * CLASS_MULTIPLIER_BPS[license_class], 10000)
    return min(adjusted, jurisdiction["bond_cap_cents"])


# --------------------------------------------------- 6. renewal_fee_assessment
def renewal_fee_assessment(jurisdiction, active_delegate_count):
    subtotal = jurisdiction["renewal_fee_cents"] + active_delegate_count * DELEGATE_RENEWAL_FEE_CENTS
    if subtotal <= RENEWAL_TIER_1_MAX_CENTS:
        tier_bps = RENEWAL_TIER_BPS[0]
    elif subtotal <= RENEWAL_TIER_2_MAX_CENTS:
        tier_bps = RENEWAL_TIER_BPS[1]
    else:
        tier_bps = RENEWAL_TIER_BPS[2]
    assessment = round_half_up_div(subtotal * tier_bps, 10000)
    return subtotal + assessment


# ----------------------------------------------- 7. aggregate_assessment_invoice
def aggregate_assessment_invoice(lines):
    """lines: iterable of (license, jurisdiction) for ACTIVE licences ordered by
    created_at ASC.  Round each line to whole dollars first, THEN sum."""
    unrounded = Decimal(0)
    total = 0
    count = 0
    for lic, jur in lines:
        count += 1
        raw = Decimal(lic["outstanding_obligations_cents"]) * Decimal(jur["assessment_rate_bps"]) / Decimal(10000)
        unrounded += raw
        total += round_half_up(raw / Decimal(DOLLAR_CENTS)) * DOLLAR_CENTS
    if unrounded == unrounded.to_integral_value():
        unrounded_out = int(unrounded)
    else:
        unrounded_out = float(unrounded)
    return count, unrounded_out, total


# ------------------------------------------------- 8. delegate_oversight_score
def delegate_oversight_score(training_score, aml_test_score, recordkeeping_score):
    return floor_div(
        training_score * WEIGHT_TRAINING_BPS
        + aml_test_score * WEIGHT_AML_TEST_BPS
        + recordkeeping_score * WEIGHT_RECORDKEEPING_BPS,
        10000,
    )


# ---------------------------------------------- 10. call_report_period_and_due_at
_PERIOD_END = {"Q1": (3, 31), "Q2": (6, 30), "Q3": (9, 30), "Q4": (12, 31), "FY": (12, 31)}


def period_end_parts(period_label):
    """Returns (year, month, day) for a validated label."""
    year = int(period_label[:4])
    suffix = period_label[4:]
    month, day = _PERIOD_END[suffix]
    return year, month, day


def period_sort_key(period_label):
    year = int(period_label[:4])
    suffix = period_label[4:]
    index = {"Q1": 1, "Q2": 2, "Q3": 3, "Q4": 4, "FY": 4}[suffix]
    return (year, index)


def call_report_assessment_fee(transmission_volume_cents, assessment_rate_bps):
    return round_half_up_div(transmission_volume_cents * assessment_rate_bps, 10000)
