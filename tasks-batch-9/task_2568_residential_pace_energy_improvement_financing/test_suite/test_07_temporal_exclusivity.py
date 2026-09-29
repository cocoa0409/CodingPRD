"""Two exclusivity windows: tax-year spans on a parcel, and live payoff quotes.

One window is a closed integer interval over years and permits adjacency; the other is
a half-open instant interval padded by a five-day buffer and therefore forbids it. Each
test pins the last refused position and the first accepted one.
"""

from test_helpers import assertions as A
from test_helpers import factories, fixtures
from test_helpers.api_errors import (
    ERR_ASSESSMENT_YEAR_OVERLAP,
    ERR_QUOTE_WINDOW_OVERLAP,
)
from test_helpers.test_users import (
    COMPLIANCE_OFFICER,
    COUNTY_OFFICER,
    FUNDING_OFFICER_RELEASER,
    FUNDING_OFFICER_VERIFIER,
    PROGRAM_ADMIN,
    UNDERWRITING_ANALYST,
)

SECOND_FUNDING_CLOCK = "2026-08-26T00:00:00Z"


def _parcel_with_one_recorded_span(client):
    """A parcel carrying a recorded 2027-2046 span plus a second deal ready to record."""
    world = fixtures.assessed_project(client, first_tax_year=2027)
    owner = world["owner_headers"]
    A.assert_fields(
        world["assessment"],
        first_tax_year=2027,
        final_tax_year=2046,
        original_principal_cents=4314500,
        billing_status="PENDING_ROLL",
    )

    # The first application is terminal at ASSESSED, so the parcel is free to file again.
    app2 = A.expect_created(
        client.open_application(
            factories.application_payload(
                world["property_id"], world["contractor_id"], 20
            ),
            owner,
        )
    )
    measure2 = A.expect_created(
        client.add_measure(
            app2["id"],
            factories.measure_payload(
                world["solar_product_id"],
                A.expect_ok(client.get_application(app2["id"], owner))["version"],
                1000000,
                80000,
            ),
            owner,
        )
    )
    A.expect_ok(client.submit_application(app2["id"], owner))
    A.assert_fields(
        fixtures.read_measure(client, measure2["id"]),
        pv_savings_cents=1393052,
        sir_bps=13931,
    )
    underwritten = A.expect_ok(
        client.underwrite_application(
            app2["id"],
            factories.underwrite_proceed_payload("ASSESSED"),
            UNDERWRITING_ANALYST,
        )
    )
    A.assert_fields(underwritten, underwriting_cltv_bps=7579)
    A.expect_ok(
        client.record_consent_response(
            world["lien_id"], factories.consent_response_payload(), COMPLIANCE_OFFICER
        )
    )
    A.expect_ok(client.approve_application(app2["id"], COMPLIANCE_OFFICER))
    agreement2 = A.expect_created(
        client.issue_agreement(
            factories.agreement_payload(
                app2["id"],
                A.expect_ok(client.get_application(app2["id"], owner))["version"],
                20,
                800,
            ),
            UNDERWRITING_ANALYST,
        )
    )
    A.assert_fields(agreement2, financed_amount_cents=1034500)
    A.expect_ok(
        client.sign_agreement(
            agreement2["id"],
            factories.sign_agreement_payload(world["owner_full_name"]),
            owner,
        )
    )
    fixtures.move_clock(client, SECOND_FUNDING_CLOCK)
    certificate2 = A.expect_created(
        client.file_certificate(
            factories.certificate_payload(app2["id"], [measure2["id"]], 1000000),
            world["contractor_caller"],
        )
    )
    A.expect_ok(
        client.sign_certificate(
            certificate2["id"],
            factories.sign_certificate_payload(world["owner_full_name"]),
            owner,
        )
    )
    A.expect_ok(
        client.verify_certificate(
            certificate2["id"],
            factories.verify_certificate_payload("APPROVE"),
            FUNDING_OFFICER_VERIFIER,
        )
    )
    draw2 = A.expect_created(
        client.request_disbursement(
            factories.disbursement_payload(
                app2["id"], certificate2["id"], world["contractor_id"], 1000000
            ),
            FUNDING_OFFICER_VERIFIER,
        )
    )
    A.expect_ok(client.release_disbursement(draw2["id"], FUNDING_OFFICER_RELEASER))
    A.assert_fields(
        A.expect_ok(client.get_application(app2["id"], owner)), status="FUNDED"
    )

    world["second_application_id"] = app2["id"]
    world["second_agreement_id"] = agreement2["id"]
    return world


