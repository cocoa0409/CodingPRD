"""Determinations the platform computes both ways, with a stored selector.

Target-market lending is measured under dollar and count weighting on one
identical loan set; the required loan-loss reserve is measured under migration
analysis and static-pool vintages on one identical book.
"""

from test_helpers import (
    api_client,
    fixtures,
    validate_success,
)
from test_helpers.fixtures import ANALYST


def _measured_book(census_tract="36005010100"):
    """One lender, one approved investment area, one loan in and one out.

    The in-market loan is 6,000,000 cents and the out-of-market loan is
    4,000,000 cents, both fully advanced inside the measured window.
    """
    fixtures.set_clock("2026-09-15T00:00:00Z")
    institution = fixtures.create_institution()
    market = fixtures.create_approved_target_market(institution["id"])
    product = fixtures.create_loan_product(institution["id"])

    inside = fixtures.create_geocoded_borrower(
        institution["id"], census_tract_code=census_tract, full_name="Maria Ortiz"
    )
    outside = fixtures.create_geocoded_borrower(
        institution["id"],
        census_tract_code="36061019900",
        full_name="Peter Hale",
        street_address="88 Riverside Drive",
        postal_code="10024",
        household_income_cents=9_800_000,
        area_median_income_cents=7_000_000,
        credit_score=760,
    )
    loan_inside = fixtures.create_disbursed_loan(
        {"institution": institution, "product": product, "borrower": inside},
        6_000_000,
    )
    loan_outside = fixtures.create_disbursed_loan(
        {"institution": institution, "product": product, "borrower": outside},
        4_000_000,
    )
    fixtures.set_clock("2026-10-01T00:00:00Z")
    return {
        "institution": institution,
        "target_market": market,
        "loan_inside": loan_inside,
        "loan_outside": loan_outside,
    }


def test_dollar_weighted_window_passes_while_count_weighting_would_fail():
    """A dollar-weighted measurement stores both percentages and selects its own.

    PRD: "Each measurement persists a dollar-weighted percentage in
    `dollar_weighted_pct` and a count-weighted percentage in
    `count_weighted_pct`, and the measurement's `weighting_basis` — either
    `DOLLAR_WEIGHTED` or `COUNT_WEIGHTED` — names which becomes `selected_pct`
    and therefore which decides the verdict."
    PRD: "That the two bases can diverge is not hypothetical: a portfolio of
    one 6,000,000-cent target-market loan and one 4,000,000-cent loan outside
    the target market yields 60.00 under dollar weighting and 50.00 under count
    weighting, which is `PASS` against `FAIL` on identical data."

    Design: Difficulty/dual_variant_calc/target_market_lending_dollar_versus_count_weighted_divergence
    """
    book = _measured_book()
    measurement = fixtures.open_measurement(
        book["institution"]["id"],
        "2026-09-01T00:00:00Z",
        "2026-10-01T00:00:00Z",
        "DOLLAR_WEIGHTED",
    )

    finalized = validate_success(
        api_client.finalize_compliance_measurement(measurement["id"], ANALYST)
    )

    assert finalized["measured_loan_count"] == 2
    assert finalized["target_market_loan_count"] == 1
    assert finalized["measured_principal_cents"] == 10_000_000
    assert finalized["target_market_principal_cents"] == 6_000_000
    assert float(finalized["dollar_weighted_pct"]) == 60.00
    assert float(finalized["count_weighted_pct"]) == 50.00
    assert float(finalized["selected_pct"]) == 60.00
    assert finalized["verdict"] == "PASS"
    assert finalized["state"] == "FINALIZED"


def test_count_weighted_window_fails_the_same_book_and_publishes_its_own_figure():
    """The other basis over the identical window selects 50.00 and fails.

    PRD: "The same portfolio can pass under one basis and fail under the other."
    PRD: "`selected_pct` is then whichever of the two the measurement's
    `weighting_basis` names, and `verdict` is `PASS` when `selected_pct` is at
    least 60.00 and `FAIL` otherwise — the threshold is inclusive at exactly
    60.00, and the comparison uses the already-rounded percentage."
    PRD: "Finalization moves the measurement `DRAFT → FINALIZED`, stamps
    `finalized_at` from the logical clock, copies `selected_pct` into the
    institution's `target_market_lending_pct`, and advances both the
    measurement's `version` and the institution's `version` by 1."

    Design: Difficulty/dual_variant_calc/target_market_lending_dollar_versus_count_weighted_divergence
    """
    book = _measured_book()
    institution_id = book["institution"]["id"]
    dollar = fixtures.open_measurement(
        institution_id, "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z",
        "DOLLAR_WEIGHTED",
    )
    count = fixtures.open_measurement(
        institution_id, "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z",
        "COUNT_WEIGHTED",
    )

    fixtures.finalize_measurement(dollar["id"])
    finalized = validate_success(
        api_client.finalize_compliance_measurement(count["id"], ANALYST)
    )

    assert float(finalized["dollar_weighted_pct"]) == 60.00
    assert float(finalized["count_weighted_pct"]) == 50.00
    assert float(finalized["selected_pct"]) == 50.00
    assert finalized["verdict"] == "FAIL"

    institution = validate_success(
        api_client.get_institution(institution_id, ANALYST)
    )
    assert float(institution["target_market_lending_pct"]) == 50.00


