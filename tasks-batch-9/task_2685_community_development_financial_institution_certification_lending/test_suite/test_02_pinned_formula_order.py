"""Formulas whose answer depends on the order the platform pins.

The match ledger rounds each pledge before it sums them; the pricing chain
freezes the debt-to-income ratio on the provisional payment and never revisits
it from the contractual rate.
"""

from test_helpers import api_client, fixtures, validate_success
from test_helpers.fixtures import ADMINISTRATOR, SECOND_ADMINISTRATOR, UNDERWRITER

PLEDGES = [
    ("Private Foundation A", "CASH_PRIVATE", 20_000_001, 20_000_001),
    ("Donated Servicing Platform", "IN_KIND", 15_000_001, 7_500_001),
    ("Deferred Bank Pledge", "DEFERRED_PLEDGE", 10_000_001, 7_500_001),
    ("Donated Office Space", "IN_KIND", 30_000_003, 15_000_002),
]


def _award_with_four_pledges():
    """A draft award for 100,000,010 cents at a 50.00 percent match ratio."""
    fixtures.set_clock("2026-09-01T00:00:00Z")
    institution = fixtures.create_institution()
    award = fixtures.open_award_application(
        institution["id"],
        requested_amount_cents=100_000_010,
        match_ratio_pct=50.00,
        period_start="2026-10-01T00:00:00Z",
        period_end="2027-09-30T00:00:00Z",
    )
    commitments = [
        fixtures.pledge_commitment(
            award["id"], source_name=name, source_type=source_type,
            amount_cents=amount_cents, committed_on="2026-08-15T00:00:00Z",
        )
        for name, source_type, amount_cents, _ in PLEDGES
    ]
    return institution, award, commitments


def test_each_pledge_is_rounded_before_the_ledger_sums_them():
    """Per-commitment rounding reaches the requirement exactly; one sum would not.

    PRD: "The rounding order in the match ledger is pinned and is the
    **opposite** of the reserve calculation's. Each commitment is rounded to
    whole cents on its own first, and only the already-rounded per-commitment
    figures are summed into the award's `match_eligible_cents`, which counts
    commitments in `status` `VERIFIED` only — `PLEDGED`, `HELD` and `WITHDRAWN`
    commitments contribute zero."
    PRD: "The order matters by whole cents, and the difference decides real
    outcomes: pledges of 20,000,001 cents of `CASH_PRIVATE`, 15,000,001 of
    `IN_KIND`, 10,000,001 of `DEFERRED_PLEDGE` and 30,000,003 of `IN_KIND`
    round individually to 20,000,001 plus 7,500,001 plus 7,500,001 plus
    15,000,002, totalling 50,000,005 cents, whereas summing the exact products
    first would give 50,000,003.75 and round to 50,000,004 — one cent short of
    a 50,000,005-cent requirement."

    Design: Difficulty/combinatorial_formula/award_match_per_commitment_rounding_order_decides_shortfall
    """
    _, award, commitments = _award_with_four_pledges()
    assert award["required_match_cents"] == 50_000_005

    for commitment, (_, _, _, expected_eligible) in zip(commitments, PLEDGES):
        verified = validate_success(
            api_client.verify_matching_fund_commitment(
                commitment["id"], SECOND_ADMINISTRATOR
            )
        )
        assert verified["status"] == "VERIFIED"
        assert verified["eligible_cents"] == expected_eligible

    settled = validate_success(
        api_client.get_award_application(award["id"], ADMINISTRATOR)
    )
    assert settled["match_eligible_cents"] == 50_000_005
    assert settled["match_shortfall_cents"] == 0


def test_an_unverified_pledge_contributes_nothing_to_the_ledger():
    """Only verified pledges enter the ledger, so the shortfall stays open.

    PRD: "Each commitment is rounded to whole cents on its own first, and only
    the already-rounded per-commitment figures are summed into the award's
    `match_eligible_cents`, which counts commitments in `status` `VERIFIED`
    only — `PLEDGED`, `HELD` and `WITHDRAWN` commitments contribute zero."
    PRD: "`match_shortfall_cents` is then the greater of zero and
    `required_match_cents` less `match_eligible_cents`."

    Design: Difficulty/combinatorial_formula/award_match_per_commitment_rounding_order_decides_shortfall
    """
    _, award, commitments = _award_with_four_pledges()

    for commitment in commitments[:3]:
        validate_success(
            api_client.verify_matching_fund_commitment(
                commitment["id"], SECOND_ADMINISTRATOR
            )
        )

    settled = validate_success(
        api_client.get_award_application(award["id"], ADMINISTRATOR)
    )
    assert settled["match_eligible_cents"] == 35_000_003
    assert settled["match_shortfall_cents"] == 15_000_002