def test_a_span_starting_on_the_incumbents_final_year_is_refused(client):
    """The interval is closed, so sharing the endpoint year is already an overlap.

    No other assessment on the same parcel may have a tax-year span overlapping the span
    of the new one, otherwise `ERR_ASSESSMENT_YEAR_OVERLAP` (409).

    Design: Difficulty/resource_temporal_overlap/assessment_tax_year_span_adjacency_allowed_overlap_rejected
    """
    world = _parcel_with_one_recorded_span(client)

    A.expect_error(
        client.record_assessment(
            factories.assessment_payload(world["second_application_id"], 2046),
            COUNTY_OFFICER,
        ),
        ERR_ASSESSMENT_YEAR_OVERLAP,
    )

    rows, meta = A.expect_page(
        client.list_assessments(PROGRAM_ADMIN, {"property_id": world["property_id"]})
    )
    A.assert_total_count(meta, 1)
    assert A.ids_of(rows) == [world["assessment_id"]]
    A.assert_fields(
        A.expect_ok(
            client.get_application(
                world["second_application_id"], world["owner_headers"]
            )
        ),
        status="FUNDED",
    )
    A.assert_fields(
        fixtures.read_property(client, world), recorded_pace_principal_cents=4314500
    )


def test_a_span_starting_the_year_after_the_incumbent_ends_is_accepted(client):
    """Adjacency is legal, and the two rollup terms both grow by the new span.

    The span is the closed integer interval from `first_tax_year` through
    `final_tax_year`; adjacency is allowed, so a new assessment starting in the year
    immediately after a previous one's `final_tax_year` is accepted.

    Design: Difficulty/resource_temporal_overlap/assessment_tax_year_span_adjacency_allowed_overlap_rejected
    """
    world = _parcel_with_one_recorded_span(client)

    second = A.expect_created(
        client.record_assessment(
            factories.assessment_payload(world["second_application_id"], 2047),
            COUNTY_OFFICER,
        )
    )
    A.assert_fields(
        second,
        first_tax_year=2047,
        final_tax_year=2066,
        original_principal_cents=1034500,
        principal_balance_cents=1034500,
        interest_accrual_from="2026-08-26",
        billing_status="PENDING_ROLL",
        lien_status="SENIOR_RECORDED",
    )
    A.assert_fields(
        A.expect_ok(
            client.get_application(
                world["second_application_id"], world["owner_headers"]
            )
        ),
        status="ASSESSED",
    )
    A.assert_fields(
        A.expect_ok(client.get_agreement(world["second_agreement_id"], PROGRAM_ADMIN)),
        status="RECORDED",
    )
    A.assert_fields(
        fixtures.read_property(client, world),
        recorded_pace_principal_cents=5349000,
        committed_pace_principal_cents=5349000,
    )

    rows, meta = A.expect_page(
        client.list_assessments(PROGRAM_ADMIN, {"property_id": world["property_id"]})
    )
    A.assert_total_count(meta, 2)
    spans = sorted((row["first_tax_year"], row["final_tax_year"]) for row in rows)
    assert spans == [(2027, 2046), (2047, 2066)]


