"""Derived figures: constants, input sets, precision and threshold ordering."""

from test_helpers import (
    api_client,
    fixtures,
    validate_success,
)
from test_helpers.assertions import assert_posture_matches_ratio
from test_helpers.fixtures import ANALYST, REVIEWER


def test_advisory_credit_stops_exactly_at_the_two_tenths_cap():
    """Half-weight advisory credit is capped, and the divisor spans both boards.

    PRD: "Advisory seats earn partial credit at half weight: the advisory credit
    is the representing advisory count multiplied by one half and divided by the
    **combined** count of governing and advisory seats, and that quotient is then
    capped at 0.2000; when the combined count is zero, the advisory credit is
    zero."
    PRD: "The governing share is the representing governing count divided by the
    total governing count, taken as an exact ratio and not rounded; when there
    are no active governing seats at all, the governing share is treated as zero
    rather than as undefined."

    Design: Corner/calculations/advisory_credit_stops_exactly_at_the_two_tenths_cap
    """
    institution = fixtures.create_institution(ein="210000021")
    institution_id = institution["id"]
    market = fixtures.create_approved_target_market(institution_id)
    fixtures.create_board_seat(
        institution_id, structure="GOVERNING_BOARD",
        holder_name="T. Whitfield", represents_target_market=False,
    )
    fixtures.create_board_seat(
        institution_id, structure="ADVISORY_BOARD", holder_name="R. Alvarez",
        represents_target_market=True, target_market_id=market["id"],
    )
    for holder in ("P. Osei", "J. Ruiz"):
        fixtures.create_board_seat(
            institution_id, structure="ADVISORY_BOARD", holder_name=holder,
            represents_target_market=False,
        )

    before = fixtures.read_institution(institution_id)
    assert float(before["accountability_score"]) == 0.1250

    fixtures.create_board_seat(
        institution_id, structure="ADVISORY_BOARD", holder_name="M. Chen",
        represents_target_market=True, target_market_id=market["id"],
    )

    after = fixtures.read_institution(institution_id)
    assert after["governing_seats_active"] == 1
    assert after["advisory_seats_active"] == 4
    assert float(after["accountability_score"]) == 0.2000
    assert after["accountability_satisfied"] is False


def test_a_resigned_seat_leaves_the_numerator_and_the_denominator_together():
    """Retiring a non-representing seat raises the governing share.

    PRD: "The **accountability representation score** is a weighted measure
    computed over the institution's `ACTIVE` seats only; `RESIGNED` seats leave
    both the numerator and the denominator entirely."
    PRD: "The governing share and the advisory credit are added, the sum is
    capped at a ceiling of 1.0000, and the capped value is rounded half up to
    four decimal places exactly once — never at the intermediate ratios —
    producing `accountability_score`."

    Design: Corner/calculations/resigned_seats_leave_the_numerator_and_the_denominator_together
    """
    institution = fixtures.create_institution(ein="210000022")
    institution_id = institution["id"]
    market = fixtures.create_approved_target_market(institution_id)
    fixtures.seat_representing_governing_board(institution_id, market["id"])
    non_representing = fixtures.create_board_seat(
        institution_id, structure="GOVERNING_BOARD",
        holder_name="T. Whitfield", represents_target_market=False,
    )
    fixtures.create_board_seat(
        institution_id, structure="GOVERNING_BOARD", holder_name="P. Osei",
        represents_target_market=False,
    )

    before = fixtures.read_institution(institution_id)
    assert float(before["accountability_score"]) == 0.5000

    resigned = validate_success(
        api_client.resign_board_seat(
            non_representing["id"],
            fixtures.make_institution_officer_headers(institution_id),
        )
    )
    assert resigned["status"] == "RESIGNED"

    after = fixtures.read_institution(institution_id)
    assert after["governing_seats_active"] == 3
    assert float(after["accountability_score"]) == 0.6667
    assert after["accountability_satisfied"] is True


def test_the_income_percentage_is_rounded_before_the_ceiling_comparison():
    """80.004 reads as 80.00 and clears an 80.00 ceiling; 80.01 does not.

    PRD: "a `LOW_INCOME_TARGETED_POPULATION` matches when the borrower's
    `income_pct_ami` is less than or equal to that market's `ami_threshold_pct`,
    using the already-rounded two-decimal income figure so that a computed 80.004
    reads as 80.00 and satisfies a ceiling of 80.00."
    PRD: "A borrower whose income works out to 80.004 percent of area median
    income is treated as 80.00 percent and therefore satisfies a ceiling of
    80.00."

    Design: Corner/calculations/income_pct_ami_is_rounded_before_the_low_income_threshold_comparison
    """
    institution = fixtures.create_institution(ein="210000023")
    institution_id = institution["id"]
    fixtures.create_approved_target_market(
        institution_id,
        market_type="LOW_INCOME_TARGETED_POPULATION",
        name="Households at or below 80 percent AMI",
        census_tract_codes=[],
        ami_threshold_pct=80.00,
    )
    on_the_threshold = fixtures.create_borrower(
        institution_id, full_name="Maria Ortiz",
        household_income_cents=4_000_200,
        area_median_income_cents=5_000_000, credit_score=700,
    )
    just_over = fixtures.create_borrower(
        institution_id, full_name="Dana Whitfield",
        street_address="44 Willis Avenue", postal_code="10454",
        household_income_cents=4_000_500,
        area_median_income_cents=5_000_000, credit_score=700,
    )

    over = fixtures.geocode_borrower(just_over["id"])
    assert float(over["income_pct_ami"]) == 80.01
    assert over["in_target_market"] is False
    assert over["matched_target_market_type"] is None

    on_threshold = fixtures.geocode_borrower(on_the_threshold["id"])
    assert float(on_threshold["income_pct_ami"]) == 80.00
    assert on_threshold["geocode_state"] == "GEOCODED"
    assert on_threshold["in_target_market"] is True
    assert on_threshold["matched_target_market_type"] == "LOW_INCOME_TARGETED_POPULATION"


