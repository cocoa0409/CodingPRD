"""Boundaries where the answer turns on rounding or on a defined constant.

A dollar-weighted ratio of 59.995 percent is lifted onto an inclusive 60.00
threshold; a lender with nothing live has its coverage ratio pinned rather than
divided by zero.
"""

from test_helpers import api_client, fixtures, validate_success
from test_helpers.fixtures import ANALYST


def _book_with_target_market_principal(target_market_cents, other_cents):
    """Two funded loans inside the same window, one in the market and one out."""
    fixtures.set_clock("2026-09-15T00:00:00Z")
    institution = fixtures.create_institution()
    fixtures.create_approved_target_market(institution["id"])
    product = fixtures.create_loan_product(institution["id"])
    inside = fixtures.create_geocoded_borrower(
        institution["id"], full_name="Maria Ortiz"
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
    fixtures.create_disbursed_loan(
        {"institution": institution, "product": product, "borrower": inside},
        target_market_cents,
    )
    fixtures.create_disbursed_loan(
        {"institution": institution, "product": product, "borrower": outside},
        other_cents,
    )
    fixtures.set_clock("2026-10-01T00:00:00Z")
    return institution


def test_a_ratio_of_fifty_nine_point_nine_nine_five_is_rounded_onto_the_threshold():
    """59.995 percent rounds half up to exactly 60.00, which passes.

    PRD: "`dollar_weighted_pct` is one hundred multiplied by
    `target_market_principal_cents`, divided by `measured_principal_cents`,
    rounded half up to two decimal places."
    PRD: "`selected_pct` is then whichever of the two the measurement's
    `weighting_basis` names, and `verdict` is `PASS` when `selected_pct` is at
    least 60.00 and `FAIL` otherwise — the threshold is inclusive at exactly
    60.00, and the comparison uses the already-rounded percentage."
    PRD: "Every rounding operation in the system uses **round half up** — a
    value exactly at the midpoint rounds away from zero."

    Design: Difficulty/boundary_precision_check/dollar_weighted_pct_rounds_up_onto_the_inclusive_threshold
    """
    institution = _book_with_target_market_principal(5_999_500, 4_000_500)
    measurement = fixtures.open_measurement(
        institution["id"], "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z",
        "DOLLAR_WEIGHTED",
    )

    finalized = validate_success(
        api_client.finalize_compliance_measurement(measurement["id"], ANALYST)
    )

    assert finalized["measured_principal_cents"] == 10_000_000
    assert finalized["target_market_principal_cents"] == 5_999_500
    assert float(finalized["dollar_weighted_pct"]) == 60.00
    assert float(finalized["count_weighted_pct"]) == 50.00
    assert float(finalized["selected_pct"]) == 60.00
    assert finalized["verdict"] == "PASS"
    assert finalized["state"] == "FINALIZED"

    published = validate_success(
        api_client.get_institution(institution["id"], ANALYST)
    )
    assert float(published["target_market_lending_pct"]) == 60.00
    assert published["certification_state"] == "UNCERTIFIED"


def test_a_ratio_of_fifty_nine_point_nine_nine_four_rounds_short_and_fails():
    """One hundred cents lower, the rounded figure lands under the threshold.

    PRD: "`dollar_weighted_pct` is one hundred multiplied by
    `target_market_principal_cents`, divided by `measured_principal_cents`,
    rounded half up to two decimal places."
    PRD: "`selected_pct` is then whichever of the two the measurement's
    `weighting_basis` names, and `verdict` is `PASS` when `selected_pct` is at
    least 60.00 and `FAIL` otherwise — the threshold is inclusive at exactly
    60.00, and the comparison uses the already-rounded percentage."

    Design: Difficulty/boundary_precision_check/dollar_weighted_pct_rounds_up_onto_the_inclusive_threshold
    """
    institution = _book_with_target_market_principal(5_999_400, 4_000_600)
    measurement = fixtures.open_measurement(
        institution["id"], "2026-09-01T00:00:00Z", "2026-10-01T00:00:00Z",
        "DOLLAR_WEIGHTED",
    )

    finalized = validate_success(
        api_client.finalize_compliance_measurement(measurement["id"], ANALYST)
    )

    assert finalized["target_market_principal_cents"] == 5_999_400
    assert float(finalized["dollar_weighted_pct"]) == 59.99
    assert float(finalized["selected_pct"]) == 59.99
    assert finalized["verdict"] == "FAIL"


def test_retiring_the_only_loan_pins_the_coverage_ratio_at_one():
    """An emptied migration base is pinned, not divided into zero.

    PRD: "An institution whose required reserve is exactly zero — a lender with
    no live book at all — has its coverage ratio pinned to 1.0000 rather than
    treated as a division by zero or as 0.0000, and is therefore `COMPLIANT`."
    PRD: "A payment that brings `principal_outstanding_cents` exactly to zero
    retires the loan: `servicing_state` becomes `PAID_OFF`,
    `underwriting_state` becomes `CLOSED`, `next_payment_due_on` is cleared and
    `days_past_due` is set to 0."
    PRD: "Each loan with `principal_disbursed_cents` above zero contributes
    that figure multiplied by its vintage rate, the exact products are summed,
    and the sum is rounded half up to whole cents once, giving
    `loss_reserve_required_static_cents` — loans already `PAID_OFF` or
    `CHARGED_OFF` remain in this base."

    Design: Difficulty/boundary_precision_check/empty_book_reserve_coverage_ratio_pinned_at_one_not_zero
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")
    institution = fixtures.create_institution(
        reserve_method="MIGRATION_ANALYSIS", loss_reserve_balance_cents=0
    )
    institution_id = institution["id"]
    product = fixtures.create_loan_product(institution_id)
    borrower = fixtures.create_geocoded_borrower(institution_id)
    loan = fixtures.create_disbursed_loan(
        {"institution": institution, "product": product, "borrower": borrower},
        1_200_000,
    )

    before = validate_success(api_client.get_institution(institution_id, ANALYST))
    assert before["loss_reserve_required_cents"] == 24_000
    assert float(before["reserve_coverage_ratio"]) == 0.0000
    assert before["compliance_posture"] == "PROBATION"

    retired = validate_success(
        api_client.pay_loan(
            loan["id"], {"amount_cents": 1_200_000},
            fixtures.make_institution_officer_headers(institution_id),
        )
    )
    assert retired["servicing_state"] == "PAID_OFF"
    assert retired["underwriting_state"] == "CLOSED"
    assert retired["principal_outstanding_cents"] == 0

    after = validate_success(api_client.get_institution(institution_id, ANALYST))
    assert after["loss_reserve_required_migration_cents"] == 0
    assert after["loss_reserve_required_static_cents"] == 54_000
    assert after["loss_reserve_required_cents"] == 0
    assert float(after["reserve_coverage_ratio"]) == 1.0000
    assert after["compliance_posture"] == "COMPLIANT"
    assert after["portfolio_principal_outstanding_cents"] == 0


def test_a_lender_that_has_never_lent_is_pinned_at_one_rather_than_at_zero():
    """The pin is a defined constant, so registration already reads compliant.

    PRD: "An institution whose required reserve is exactly zero — a lender with
    no live book at all — has its coverage ratio pinned to 1.0000 rather than
    treated as a division by zero or as 0.0000, and is therefore `COMPLIANT`. A
    newly registered institution begins at `COMPLIANT` with a coverage ratio of
    1.0000."

    Design: Difficulty/boundary_precision_check/empty_book_reserve_coverage_ratio_pinned_at_one_not_zero
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")
    institution = fixtures.create_institution(loss_reserve_balance_cents=0)

    fresh = validate_success(
        api_client.get_institution(institution["id"], ANALYST)
    )
    assert fresh["loss_reserve_required_cents"] == 0
    assert float(fresh["reserve_coverage_ratio"]) == 1.0000
    assert fresh["compliance_posture"] == "COMPLIANT"
