"""The arithmetic the contract pins, and assertion helpers that report mismatches.

The money and basis-point functions here re-derive the PRD's own formulas in the
PRD's own order rather than restating their answers, so a test can pin an exact
figure and still show where that figure comes from. Which rounding mode applies is
never a choice: floor for every basis-point ratio and for each intermediate
division of the rent ceiling and the per-unit qualified basis, round half up for
the issuance allowance, each arbitrage period accrual, the annual credit and the
recapture exposure, and round up for the bond denomination step alone.
"""

from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from prd_bench_local_runner.testing import validate_paginated

from . import constants


# ─── Rounding primitives (PRD §2.5) ───────────────────


def floor_div(numerator, denominator):
    """Integer division with the quotient floored, as every bps ratio requires."""
    return int(Decimal(numerator) / Decimal(denominator))


def round_half_up(numerator, denominator=1):
    """Round a quotient to the nearest whole cent, halves upward."""
    quotient = Decimal(numerator) / Decimal(denominator)
    return int(quotient.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_up_to_denomination(value, denomination=constants.AUTHORIZED_DENOMINATION_CENTS):
    """Raise a value to the next whole authorized denomination; never lower it."""
    whole, remainder = divmod(int(value), int(denomination))
    return (whole + (1 if remainder else 0)) * int(denomination)


# ─── Timestamps ───────────────────────────────────────


def parse_instant(value):
    """Read one of the contract's ISO-8601 Z instants."""
    return datetime.strptime(value.replace("Z", ""), "%Y-%m-%dT%H:%M:%S")


def format_instant(moment):
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def add_days(value, days):
    return format_instant(parse_instant(value) + timedelta(days=days))


def add_years(value, years):
    """Add whole calendar years, which is how both covenant horizons are measured."""
    moment = parse_instant(value)
    return format_instant(moment.replace(year=moment.year + int(years)))


def whole_days_between(period_start, period_end):
    """Whole days from an inclusive start up to but not including an exclusive end."""
    return (parse_instant(period_end) - parse_instant(period_start)).days


def next_inspection_due_date(completed_date):
    """The completed date plus 1,095 days — a three-year inspection cycle."""
    return add_days(completed_date, constants.INSPECTION_CYCLE_DAYS)


# ─── The restricted rent ceiling (PRD §3.2) ───────────


def imputed_household_size(bedroom_count):
    """The larger of 1 and one more than the bedroom count."""
    return max(1, int(bedroom_count) + 1)


def effective_band(ami_percent, set_aside_election):
    """The smaller of the unit's elected band and the election's own band cap."""
    return min(int(ami_percent), constants.ELECTION_BAND_CAP[set_aside_election])


def restricted_rent_cents(bedroom_count, ami_percent, set_aside_election,
                          utility_allowance_cents, market_rent_cents):
    """The four-input ceiling, with every division floored at the step the PRD names."""
    household = imputed_household_size(bedroom_count)
    band = effective_band(ami_percent, set_aside_election)
    annual_income = floor_div(
        constants.AMI_ANNUAL_INCOME_CENTS[household] * band, 100
    )
    thirty_percent = floor_div(annual_income * constants.RENT_INCOME_SHARE_PCT, 100)
    monthly_gross = floor_div(thirty_percent, constants.MONTHS_PER_YEAR)
    utility_adjusted = monthly_gross - int(utility_allowance_cents)
    capped = min(utility_adjusted, int(market_rent_cents))
    return max(constants.RENT_FLOOR_CENTS, capped)


# ─── The development's fractions (PRD §3.2) ───────────


def ratio_bps(numerator, denominator):
    """A basis-point ratio: numerator times 10,000 over denominator, floored."""
    return floor_div(int(numerator) * constants.BPS_SCALE, int(denominator))


def unit_fraction_bps(restricted_unit_count, total_units):
    return ratio_bps(restricted_unit_count, total_units)


def floor_space_fraction_bps(restricted_floor_space_sqft, total_floor_space_sqft):
    return ratio_bps(restricted_floor_space_sqft, total_floor_space_sqft)


def applicable_fraction_bps(restricted_unit_count, total_units,
                            restricted_floor_space_sqft, total_floor_space_sqft):
    """The smaller of the unit fraction and the floor-space fraction."""
    return min(
        unit_fraction_bps(restricted_unit_count, total_units),
        floor_space_fraction_bps(restricted_floor_space_sqft, total_floor_space_sqft),
    )


def qualifying_bands(restricted_bands, set_aside_election):
    """The restricted bands at or below the election's qualifying ceiling."""
    ceiling = constants.SET_ASIDE_QUALIFYING_BAND[set_aside_election]
    return [band for band in restricted_bands if int(band) <= ceiling]


def set_aside_ratio_bps(restricted_bands, total_units, set_aside_election):
    return ratio_bps(
        len(qualifying_bands(restricted_bands, set_aside_election)), total_units
    )


def average_band_bps(bands):
    """The average elected band in basis points; an empty set reads as zero."""
    if not bands:
        return 0
    return floor_div(sum(int(band) for band in bands) * 100, len(bands))


def set_aside_satisfied(restricted_bands, total_units, set_aside_election):
    """True when the ratio reaches its threshold and, for AVG_INCOME, the average holds."""
    qualifying = qualifying_bands(restricted_bands, set_aside_election)
    ratio = ratio_bps(len(qualifying), total_units)
    if ratio < constants.SET_ASIDE_THRESHOLD_BPS[set_aside_election]:
        return False
    if set_aside_election != "AVG_INCOME":
        return True
    if not qualifying:
        return False
    return average_band_bps(qualifying) <= constants.AVG_INCOME_AVERAGE_CEILING_BPS


# ─── Bond sizing (PRD §3.5) ───────────────────────────


def provisional_par_cents(eligible_cost_cents, capitalized_interest_cents):
    return int(eligible_cost_cents) + int(capitalized_interest_cents)


def issuance_allowance_cents(eligible_cost_cents, capitalized_interest_cents):
    """Two percent of provisional par, rounded half up, never re-solved."""
    provisional = provisional_par_cents(eligible_cost_cents, capitalized_interest_cents)
    return round_half_up(
        provisional * constants.ISSUANCE_ALLOWANCE_BPS, constants.BPS_SCALE
    )


def par_amount_cents(eligible_cost_cents, capitalized_interest_cents):
    """Provisional par plus the allowance, lifted to the next 500,000 cents."""
    provisional = provisional_par_cents(eligible_cost_cents, capitalized_interest_cents)
    allowance = issuance_allowance_cents(
        eligible_cost_cents, capitalized_interest_cents
    )
    return round_up_to_denomination(provisional + allowance)


def negative_arbitrage_allowance_cents(par_cents):
    """Two hundred basis points of the final par, floored."""
    return floor_div(
        int(par_cents) * constants.NEGATIVE_ARBITRAGE_ALLOWANCE_BPS, constants.BPS_SCALE
    )


def bond_sizing(eligible_cost_cents=constants.ELIGIBLE_COST_CENTS,
                capitalized_interest_cents=constants.CAPITALIZED_INTEREST_CENTS):
    """Every solved sizing figure, in the order the PRD solves them."""
    par = par_amount_cents(eligible_cost_cents, capitalized_interest_cents)
    return {
        "issuance_allowance_cents": issuance_allowance_cents(
            eligible_cost_cents, capitalized_interest_cents
        ),
        "par_amount_cents": par,
        "negative_arbitrage_allowance_cents": negative_arbitrage_allowance_cents(par),
    }


def fifty_percent_ratio_bps(numerator_cents, aggregate_basis_cents):
    """Either variant of the fifty-percent test: numerator over basis, floored."""
    return ratio_bps(numerator_cents, aggregate_basis_cents)


def fifty_percent_test_passes(ratio_bps_value):
    """The passing side is inclusive, so exactly 5,000 basis points triggers credit."""
    return int(ratio_bps_value) >= constants.FIFTY_PERCENT_THRESHOLD_BPS


# ─── The negative-arbitrage series (PRD §3.6) ─────────


def spread_bps(bond_yield_bps, investment_yield_bps):
    """The larger of zero and the bond yield less the investment yield."""
    return max(0, int(bond_yield_bps) - int(investment_yield_bps))


def negative_arbitrage_series(par_cents, bond_yield_bps, investment_yield_bps, draws):
    """Walk the funded draws by period start, rounding each accrual before summing.

    ``draws`` is a sequence of mappings carrying ``period_start``, ``period_end``,
    ``approved_amount_cents`` and ``draw_number``. The return value is the list of
    per-draw accruals in walk order and their total — summing unrounded accruals
    and rounding once at the end is a different and wrong answer.
    """
    spread = spread_bps(bond_yield_bps, investment_yield_bps)
    ordered = sorted(
        draws, key=lambda draw: (parse_instant(draw["period_start"]), draw["draw_number"])
    )
    running_total = 0
    accruals = []
    for draw in ordered:
        undrawn_before = int(par_cents) - running_total
        days = whole_days_between(draw["period_start"], draw["period_end"])
        accrual = round_half_up(
            undrawn_before * spread * days,
            constants.BPS_SCALE * constants.ARBITRAGE_DAYS_PER_YEAR,
        )
        accruals.append((draw["draw_number"], accrual))
        running_total += int(draw["approved_amount_cents"])
    return accruals, sum(accrual for _, accrual in accruals)


def negative_arbitrage_total(par_cents, bond_yield_bps, investment_yield_bps, draws):
    return negative_arbitrage_series(
        par_cents, bond_yield_bps, investment_yield_bps, draws
    )[1]


# ─── Conversion (PRD §3.7) ────────────────────────────


def conversion_window(operating_months, dscr_basis):
    """The last entries of the month-index ordering that the chosen basis needs."""
    size = (
        constants.T3_WINDOW_MONTHS
        if dscr_basis == "T3"
        else constants.T12_WINDOW_MONTHS
    )
    ordered = sorted(operating_months, key=lambda month: month["month_index"])
    return ordered[-size:]


def annualization_factor(dscr_basis):
    return (
        constants.T3_ANNUALIZATION if dscr_basis == "T3" else constants.T12_ANNUALIZATION
    )


def dscr_bps(operating_months, dscr_basis):
    """Annualized coverage over the window, floored to a whole basis point."""
    window = conversion_window(operating_months, dscr_basis)
    factor = annualization_factor(dscr_basis)
    annualized_noi = sum(int(month["noi_cents"]) for month in window) * factor
    annualized_debt_service = (
        sum(int(month["debt_service_cents"]) for month in window) * factor
    )
    return ratio_bps(annualized_noi, annualized_debt_service)


def min_occupancy_bps(operating_months, total_units, dscr_basis):
    """The weakest month's occupancy in the window, each month floored first."""
    window = conversion_window(operating_months, dscr_basis)
    return min(ratio_bps(month["occupied_units"], total_units) for month in window)


# ─── Credit (PRD §3.8) ────────────────────────────────


def per_unit_qualified_basis_cents(certified_eligible_basis_cents, floor_space_sqft,
                                   total_floor_space_sqft):
    """One unit's share of the audited eligible basis, floored for that unit."""
    return floor_div(
        int(certified_eligible_basis_cents) * int(floor_space_sqft),
        int(total_floor_space_sqft),
    )


def qualified_basis_cents(certified_eligible_basis_cents, restricted_floor_spaces,
                         total_floor_space_sqft):
    """The sum of the already-floored per-unit figures, unit by unit."""
    return sum(
        per_unit_qualified_basis_cents(
            certified_eligible_basis_cents, sqft, total_floor_space_sqft
        )
        for sqft in restricted_floor_spaces
    )


def annual_credit_cents(qualified_basis, credit_percentage_bps):
    """The qualified basis at the credit percentage, rounded half up."""
    return round_half_up(
        int(qualified_basis) * int(credit_percentage_bps), constants.BPS_SCALE
    )


def total_credit_cents(annual_credit):
    return int(annual_credit) * constants.CREDIT_PERIOD_YEARS


def price_per_credit_dollar_bps(capital_contribution_cents, delivered_credit_cents):
    """The contribution over the clamped delivered credit, floored."""
    return ratio_bps(capital_contribution_cents, delivered_credit_cents)


def delivered_credit_cents(requested_credit_cents, undelivered_remainder_cents):
    """An over-ask is clamped down to the remainder rather than rejected."""
    return min(int(requested_credit_cents), int(undelivered_remainder_cents))


def recapture_amount_cents(annual_credit_cents_value, shortfall_bps_value):
    """The annual credit at the triggering report's shortfall, rounded half up."""
    return round_half_up(
        int(annual_credit_cents_value) * int(shortfall_bps_value), constants.BPS_SCALE
    )


# ─── Annual compliance (PRD §3.9) ─────────────────────


def achieved_set_aside_bps(restricted_units_occupied, total_units):
    return ratio_bps(restricted_units_occupied, total_units)


def shortfall_bps(set_aside_election, achieved_bps):
    """The larger of zero and the required threshold less the achieved ratio."""
    required = constants.SET_ASIDE_THRESHOLD_BPS[set_aside_election]
    return max(0, required - int(achieved_bps))


# ─── Field and envelope assertions ────────────────────


def assert_fields(data, label="row", **expected):
    """Assert an exact value for each named field, reporting all mismatches."""
    missing = [field for field in expected if field not in data]
    assert not missing, "{0} is missing fields {1}; got {2}".format(
        label, sorted(missing), sorted(data.keys())
    )
    mismatches = [
        "{0} expected {1!r}, got {2!r}".format(field, value, data[field])
        for field, value in expected.items()
        if data[field] != value
    ]
    assert not mismatches, "{0}: {1}".format(label, "; ".join(sorted(mismatches)))


def assert_has_fields(data, fields, label="row"):
    """Assert the response exposes every field the contract publishes for it."""
    missing = [field for field in fields if field not in data]
    assert not missing, "{0} is missing fields {1}; got {2}".format(
        label, sorted(missing), sorted(data.keys())
    )


def assert_common_properties(data, label="row"):
    """The quartet every one of the fourteen resource types carries (PRD §2.4)."""
    assert_has_fields(data, constants.COMMON_FIELDS, label)
    assert isinstance(data["version"], int), "{0}.version must be an integer".format(
        label
    )
    for field in ("created_at", "updated_at"):
        assert data[field].endswith("Z"), "{0}.{1} must be a UTC instant, got {2!r}".format(
            label, field, data[field]
        )


def assert_nulls(data, fields, label="row"):
    """Assert every named field reads null, which several initial states require."""
    non_null = {
        field: data.get(field, "<absent>") for field in fields if data.get(field) is not None
    }
    assert not non_null, "{0} expected nulls at {1}".format(label, non_null)


def assert_version(data, expected_version, label="row"):
    assert data["version"] == expected_version, (
        "{0}.version expected {1}, got {2}".format(label, expected_version, data["version"])
    )


def assert_version_unchanged(before, after, label="row"):
    assert after["version"] == before["version"], (
        "{0}.version should not have moved from {1}, got {2}".format(
            label, before["version"], after["version"]
        )
    )


def assert_version_advanced_by(before, after, steps, label="row"):
    assert after["version"] == before["version"] + steps, (
        "{0}.version expected {1} after {2} mutation(s), got {3}".format(
            label, before["version"] + steps, steps, after["version"]
        )
    )


def assert_page(response, total_count=None, has_more=None, limit=None, offset=None):
    """Validate the pagination envelope of PRD §2.3 and its counters."""
    items, meta = validate_paginated(response)
    if total_count is not None:
        assert meta["total_count"] == total_count, (
            "meta.total_count expected {0}, got {1}".format(
                total_count, meta["total_count"]
            )
        )
    if has_more is not None:
        assert meta["has_more"] is has_more, "meta.has_more expected {0}, got {1!r}".format(
            has_more, meta["has_more"]
        )
    if limit is not None:
        assert meta["limit"] == limit, "meta.limit expected {0}, got {1}".format(
            limit, meta["limit"]
        )
    if offset is not None:
        assert meta["offset"] == offset, "meta.offset expected {0}, got {1}".format(
            offset, meta["offset"]
        )
    return items, meta


def assert_ids_equal(items, expected_ids, label="collection"):
    actual = [item["id"] for item in items]
    assert actual == list(expected_ids), "{0} expected ids {1}, got {2}".format(
        label, list(expected_ids), actual
    )


def assert_contains_id(items, expected_id, label="collection"):
    actual = [item["id"] for item in items]
    assert expected_id in actual, "{0} should contain {1}, got {2}".format(
        label, expected_id, actual
    )


def assert_excludes_id(items, unexpected_id, label="collection"):
    actual = [item["id"] for item in items]
    assert unexpected_id not in actual, "{0} should exclude {1}, got {2}".format(
        label, unexpected_id, actual
    )


def assert_ordered_by(items, field, label="collection"):
    values = [item[field] for item in items]
    assert values == sorted(values), "{0} should be ordered by {1}, got {2}".format(
        label, field, values
    )


# ─── The three conservation identities (PRD §2.9) ─────


def assert_pool_conservation(pool, label="cap_pool"):
    """Total cap equals available plus reserved plus committed, and the status follows."""
    assert pool["total_cap_cents"] == pool["base_cap_cents"] + pool["carryforward_cents"], (
        "{0}.total_cap_cents must be the base cap plus the carryforward".format(label)
    )
    identity = pool["available_cents"] + pool["reserved_cents"] + pool["committed_cents"]
    assert identity == pool["total_cap_cents"], (
        "{0}: available {1} + reserved {2} + committed {3} = {4}, not the total cap {5}".format(
            label,
            pool["available_cents"],
            pool["reserved_cents"],
            pool["committed_cents"],
            identity,
            pool["total_cap_cents"],
        )
    )
    assert pool["awardable_cents"] == pool["total_cap_cents"] - pool["committed_cents"], (
        "{0}.awardable_cents must be the total cap less the committed amount".format(label)
    )
    if pool["awardable_cents"] <= 0:
        expected_status = "EXHAUSTED"
    elif pool["available_cents"] < 0:
        expected_status = "OVERSUBSCRIBED"
    else:
        expected_status = "OPEN"
    assert pool["pool_status"] == expected_status, (
        "{0}.pool_status expected {1} for awardable {2} and available {3}, got {4}".format(
            label,
            expected_status,
            pool["awardable_cents"],
            pool["available_cents"],
            pool["pool_status"],
        )
    )


def assert_pool_ledger(pool, reserved_cents=None, committed_cents=None,
                       available_cents=None, awardable_cents=None, pool_status=None,
                       label="cap_pool"):
    """Pin whichever of the six derived pool figures the test cares about."""
    expected = {}
    if reserved_cents is not None:
        expected["reserved_cents"] = reserved_cents
    if committed_cents is not None:
        expected["committed_cents"] = committed_cents
    if available_cents is not None:
        expected["available_cents"] = available_cents
    if awardable_cents is not None:
        expected["awardable_cents"] = awardable_cents
    if pool_status is not None:
        expected["pool_status"] = pool_status
    assert_fields(pool, label, **expected)
    assert_pool_conservation(pool, label)


def assert_par_conservation(bond_issue, label="bond_issue"):
    """Par always equals cumulative funded plus undrawn."""
    total = bond_issue["cumulative_funded_cents"] + bond_issue["undrawn_cents"]
    assert total == bond_issue["par_amount_cents"], (
        "{0}: funded {1} + undrawn {2} = {3}, not par {4}".format(
            label,
            bond_issue["cumulative_funded_cents"],
            bond_issue["undrawn_cents"],
            total,
            bond_issue["par_amount_cents"],
        )
    )


def assert_credit_conservation(allocation, label="credit_allocation"):
    """Total credit always equals delivered plus undelivered."""
    total = allocation["delivered_credit_cents"] + allocation["undelivered_credit_cents"]
    assert total == allocation["total_credit_cents"], (
        "{0}: delivered {1} + undelivered {2} = {3}, not total {4}".format(
            label,
            allocation["delivered_credit_cents"],
            allocation["undelivered_credit_cents"],
            total,
            allocation["total_credit_cents"],
        )
    )


# ─── Composite domain assertions ──────────────────────


def assert_project_fractions(project, unit_fraction=None, floor_space_fraction=None,
                            applicable_fraction=None, label="project"):
    expected = {}
    if unit_fraction is not None:
        expected["unit_fraction_bps"] = unit_fraction
    if floor_space_fraction is not None:
        expected["floor_space_fraction_bps"] = floor_space_fraction
    if applicable_fraction is not None:
        expected["applicable_fraction_bps"] = applicable_fraction
    assert_fields(project, label, **expected)
    assert project["applicable_fraction_bps"] == min(
        project["unit_fraction_bps"], project["floor_space_fraction_bps"]
    ), "{0}.applicable_fraction_bps must be the smaller of the two fractions".format(label)


def assert_unit_counts(project, restricted=None, market=None, employee=None,
                       designated=None, label="project"):
    expected = {}
    if restricted is not None:
        expected["restricted_unit_count"] = restricted
    if market is not None:
        expected["market_unit_count"] = market
    if employee is not None:
        expected["employee_unit_count"] = employee
    if designated is not None:
        expected["designated_unit_count"] = designated
    assert_fields(project, label, **expected)


def assert_bond_sizing(bond_issue, eligible_cost_cents=None,
                       capitalized_interest_cents=None, label="bond_issue"):
    """Re-solve the sizing from the issue's own inputs and pin all three figures."""
    eligible = (
        bond_issue["eligible_cost_cents"]
        if eligible_cost_cents is None
        else eligible_cost_cents
    )
    capitalized = (
        bond_issue["capitalized_interest_cents"]
        if capitalized_interest_cents is None
        else capitalized_interest_cents
    )
    assert_fields(bond_issue, label, **bond_sizing(eligible, capitalized))


def assert_draw_accruals(draws_by_number, expected_accruals, label="draw"):
    """Pin each funded draw's own stored accrual, keyed by draw number."""
    mismatches = [
        "draw {0} accrual expected {1}, got {2}".format(
            number, accrual, draws_by_number[number]["negative_arbitrage_accrual_cents"]
        )
        for number, accrual in expected_accruals.items()
        if draws_by_number[number]["negative_arbitrage_accrual_cents"] != accrual
    ]
    assert not mismatches, "{0}: {1}".format(label, "; ".join(mismatches))