def _quoted_assessment_on_the_roll(client):
    """A billed, current assessment carrying one live payoff quote."""
    world = fixtures.assessed_project(client, first_tax_year=2027)
    A.assert_fields(
        world["assessment"],
        original_principal_cents=4314500,
        apr_bps=800,
        term_years=20,
        interest_accrual_from="2026-08-20",
    )
    fixtures.move_clock(client, "2026-09-01T00:00:00Z")
    summary = A.expect_ok(
        client.run_county_roll(
            "06073", factories.roll_run_payload(2027, "2026-09-01"), COUNTY_OFFICER
        )
    )
    A.assert_fields(summary, billed_installment_count=1, delinquent_installment_count=0)
    A.assert_fields(
        fixtures.read_assessment(client, world),
        billing_status="ON_ROLL",
        lien_status="SENIOR_RECORDED",
    )

    fixtures.move_clock(client, "2026-09-05T00:00:00Z")
    fixtures.payoff_quote(client, world, "2026-10-01")
    return world


def test_a_requote_four_days_after_the_quote_lapses_is_still_inside_the_buffer(client):
    """Day four of the five-day buffer is the last refused instant.

    The window is half-open: it begins at `quoted_at` and ends five days after
    `good_through_date`, that end instant excluded.

    Design: Difficulty/resource_temporal_overlap/payoff_quote_window_buffer_forbids_adjacent_requote
    """
    world = _quoted_assessment_on_the_roll(client)

    A.assert_fields(
        world["transfer"],
        status="QUOTED",
        quoted_at="2026-09-05T00:00:00Z",
        good_through_date="2026-10-05",
        payoff_principal_cents=4314500,
        accrued_interest_cents=39717,
        payoff_admin_fee_cents=7500,
        base_payoff_cents=4361717,
        prepayment_premium_bps=200,
        prepayment_premium_cents=87234,
        payoff_total_cents=4448951,
    )

    fixtures.move_clock(client, "2026-10-09T00:00:00Z")
    A.expect_error(
        client.quote_transfer(
            factories.transfer_quote_payload(world["assessment_id"], "2026-11-01"),
            COUNTY_OFFICER,
        ),
        ERR_QUOTE_WINDOW_OVERLAP,
    )

    rows, meta = A.expect_page(
        client.list_assessment_transfers(world["assessment_id"], PROGRAM_ADMIN)
    )
    A.assert_total_count(meta, 1)
    # Nothing but an attempt to record ever expires a quote.
    A.assert_fields(rows[0], id=world["transfer_id"], status="QUOTED")
    A.assert_fields(fixtures.read_assessment(client, world), transfer_status="QUOTED")


def test_the_fifth_day_after_the_quote_lapses_reopens_the_window(client):
    """The excluded end instant is the first legal re-quote, and it re-prices to closing.

    Because of that five-day buffer, back-to-back quotes are forbidden as well as
    overlapping ones.

    Design: Difficulty/resource_temporal_overlap/payoff_quote_window_buffer_forbids_adjacent_requote
    """
    world = _quoted_assessment_on_the_roll(client)

    fixtures.move_clock(client, "2026-10-10T00:00:00Z")
    requote = A.expect_created(
        client.quote_transfer(
            factories.transfer_quote_payload(world["assessment_id"], "2026-11-01"),
            COUNTY_OFFICER,
        )
    )
    A.assert_fields(
        requote,
        status="QUOTED",
        mode="ASSUME_WITH_PROPERTY",
        quoted_at="2026-10-10T00:00:00Z",
        good_through_date="2026-11-09",
        payoff_principal_cents=4314500,
        accrued_interest_cents=69032,
        base_payoff_cents=4391032,
        prepayment_premium_bps=200,
        prepayment_premium_cents=87821,
        payoff_total_cents=4478853,
    )

    rows, meta = A.expect_page(
        client.list_assessment_transfers(
            world["assessment_id"], PROGRAM_ADMIN, {"status": "QUOTED"}
        )
    )
    A.assert_total_count(meta, 2)
    assert sorted(A.ids_of(rows)) == sorted([world["transfer_id"], requote["id"]])
    A.assert_fields(
        fixtures.read_assessment(client, world),
        principal_balance_cents=4314500,
        billing_status="ON_ROLL",
        lien_status="SENIOR_RECORDED",
    )