def _diverging_reserve_book(reserve_method):
    """A book of one 1,000,000 CURRENT loan and one 2,000,000 DELINQUENT_90 loan.

    Both loans carry the clock's calendar year as their vintage. The funded
    reserve is left at zero so the coverage ratio is observable.
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")
    institution = fixtures.create_institution(
        reserve_method=reserve_method, loss_reserve_balance_cents=0
    )
    product = fixtures.create_loan_product(institution["id"])
    borrower = fixtures.create_geocoded_borrower(institution["id"])
    scenario = {
        "institution": institution, "product": product, "borrower": borrower,
    }

    delinquent = fixtures.create_disbursed_loan(scenario, 2_000_000)
    fixtures.set_clock("2026-12-31T00:00:00Z")
    fixtures.run_servicing(institution["id"])
    current = fixtures.create_approved_loan(scenario, 1_000_000)

    scenario["delinquent_loan"] = delinquent
    scenario["current_loan"] = current
    return scenario


def test_static_pool_selector_publishes_the_vintage_figure_over_the_roll_rate_figure():
    """Both reserve bases are stored; the static-pool lender is driven by vintages.

    PRD: "Consider a book of one 1,000,000-cent `CURRENT` loan and one
    2,000,000-cent `DELINQUENT_90` loan, both first disbursed in the clock's
    calendar year: the migration basis requires 1,520,000 cents and the
    static-pool basis requires 135,000 cents on identical data."
    PRD: "The institution's `reserve_method`, which is either
    `MIGRATION_ANALYSIS` or `STATIC_POOL` and defaults to `MIGRATION_ANALYSIS`,
    names which of the two is copied into `loss_reserve_required_cents`, and
    only that copied figure drives coverage and posture."
    PRD: "A ratio below 0.8000 is `PROBATION`."

    Design: Difficulty/dual_variant_calc/loss_reserve_migration_versus_static_pool_divergence
    """
    scenario = _diverging_reserve_book("STATIC_POOL")

    validate_success(
        api_client.disburse_loan(
            scenario["current_loan"]["id"],
            {"amount_cents": 1_000_000},
            fixtures.make_institution_officer_headers(
                scenario["institution"]["id"]
            ),
        )
    )

    delinquent = validate_success(
        api_client.get_loan(scenario["delinquent_loan"]["id"], ANALYST)
    )
    assert delinquent["servicing_state"] == "DELINQUENT_90"
    assert delinquent["days_past_due"] == 91

    current = validate_success(
        api_client.get_loan(scenario["current_loan"]["id"], ANALYST)
    )
    assert current["servicing_state"] == "CURRENT"

    institution = validate_success(
        api_client.get_institution(scenario["institution"]["id"], ANALYST)
    )
    assert institution["loss_reserve_required_migration_cents"] == 1_520_000
    assert institution["loss_reserve_required_static_cents"] == 135_000
    assert institution["loss_reserve_required_cents"] == 135_000
    assert institution["portfolio_principal_outstanding_cents"] == 3_000_000
    assert float(institution["reserve_coverage_ratio"]) == 0.0000
    assert institution["compliance_posture"] == "PROBATION"


def test_migration_selector_publishes_the_roll_rate_figure_on_the_identical_book():
    """The same book under the other selector copies the migration variant across.

    PRD: "The institution's required loan-loss reserve is computed under both a
    migration-analysis basis and a static-pool basis, and both results are
    persisted and returned — `loss_reserve_required_migration_cents` and
    `loss_reserve_required_static_cents`."
    PRD: "Consider a book of one 1,000,000-cent `CURRENT` loan and one
    2,000,000-cent `DELINQUENT_90` loan, both first disbursed in the clock's
    calendar year: the migration basis requires 1,520,000 cents and the
    static-pool basis requires 135,000 cents on identical data."

    Design: Difficulty/dual_variant_calc/loss_reserve_migration_versus_static_pool_divergence
    """
    scenario = _diverging_reserve_book("MIGRATION_ANALYSIS")

    validate_success(
        api_client.disburse_loan(
            scenario["current_loan"]["id"],
            {"amount_cents": 1_000_000},
            fixtures.make_institution_officer_headers(
                scenario["institution"]["id"]
            ),
        )
    )

    institution = validate_success(
        api_client.get_institution(scenario["institution"]["id"], ANALYST)
    )
    assert institution["loss_reserve_required_migration_cents"] == 1_520_000
    assert institution["loss_reserve_required_static_cents"] == 135_000
    assert institution["loss_reserve_required_cents"] == 1_520_000
    assert float(institution["reserve_coverage_ratio"]) == 0.0000
    assert institution["compliance_posture"] == "PROBATION"
