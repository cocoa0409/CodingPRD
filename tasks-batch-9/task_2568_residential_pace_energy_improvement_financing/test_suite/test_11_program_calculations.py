"""Pinned constants and formulas read back off the rows they were written onto.

Each test drives one calculation to a value that no simpler arithmetic reproduces: a
short-horizon annuity factor, a cost-weighted blend, a fee waterfall, a business-day
walk over a holiday, and the empty-lien branch of the consent posture.
"""

from test_helpers import assertions as A
from test_helpers import factories, fixtures
from test_helpers.api_errors import (
    ERR_APPLICATION_VERSION_CONFLICT,
    ERR_NO_ELIGIBLE_MEASURES,
    ERR_TERM_EXCEEDS_USEFUL_LIFE,
)
from test_helpers.test_users import (
    COMPLIANCE_OFFICER,
    PROGRAM_ADMIN,
    UNDERWRITING_ANALYST,
)

SEPTEMBER_SIGNING_CLOCK = "2026-09-03T00:00:00Z"


def test_a_ten_year_horizon_uses_its_own_factor_and_the_floor_bites_at_9895(client):
    """The short-life factor is 8.5302028368, and 105 basis points short is still short.

    For the five useful lives products may declare, the pinned factors are 8.5302028368 at
    10 years, 11.9379350868 at 15 years, 13.7535130795 at 18 years, 14.8774748605 at 20
    years and 17.4131476913 at 25 years.

    Design: Corner/calculations/annuity_factor_and_sir_floor_constant_applied_to_short_life_product
    """
    fixtures.move_clock(client, fixtures.SIGNING_CLOCK)
    product = A.expect_created(
        client.create_product(
            factories.product_payload("WATER_LOWFLOW_KIT", "WATER_EFFICIENCY", 10, 90000),
            PROGRAM_ADMIN,
        )
    )
    contractor = fixtures.seed_enrolled_contractor(client)

    passing = fixtures.seed_parcel(client, with_senior_lien=False)
    failing = fixtures.seed_parcel(
        client, payload=factories.second_property_payload(), with_senior_lien=False
    )

    ids = {}
    for label, parcel, savings in (
        ("pass", passing, 70000),
        ("fail", failing, 58000),
    ):
        application = A.expect_created(
            client.open_application(
                factories.application_payload(
                    parcel["property_id"], contractor["contractor_id"], 10
                ),
                parcel["owner_headers"],
            )
        )
        measure = A.expect_created(
            client.add_measure(
                application["id"],
                factories.measure_payload(
                    product["id"], application["version"], 500000, savings
                ),
                parcel["owner_headers"],
            )
        )
        A.expect_ok(
            client.submit_application(application["id"], parcel["owner_headers"])
        )
        ids[label] = (application["id"], measure["id"], parcel)

    passing_app, passing_measure, passing_parcel = ids["pass"]
    A.assert_fields(
        fixtures.read_measure(client, passing_measure),
        pv_savings_cents=597114,
        sir_bps=11942,
    )
    cleared = A.expect_ok(
        client.underwrite_application(
            passing_app,
            factories.underwrite_proceed_payload("ASSESSED"),
            UNDERWRITING_ANALYST,
        )
    )
    A.assert_fields(
        cleared,
        status="CONSENT_PENDING",
        portfolio_sir_bps=11942,
        min_measure_sir_bps=11942,
        underwriting_cltv_bps=125,
    )
    A.assert_fields(
        A.expect_ok(
            client.get_property(passing_parcel["property_id"], PROGRAM_ADMIN)
        ),
        equity_ratio_bps=10000,
    )

    failing_app, failing_measure, _failing_parcel = ids["fail"]
    A.assert_fields(
        fixtures.read_measure(client, failing_measure),
        pv_savings_cents=494752,
        sir_bps=9895,
    )
    A.expect_error(
        client.underwrite_application(
            failing_app,
            factories.underwrite_proceed_payload("ASSESSED"),
            UNDERWRITING_ANALYST,
        ),
        ERR_NO_ELIGIBLE_MEASURES,
    )
    A.assert_fields(
        A.expect_ok(client.get_application(failing_app, PROGRAM_ADMIN)),
        status="UNDER_REVIEW",
    )
    A.assert_fields(
        fixtures.read_measure(client, failing_measure), status="PROPOSED"
    )