def test_attribution_skips_a_draft_market_then_precedence_flips_the_winner():
    """A draft definition never matches; once approved it outranks the incumbent.

    PRD: "Otherwise the candidate set is the target markets of the borrower's own
    institution that are in `state` `APPROVED`; definitions still in `DRAFT`
    never match."
    PRD: "Candidates are ranked by market type, with `INVESTMENT_AREA` taking
    first precedence, `LOW_INCOME_TARGETED_POPULATION` second and
    `OTHER_TARGETED_POPULATION` third, and ties among candidates of the same
    market type broken by `created_at` ascending."
    PRD: "Every attempt increments `geocode_attempts` by 1 regardless of
    outcome, and every attempt advances the borrower's `version` by 1."

    Design: Corner/calculations/attribution_skips_a_draft_market_then_precedence_flips_the_winner
    """
    institution = fixtures.create_institution(ein="210000024")
    institution_id = institution["id"]
    low_income = fixtures.create_approved_target_market(
        institution_id,
        market_type="LOW_INCOME_TARGETED_POPULATION",
        name="Households at or below 80 percent AMI",
        census_tract_codes=[],
        ami_threshold_pct=80.00,
    )
    investment_area = fixtures.create_target_market(institution_id)
    borrower = fixtures.create_borrower(
        institution_id, household_income_cents=4_000_000,
        area_median_income_cents=5_000_000, credit_score=700,
    )

    first_pass = fixtures.geocode_borrower(borrower["id"])
    assert first_pass["in_target_market"] is True
    assert first_pass["matched_target_market_type"] == "LOW_INCOME_TARGETED_POPULATION"

    approved_area = validate_success(
        api_client.approve_target_market(investment_area["id"], REVIEWER)
    )
    assert approved_area["state"] == "APPROVED"

    second_pass = fixtures.geocode_borrower(borrower["id"])
    assert float(second_pass["income_pct_ami"]) == 80.00
    assert second_pass["in_target_market"] is True
    assert second_pass["matched_target_market_type"] == "INVESTMENT_AREA"
    assert second_pass["geocode_attempts"] == 2

    incumbent = validate_success(
        api_client.get_target_market(low_income["id"], ANALYST)
    )
    assert incumbent["state"] == "APPROVED"


def test_thirty_days_past_due_is_the_first_delinquent_day_and_rerates_the_reserve():
    """Twenty-nine days leaves the loan current; the thirtieth re-rates the book.

    PRD: "A recomputed value of 90 days or more assigns `DELINQUENT_90`; at least
    60 but under 90 assigns `DELINQUENT_60`; at least 30 but under 60 assigns
    `DELINQUENT_30`; and under 30 days leaves `servicing_state` unchanged.
    Exactly 30 days past due lands in `DELINQUENT_30`, while 29 days leaves the
    loan `CURRENT`."
    PRD: "Under the migration-analysis basis, roll rates are applied to *current*
    outstanding principal: 2 percent for a `CURRENT` loan, 10 percent for
    `DELINQUENT_30`, 35 percent for `DELINQUENT_60` and 75 percent for
    `DELINQUENT_90`."
    PRD: "a loan whose `vintage_year` equals the calendar year of the current
    logical clock carries a rate of 4.5 percent, and every older vintage carries
    3 percent."

    Design: Corner/calculations/thirty_days_past_due_is_the_first_delinquent_day_and_rerates_the_reserve
    """
    fixtures.set_clock("2026-09-01T00:00:00Z")
    scenario = fixtures.setup_disbursed_loan(
        institution_overrides={"ein": "210000025"},
        requested_principal_cents=1_000_000,
    )
    institution_id = scenario["institution"]["id"]
    loan_id = scenario["loan"]["id"]
    assert scenario["loan"]["next_payment_due_on"] == "2026-10-01"

    fixtures.set_clock("2026-10-30T00:00:00Z")
    after_first_run = fixtures.run_servicing(institution_id)
    assert after_first_run["loss_reserve_required_cents"] == 20_000
    assert float(after_first_run["reserve_coverage_ratio"]) == 0.0000

    still_current = validate_success(api_client.get_loan(loan_id, ANALYST))
    assert still_current["servicing_state"] == "CURRENT"
    assert still_current["days_past_due"] == 29

    fixtures.set_clock("2026-10-31T00:00:00Z")
    after_second_run = fixtures.run_servicing(institution_id)

    delinquent = validate_success(api_client.get_loan(loan_id, ANALYST))
    assert delinquent["days_past_due"] == 30
    assert delinquent["servicing_state"] == "DELINQUENT_30"
    assert delinquent["principal_outstanding_cents"] == 1_000_000

    assert after_second_run["loss_reserve_required_migration_cents"] == 100_000
    assert after_second_run["loss_reserve_required_static_cents"] == 45_000
    assert after_second_run["loss_reserve_required_cents"] == 100_000
    assert float(after_second_run["reserve_coverage_ratio"]) == 0.0000
    assert after_second_run["reserve_deficit_cents"] == 0
    assert after_second_run["compliance_posture"] == "PROBATION"
    assert after_second_run["certification_state"] == "UNCERTIFIED"
    assert_posture_matches_ratio(after_second_run)
