"""Thresholds and collection cardinalities probed one unit either side of the line.

The PRD states each comparison's inclusivity explicitly, so every test here fires the
same call twice — once exactly at the stated boundary and once one basis point, one
day or one member away from it.
"""

from decimal import Decimal

from test_helpers import assertions as A
from test_helpers import factories, fixtures
from test_helpers.api_errors import ERR_CLTV_LIMIT_EXCEEDED, ERR_NO_ELIGIBLE_MEASURES
from test_helpers.test_users import COUNTY_OFFICER, PROGRAM_ADMIN, UNDERWRITING_ANALYST


def _parcel_at_principal(client, solar_cost_cents):
    """A 34000000-cent senior lien, so the assessed ratio lands on the 9700 bps cap."""
    fixtures.move_clock(client, fixtures.SIGNING_CLOCK)
    world = {"clock": fixtures.SIGNING_CLOCK}
    world.update(fixtures.seed_catalog(client))
    world.update(fixtures.seed_enrolled_contractor(client))
    world.update(
        fixtures.seed_parcel(
            client,
            payload=factories.property_payload(),
            lien_overrides={"current_balance_cents": 34000000},
        )
    )
    fixtures.open_draft_application(client, world, 20)
    solar = A.expect_created(
        client.add_measure(
            world["application_id"],
            factories.measure_payload(
                world["solar_product_id"],
                fixtures.current_version(client, world),
                solar_cost_cents,
                280000,
            ),
            world["owner_headers"],
        )
    )
    world["solar_measure_id"] = solar["id"]
    hvac = A.expect_created(
        client.add_measure(
            world["application_id"],
            factories.measure_payload(
                world["hvac_product_id"],
                fixtures.current_version(client, world),
                1200000,
                100000,
            ),
            world["owner_headers"],
        )
    )
    world["hvac_measure_id"] = hvac["id"]
    A.expect_ok(client.submit_application(world["application_id"], world["owner_headers"]))
    return world


def test_the_combined_ratio_passes_at_exactly_9700_basis_points(client):
    """Underwriting proceeds on a ratio that lands exactly on the stated cap.

    It must be at most 9700 basis points; exactly 9700 passes and 9701 fails.

    Design: Difficulty/boundary_precision_check/cltv_cap_inclusive_at_9700_and_fails_at_9701
    """
    world = _parcel_at_principal(client, 3600000)

    underwritten = A.expect_ok(
        client.underwrite_application(
            world["application_id"],
            factories.underwrite_proceed_payload("ASSESSED"),
            UNDERWRITING_ANALYST,
        )
    )
    A.assert_fields(
        underwritten,
        status="CONSENT_PENDING",
        underwriting_cltv_bps=9700,
        requested_principal_cents=4800000,
        portfolio_sir_bps=13023,
        notified_lien_count=1,
    )
    A.assert_fields(
        fixtures.read_measure(client, world["solar_measure_id"]),
        sir_bps=13544,
        status="APPROVED",
    )
    A.assert_fields(
        fixtures.read_measure(client, world["hvac_measure_id"]),
        sir_bps=11461,
        status="APPROVED",
    )

    report = A.expect_ok(
        client.get_eligibility_report(world["application_id"], UNDERWRITING_ANALYST)
    )
    A.assert_fields(
        report,
        cltv_bps_assessed=9700,
        approved_principal_cents=4800000,
        blocking_error_id=None,
    )


def test_one_basis_point_over_the_cap_is_refused_and_persists_nothing(client):
    """A ratio of 9701 stops the underwrite and leaves the application untouched.

    Comparisons against thresholds are inclusive or exclusive exactly as stated and
    never approximated. A combined lien-to-value ratio of exactly 9700 basis points
    passes; 9701 fails.

    Design: Difficulty/boundary_precision_check/cltv_cap_inclusive_at_9700_and_fails_at_9701
    """
    world = _parcel_at_principal(client, 3604000)

    A.expect_error(
        client.underwrite_application(
            world["application_id"],
            factories.underwrite_proceed_payload("ASSESSED"),
            UNDERWRITING_ANALYST,
        ),
        ERR_CLTV_LIMIT_EXCEEDED,
    )
    A.assert_fields(
        fixtures.read_application(client, world),
        status="UNDER_REVIEW",
        consent_posture="NOT_STARTED",
        notified_lien_count=0,
    )
    A.assert_fields(
        A.expect_ok(client.get_mortgage_lien(world["lien_id"], PROGRAM_ADMIN)),
        consent_response="NOT_NOTIFIED",
    )

    # The report makes the failing boundary observable without persisting anything.
    report = A.expect_ok(
        client.get_eligibility_report(world["application_id"], UNDERWRITING_ANALYST)
    )
    A.assert_fields(
        report,
        cltv_bps_assessed=9701,
        ptv_bps=1201,
        equity_bps=1500,
        approved_principal_cents=4804000,
        portfolio_sir_bps=13012,
        blocking_error_id=ERR_CLTV_LIMIT_EXCEEDED,
    )


def test_submitting_an_empty_measure_collection_is_refused(client):
    """Zero measures is one below the first legal cardinality and nothing is computed.

    Submission requires at least one `PROPOSED` measure and at most five, requires the
    parcel not to be in bankruptcy, requires the parcel's `tax_delinquency_count_36m` to
    be at most 1, and requires `requested_term_years` to be one of 10, 15, 18, 20 or 25
    and to be no greater than the cost-weighted useful life computed in the same call.

    Design: Difficulty/boundary_precision_check/submit_with_zero_measures_empty_collection_boundary
    """
    world = fixtures.seed_program(client)
    fixtures.open_draft_application(client, world, 20)
    opening_version = world["application"]["version"]

    A.expect_error(
        client.submit_application(world["application_id"], world["owner_headers"]),
        ERR_NO_ELIGIBLE_MEASURES,
    )

    application = fixtures.read_application(client, world)
    A.assert_fields(
        application, status="DRAFT", requested_principal_cents=0, version=opening_version
    )
    A.assert_absent_or_none(
        application,
        "weighted_useful_life_years",
        "min_measure_sir_bps",
        "portfolio_sir_bps",
        "screening_cltv_bps",
    )