def _priced_loan_scenario():
    """A product admitting both grade B and grade C, and a 690-score borrower."""
    fixtures.set_clock("2026-09-01T00:00:00Z")
    institution = fixtures.create_institution()
    product = fixtures.create_loan_product(
        institution["id"], name="Working Capital Ladder", max_dti_pct=45.00,
    )
    borrower = fixtures.create_geocoded_borrower(
        institution["id"],
        full_name="Alma Reyes",
        street_address="9 Melrose Avenue",
        postal_code="10456",
        household_income_cents=4_824_000,
        area_median_income_cents=7_000_000,
        credit_score=690,
    )
    loan = fixtures.file_loan(
        institution["id"], borrower["id"], product["id"], 3_000_000
    )
    return institution, product, borrower, loan


def test_the_ratio_frozen_on_the_provisional_payment_decides_the_grade():
    """A ratio of 42.91 taken from the provisional payment lands grade B.

    PRD: "`dti_pct` is then one hundred multiplied by the sum of
    `existing_monthly_debt_cents` and `provisional_monthly_payment_cents`,
    divided by `verified_monthly_income_cents`, rounded half up to two decimal
    places. **This value is frozen here** and is never recomputed from the
    contractual rate later in the chain."
    PRD: "Tier `B` requires a non-null score of at least 660 and a `dti_pct` at
    or below 43.00."
    PRD: "`risk_spread_bps` follows mechanically from the grade: 0 basis points
    for `A`, 75 for `B`, 150 for `C`, 275 for `D`, and 200 for `E` — note that
    the credit-invisible tier prices below tier `D`, deliberately rewarding the
    coaching that qualified it."

    Design: Difficulty/combinatorial_formula/loan_pricing_pinned_order_freezes_dti_before_spread
    """
    _, _, _, loan = _priced_loan_scenario()

    priced = validate_success(
        api_client.underwrite_loan(
            loan["id"],
            {
                "verified_monthly_income_cents": 402_000,
                "existing_monthly_debt_cents": 100_000,
                "credit_score_at_underwriting": 690,
            },
            UNDERWRITER,
        )
    )

    assert priced["underwriting_state"] == "UNDERWRITING"
    assert priced["provisional_monthly_payment_cents"] == 72_500
    assert float(priced["dti_pct"]) == 42.91
    assert priced["risk_grade"] == "B"
    assert priced["risk_spread_bps"] == 75


def test_the_contractual_payment_is_requoted_without_disturbing_the_frozen_ratio():
    """The re-quote at 975 basis points does not push the ratio to a lower tier.

    PRD: "`final_rate_bps` is the product's `base_rate_bps` plus
    `risk_spread_bps` minus `ta_discount_bps`."
    PRD: "`monthly_payment_cents` re-quotes the payment at the contractual rate
    using the same simple declining formula as step 1 — one month of simple
    interest on the full requested principal at `final_rate_bps` divided by ten
    thousand and then by twelve, plus the requested principal divided by
    `term_months`, rounded half up to whole cents once. `dti_pct` is
    deliberately left at its step-2 value."
    PRD: "`ta_discount_bps` is a step function on coaching already delivered at
    the moment of underwriting: 25 basis points when the borrower's
    `ta_hours_total` is at least 8.00 hours, and 0 otherwise."

    Design: Difficulty/combinatorial_formula/loan_pricing_pinned_order_freezes_dti_before_spread
    """
    _, _, _, loan = _priced_loan_scenario()

    priced = validate_success(
        api_client.underwrite_loan(
            loan["id"],
            {
                "verified_monthly_income_cents": 402_000,
                "existing_monthly_debt_cents": 100_000,
                "credit_score_at_underwriting": 690,
            },
            UNDERWRITER,
        )
    )

    assert priced["ta_discount_bps"] == 0
    assert priced["final_rate_bps"] == 975
    assert priced["monthly_payment_cents"] == 74_375
    assert float(priced["dti_pct"]) == 42.91