def test_the_term_cap_reads_the_cost_weighted_blend_and_not_a_plain_mean(client):
    """A 23-year blend admits a 20-year term; an 18-year single measure does not.

    Each measure's `installed_cost_cents` is multiplied by its product's
    `useful_life_years`, those products are summed, the sum is divided by the total
    installed cost of the measure set, and the quotient is truncated toward zero to a whole
    number of years.

    Design: Corner/calculations/weighted_useful_life_blend_gates_requested_term
    """
    world = fixtures.draft_with_two_measures(
        client, fixtures.seed_program(client, fixtures.SIGNING_CLOCK), 20
    )

    blended = A.expect_ok(
        client.submit_application(world["application_id"], world["owner_headers"])
    )
    A.assert_fields(
        blended,
        status="UNDER_REVIEW",
        weighted_useful_life_years=23,
        requested_principal_cents=4200000,
        portfolio_sir_bps=12396,
        min_measure_sir_bps=11461,
    )
    A.assert_fields(
        fixtures.read_measure(client, world["solar_measure_id"]), sir_bps=12770
    )
    A.assert_fields(
        fixtures.read_measure(client, world["hvac_measure_id"]), sir_bps=11461
    )

    fixtures.second_parcel(client, world)
    owner2 = world["second_owner_headers"]
    heat_pump_only = A.expect_created(
        client.open_application(
            factories.application_payload(
                world["second_property_id"], world["contractor_id"], 20
            ),
            owner2,
        )
    )
    A.expect_created(
        client.add_measure(
            heat_pump_only["id"],
            factories.measure_payload(
                world["hvac_product_id"], heat_pump_only["version"], 1200000, 100000
            ),
            owner2,
        )
    )

    A.expect_error(
        client.submit_application(heat_pump_only["id"], owner2),
        ERR_TERM_EXCEEDS_USEFUL_LIFE,
    )
    refused = A.expect_ok(client.get_application(heat_pump_only["id"], owner2))
    A.assert_fields(refused, status="DRAFT")
    A.assert_absent_or_none(refused, "weighted_useful_life_years")


def test_the_waterfall_adds_a_scaled_fee_and_a_flat_fee_and_pays_neither_out(client):
    """105000 of fee is scaled, 9500 is flat, and the installer sees neither.

    `contractor_payable_cents` equals `principal_cents` exactly: program fees are never
    payable to the contractor, so the homeowner finances the fees while the installer sees
    only the cost of the work.

    Design: Corner/calculations/financed_amount_applies_admin_and_recording_fee_constants
    """
    world = fixtures.issued_agreement(client)

    agreement = world["agreement"]
    A.assert_resource_envelope(agreement)
    A.assert_fields(
        agreement,
        principal_cents=4200000,
        admin_fee_cents=105000,
        county_recording_fee_cents=9500,
        financed_amount_cents=4314500,
        contractor_payable_cents=4200000,
        annual_installment_cents=439441,
        term_years=20,
        apr_bps=800,
        status="ISSUED",
        oral_confirmation_required=False,
    )
    A.assert_fee_decomposition(agreement, 4200000)
    for pending in (
        "signature_name",
        "signed_at",
        "rescission_expires_at",
        "effective_at",
    ):
        A.assert_absent_or_none(agreement, pending)