def test_a_single_measure_is_the_first_legal_collection_size(client):
    """One measure clears the cardinality floor and every submit figure is computed.

    `requested_principal_cents` is set to the sum of `installed_cost_cents` over the
    `PROPOSED` measures, and the combined lien-to-value ratio is computed on the
    assessed basis and stored as `screening_cltv_bps`.

    Design: Difficulty/boundary_precision_check/submit_with_zero_measures_empty_collection_boundary
    """
    world = fixtures.seed_program(client)
    fixtures.open_draft_application(client, world, 20)
    A.expect_error(
        client.submit_application(world["application_id"], world["owner_headers"]),
        ERR_NO_ELIGIBLE_MEASURES,
    )

    fixtures.add_solar_measure(client, world)
    submitted = A.expect_ok(
        client.submit_application(world["application_id"], world["owner_headers"])
    )
    A.assert_fields(
        submitted,
        status="UNDER_REVIEW",
        requested_principal_cents=3000000,
        weighted_useful_life_years=25,
        min_measure_sir_bps=12770,
        portfolio_sir_bps=12770,
        screening_cltv_bps=7000,
    )
    # Submit prices the set but classifies nothing.
    A.assert_fields(
        fixtures.read_measure(client, world["solar_measure_id"]),
        pv_savings_cents=3830892,
        sir_bps=12770,
        status="PROPOSED",
    )


def _billed_solar_only_assessment(client):
    """A 3084500-cent roll entry whose first installment is BILLED and not yet late."""
    world = fixtures.solar_only_project(client)
    A.assert_fields(
        fixtures.read_agreement(client, world),
        financed_amount_cents=3084500,
        annual_installment_cents=314163,
    )
    fixtures.assessed_project(client, world, first_tax_year=2027)
    fixtures.move_clock(client, "2027-10-01T00:00:00Z")
    A.expect_ok(
        client.run_county_roll(
            "06073", factories.roll_run_payload(2027, "2027-10-01"), COUNTY_OFFICER
        )
    )
    rows = fixtures.schedule_of(client, world)
    first = A.find_installment(rows, 2027)
    A.assert_fields(
        first,
        status="BILLED",
        penalty_cents=0,
        months_past_due=0,
        total_due_cents=318163,
        due_on="2027-12-10",
    )
    world["first_installment_id"] = first["id"]
    return world


def test_twenty_nine_days_past_due_yields_zero_whole_months(client):
    """One day short of the first 30-day period leaves the penalty on the bare floor.

    `days_past_due` is the whole number of days from `due_on` to the run's
    `effective_date`; `months_past_due` is that count divided by 30 and **floored**, so
    29 days past due yields 0 and 30 days yields 1.

    Design: Difficulty/boundary_precision_check/delinquency_month_boundary_29_vs_30_days_past_due
    """
    world = _billed_solar_only_assessment(client)
    fixtures.move_clock(client, "2028-01-08T00:00:00Z")
    run = A.expect_ok(
        client.run_county_roll(
            "06073", factories.roll_run_payload(2028, "2028-01-08"), COUNTY_OFFICER
        )
    )
    A.assert_fields(
        run,
        billed_installment_count=1,
        delinquent_installment_count=1,
        total_penalty_cents=31816,
    )

    swept = A.expect_ok(
        client.get_installment(
            world["assessment_id"], world["first_installment_id"], COUNTY_OFFICER
        )
    )
    A.assert_fields(swept, status="DELINQUENT", months_past_due=0, penalty_cents=31816)
    assert A.round_half_up(Decimal(318163) * Decimal(1000) / Decimal(10000)) == 31816

    # One delinquent year is below the two-year referral trigger.
    A.assert_fields(
        fixtures.read_assessment(client, world),
        lien_status="SENIOR_RECORDED",
        accrued_penalty_cents=31816,
        delinquent_installment_count=1,
    )
    A.assert_fields(fixtures.read_property(client, world), tax_delinquency_count_36m=0)


def test_thirty_days_past_due_buys_a_whole_month_of_penalty(client):
    """The thirtieth day adds 150 basis points, costing 4773 cents more than day 29.

    The raw rate is 1000 basis points plus 150 basis points per whole month past due.

    Design: Difficulty/boundary_precision_check/delinquency_month_boundary_29_vs_30_days_past_due
    """
    world = _billed_solar_only_assessment(client)
    fixtures.move_clock(client, "2028-01-09T00:00:00Z")
    run = A.expect_ok(
        client.run_county_roll(
            "06073", factories.roll_run_payload(2028, "2028-01-09"), COUNTY_OFFICER
        )
    )
    A.assert_fields(run, delinquent_installment_count=1, total_penalty_cents=36589)

    swept = A.expect_ok(
        client.get_installment(
            world["assessment_id"], world["first_installment_id"], COUNTY_OFFICER
        )
    )
    A.assert_fields(swept, status="DELINQUENT", months_past_due=1, penalty_cents=36589)
    assert A.round_half_up(Decimal(318163) * Decimal(1150) / Decimal(10000)) == 36589
    assert 36589 - 31816 == 4773

    A.assert_fields(
        fixtures.read_assessment(client, world),
        lien_status="SENIOR_RECORDED",
        accrued_penalty_cents=36589,
    )
    A.assert_fields(fixtures.read_property(client, world), tax_delinquency_count_36m=0)