def test_three_business_days_walk_past_a_weekend_and_the_september_holiday(client):
    """Signing on Thursday 2026-09-03 buys the owner until 2026-09-10, not 2026-09-09.

    Step forward one day at a time, counting a day only when it is neither a Saturday nor a
    Sunday nor one of the program holidays, until three such days have been counted.

    Design: Corner/calculations/rescission_window_skips_weekend_and_program_holiday
    """
    world = fixtures.issued_agreement(client)
    fixtures.move_clock(client, SEPTEMBER_SIGNING_CLOCK)

    signed = A.expect_ok(
        client.sign_agreement(
            world["agreement_id"],
            factories.sign_agreement_payload(world["owner_full_name"]),
            world["owner_headers"],
        )
    )

    A.assert_fields(
        signed,
        status="SIGNED",
        signed_at="2026-09-03T00:00:00Z",
        rescission_expires_at="2026-09-10T00:00:00Z",
        oral_confirmation_required=False,
    )
    A.assert_absent_or_none(signed, "oral_confirmation_completed_at")
    A.assert_fields(
        fixtures.read_application(client, world), status="FUNDING_PENDING"
    )
    A.assert_parcel_exposure(fixtures.read_property(client, world), 0, 4314500)


def test_a_parcel_with_nobody_to_notify_clears_its_posture_at_underwriting(client):
    """The empty notified set clears rather than pends, and approval needs no response call.

    A veto outranks everything, and the empty set clears — a free-and-clear parcel with zero
    `ACTIVE` liens has nobody to consent, so its posture is `CLEARED` from the moment of the
    `PROCEED`.

    Design: Corner/calculations/consent_posture_cleared_for_free_and_clear_parcel
    """
    fixtures.move_clock(client, fixtures.SIGNING_CLOCK)
    catalog = fixtures.seed_catalog(client)
    contractor = fixtures.seed_enrolled_contractor(client)
    parcel = fixtures.seed_parcel(client, with_senior_lien=False)

    application = A.expect_created(
        client.open_application(
            factories.application_payload(
                parcel["property_id"], contractor["contractor_id"], 20
            ),
            parcel["owner_headers"],
        )
    )
    stale_version = application["version"]
    A.expect_created(
        client.add_measure(
            application["id"],
            factories.solar_measure_payload(
                catalog["solar_product_id"], stale_version
            ),
            parcel["owner_headers"],
        )
    )
    A.expect_ok(
        client.submit_application(application["id"], parcel["owner_headers"])
    )

    underwritten = A.expect_ok(
        client.underwrite_application(
            application["id"],
            factories.underwrite_proceed_payload("ASSESSED"),
            UNDERWRITING_ANALYST,
        )
    )
    A.assert_fields(
        underwritten,
        status="CONSENT_PENDING",
        consent_posture="CLEARED",
        notified_lien_count=0,
        underwriting_cltv_bps=750,
        requested_principal_cents=3000000,
        portfolio_sir_bps=12770,
    )
    A.assert_absent_or_none(underwritten, "consent_deadline_at")
    _rows, meta = A.expect_page(
        client.list_mortgage_liens(
            PROGRAM_ADMIN, params={"consent_application_id": application["id"]}
        )
    )
    A.assert_total_count(meta, 0)

    approved = A.expect_ok(
        client.approve_application(application["id"], COMPLIANCE_OFFICER)
    )
    A.assert_fields(
        approved,
        status="APPROVED",
        consent_posture="CLEARED",
        approver_user_id="u_comp_1",
        underwriter_user_id="u_ana_1",
    )
    A.assert_fields(
        A.expect_ok(client.get_property(parcel["property_id"], PROGRAM_ADMIN)),
        equity_ratio_bps=10000,
    )

    A.expect_error(
        client.issue_agreement(
            factories.agreement_payload(application["id"], stale_version, 20, 800),
            UNDERWRITING_ANALYST,
        ),
        ERR_APPLICATION_VERSION_CONFLICT,
    )
    _agreements, agreement_meta = A.expect_page(
        client.list_application_agreements(application["id"], PROGRAM_ADMIN)
    )
    A.assert_total_count(agreement_meta, 0)
