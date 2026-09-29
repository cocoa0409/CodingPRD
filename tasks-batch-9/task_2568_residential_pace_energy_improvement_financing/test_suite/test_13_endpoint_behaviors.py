"""Endpoints whose contract is more than a status code: partial patches, previews and runs.

Each one is exercised for the thing that is easy to get wrong — what it recomputes, what it
leaves alone, and what it refuses to persist.
"""

from test_helpers import assertions as A
from test_helpers import factories, fixtures
from test_helpers.api_errors import (
    ERR_ORAL_CONFIRMATION_REQUIRED,
    ERR_PRODUCT_RETIRED,
    ERR_VALIDATION,
)
from test_helpers.test_users import (
    COMPLIANCE_OFFICER,
    COUNTY_OFFICER,
    FUNDING_OFFICER_RELEASER,
    FUNDING_OFFICER_VERIFIER,
    PROGRAM_ADMIN,
    UNDERWRITING_ANALYST,
    contractor_headers,
)

FIRST_BILLING_CLOCK = "2027-12-01T00:00:00Z"
ORAL_RELEASE_CLOCK = "2026-08-19T00:00:00Z"


def test_an_appraisal_needs_its_date_and_only_the_assessed_value_moves_equity(client):
    """A market value alone is refused, a dated one changes no equity, and the assessed value does.

    Filing a market value without the effective date that supports it is refused with
    `ERR_VALIDATION`, because the program cannot judge whether an appraisal is fresh without
    knowing when it was performed.

    Design: Corner/endpoints/valuation_patch_recomputes_equity_and_needs_an_appraisal_date
    """
    fixtures.move_clock(client, fixtures.SIGNING_CLOCK)
    parcel = fixtures.seed_parcel(client, with_senior_lien=False)
    A.assert_fields(parcel["property"], equity_ratio_bps=10000)
    A.expect_created(
        client.record_mortgage_lien(
            factories.mortgage_lien_payload(parcel["property_id"]), PROGRAM_ADMIN
        )
    )
    A.assert_fields(
        A.expect_ok(client.get_property(parcel["property_id"], PROGRAM_ADMIN)),
        senior_lien_balance_cents=25000000,
        equity_ratio_bps=3750,
    )

    A.expect_error(
        client.patch_valuation(
            parcel["property_id"], {"market_value_cents": 50000000}, COUNTY_OFFICER
        ),
        ERR_VALIDATION,
    )
    A.assert_absent_or_none(
        A.expect_ok(client.get_property(parcel["property_id"], PROGRAM_ADMIN)),
        "market_value_cents",
    )

    appraised = A.expect_ok(
        client.patch_valuation(
            parcel["property_id"],
            {"market_value_cents": 50000000, "appraisal_effective_on": "2026-06-01"},
            COUNTY_OFFICER,
        )
    )
    A.assert_fields(
        appraised,
        market_value_cents=50000000,
        appraisal_effective_on="2026-06-01",
        assessed_value_cents=40000000,
        equity_ratio_bps=3750,
    )

    reassessed = A.expect_ok(
        client.patch_valuation(
            parcel["property_id"], {"assessed_value_cents": 50000000}, PROGRAM_ADMIN
        )
    )
    A.assert_fields(
        reassessed,
        assessed_value_cents=50000000,
        equity_ratio_bps=5000,
        senior_lien_balance_cents=25000000,
        market_value_cents=50000000,
        appraisal_effective_on="2026-06-01",
    )


def test_retirement_stops_the_next_measure_and_leaves_the_existing_one_alone(client):
    """A RETIRED product still reads, still lists and still backs the measure it already backs.

    Retiring a product by patching its `status` to `RETIRED` does not disturb existing project
    measures — they keep pointing at it — but a `RETIRED` product may not back a new measure,
    and any measure still pointing at a retired product is forced to `INELIGIBLE` at the next
    underwrite.

    Design: Corner/endpoints/retiring_a_product_blocks_new_measures_only
    """
    world = fixtures.seed_program(client, fixtures.SIGNING_CLOCK)
    fixtures.open_draft_application(client, world, 20)
    fixtures.add_hvac_measure(client, world)
    A.assert_fields(world["hvac_product"], status="ACTIVE")

    retired = A.expect_ok(
        client.patch_product(
            world["hvac_product_id"], {"status": "RETIRED"}, PROGRAM_ADMIN
        )
    )
    A.assert_fields(
        retired,
        status="RETIRED",
        product_code="HVAC_HEATPUMP",
        useful_life_years=18,
        max_annual_savings_cents=120000,
    )

    version = fixtures.current_version(client, world)
    A.expect_error(
        client.add_measure(
            world["application_id"],
            factories.measure_payload(
                world["hvac_product_id"], version, 900000, 80000
            ),
            world["owner_headers"],
        ),
        ERR_PRODUCT_RETIRED,
    )
    A.assert_fields(
        fixtures.read_measure(client, world["hvac_measure_id"]),
        status="PROPOSED",
        product_id=world["hvac_product_id"],
    )

    A.expect_created(
        client.add_measure(
            world["application_id"],
            factories.solar_measure_payload(world["solar_product_id"], version),
            world["owner_headers"],
        )
    )

    _all_rows, all_meta = A.expect_page(client.list_products(PROGRAM_ADMIN))
    A.assert_total_count(all_meta, 2)
    _active_rows, active_meta = A.expect_page(
        client.list_products(PROGRAM_ADMIN, params={"status": "ACTIVE"})
    )
    A.assert_total_count(active_meta, 1)
    A.assert_fields(
        A.expect_ok(client.get_product(world["hvac_product_id"], PROGRAM_ADMIN)),
        status="RETIRED",
    )


def test_the_roll_run_bills_its_year_once_and_a_replay_changes_nothing(client):
    """One scheduled row moves to BILLED, nineteen stay SCHEDULED, and the second run bills zero.

    Every `SCHEDULED` installment whose `tax_year` equals the run's `tax_year`, belonging to an
    assessment on a parcel in that county, moves to `BILLED` with `billed_on` set to the run's
    `effective_date`.

    Design: Corner/endpoints/county_roll_run_bills_the_year_and_skips_already_billed_rows
    """
    world = fixtures.assessed_project(client, fixtures.solar_only_project(client), 2027)
    A.assert_fields(
        fixtures.read_agreement(client, world),
        financed_amount_cents=3084500,
        status="RECORDED",
    )
    A.assert_fields(fixtures.read_application(client, world), status="ASSESSED")
    A.assert_parcel_exposure(
        fixtures.read_property(client, world), 3084500, 3084500
    )

    fixtures.move_clock(client, FIRST_BILLING_CLOCK)
    first_run = A.expect_ok(
        client.run_county_roll(
            "06073", factories.roll_run_payload(2027, "2027-12-01"), COUNTY_OFFICER
        )
    )
    A.assert_fields(
        first_run,
        county_code="06073",
        tax_year=2027,
        effective_date="2027-12-01",
        billed_installment_count=1,
        delinquent_installment_count=0,
        total_penalty_cents=0,
        referred_assessment_ids="",
        voided_transfer_ids="",
        cured_application_ids="",
        incremented_property_ids="",
    )
    A.assert_fields(
        fixtures.read_assessment(client, world),
        billing_status="ON_ROLL",
        lien_status="SENIOR_RECORDED",
        transfer_status="NONE",
    )

    billed_rows, billed_meta = A.expect_page(
        client.list_installments(
            world["assessment_id"], COUNTY_OFFICER, {"tax_year": 2027}
        )
    )
    A.assert_total_count(billed_meta, 1)
    A.assert_installment_row(billed_rows[0], 1, 2027, 67403, 246760)
    A.assert_fields(
        billed_rows[0],
        due_on="2027-12-10",
        total_due_cents=318163,
        status="BILLED",
        billed_on="2027-12-01",
    )
    _scheduled, scheduled_meta = A.expect_page(
        client.list_installments(
            world["assessment_id"], COUNTY_OFFICER, {"status": "SCHEDULED", "limit": 100}
        )
    )
    A.assert_total_count(scheduled_meta, 19)

    second_run = A.expect_ok(
        client.run_county_roll(
            "06073", factories.roll_run_payload(2027, "2027-12-01"), COUNTY_OFFICER
        )
    )
    A.assert_fields(
        second_run, billed_installment_count=0, delinquent_installment_count=0
    )
    replayed, _meta = A.expect_page(
        client.list_installments(
            world["assessment_id"], COUNTY_OFFICER, {"tax_year": 2027}
        )
    )
    A.assert_fields(replayed[0], status="BILLED", billed_on="2027-12-01")
    A.assert_absent_or_none(replayed[0], "paid_on")


def test_the_report_prices_the_surviving_subset_and_persists_nothing(client):
    """The preview drops the weak measure for pricing purposes without touching a single row.

    `approved_principal_cents` is the principal that *would* survive the per-measure gate at
    this instant — measures already stamped `APPROVED`, plus `PROPOSED` measures whose
    `sir_bps` is at least 10000 and whose product is `ACTIVE` — while
    `proposed_principal_cents` sums every `PROPOSED` measure regardless of gate.

    Design: Corner/endpoints/eligibility_report_previews_the_gate_without_writing
    """
    fixtures.move_clock(client, fixtures.SIGNING_CLOCK)
    catalog = fixtures.seed_catalog(client)
    contractor = fixtures.seed_enrolled_contractor(client)
    appraised = fixtures.seed_parcel(
        client,
        payload=factories.property_payload(
            market_value_cents=50000000, appraisal_effective_on="2026-06-01"
        ),
        with_senior_lien=False,
    )
    doomed = fixtures.seed_parcel(
        client, payload=factories.second_property_payload(), with_senior_lien=False
    )

    mixed = A.expect_created(
        client.open_application(
            factories.application_payload(
                appraised["property_id"], contractor["contractor_id"], 20
            ),
            appraised["owner_headers"],
        )
    )
    strong = A.expect_created(
        client.add_measure(
            mixed["id"],
            factories.measure_payload(
                catalog["solar_product_id"], mixed["version"], 3000000, 220000
            ),
            appraised["owner_headers"],
        )
    )
    weak = A.expect_created(
        client.add_measure(
            mixed["id"],
            factories.measure_payload(
                catalog["hvac_product_id"],
                A.expect_ok(
                    client.get_application(mixed["id"], appraised["owner_headers"])
                )["version"],
                1200000,
                58000,
            ),
            appraised["owner_headers"],
        )
    )
    A.expect_ok(client.submit_application(mixed["id"], appraised["owner_headers"]))

    hopeless = A.expect_created(
        client.open_application(
            factories.application_payload(
                doomed["property_id"], contractor["contractor_id"], 18
            ),
            doomed["owner_headers"],
        )
    )
    A.expect_created(
        client.add_measure(
            hopeless["id"],
            factories.measure_payload(
                catalog["hvac_product_id"], hopeless["version"], 1200000, 58000
            ),
            doomed["owner_headers"],
        )
    )
    A.expect_ok(client.submit_application(hopeless["id"], doomed["owner_headers"]))

    report = A.expect_ok(
        client.get_eligibility_report(mixed["id"], UNDERWRITING_ANALYST)
    )
    A.assert_fields(
        report,
        application_id=mixed["id"],
        valuation_basis_applied="ASSESSED",
        appraisal_stale=False,
        approved_principal_cents=3000000,
        proposed_principal_cents=4200000,
        cltv_bps_assessed=750,
        cltv_bps_market=600,
        ptv_bps=750,
        equity_bps=10000,
        portfolio_sir_bps=12770,
        weighted_useful_life_years=23,
        consent_posture="NOT_STARTED",
    )
    A.assert_absent_or_none(report, "blocking_error_id")
    assert "{0}:12770".format(strong["id"]) in report["measure_sir_report"], (
        "the strong measure's ratio is missing from {0}".format(
            report["measure_sir_report"]
        )
    )
    assert "{0}:6648".format(weak["id"]) in report["measure_sir_report"], (
        "the weak measure's ratio is missing from {0}".format(
            report["measure_sir_report"]
        )
    )

    unchanged = A.expect_ok(client.get_application(mixed["id"], UNDERWRITING_ANALYST))
    A.assert_fields(
        unchanged, status="UNDER_REVIEW", requested_principal_cents=4200000
    )
    A.assert_absent_or_none(unchanged, "underwriter_user_id")
    A.assert_fields(fixtures.read_measure(client, strong["id"]), status="PROPOSED")
    A.assert_fields(fixtures.read_measure(client, weak["id"]), status="PROPOSED")

    blocked = A.expect_ok(
        client.get_eligibility_report(hopeless["id"], UNDERWRITING_ANALYST)
    )
    A.assert_fields(
        blocked,
        approved_principal_cents=0,
        proposed_principal_cents=1200000,
        blocking_error_id="ERR_NO_ELIGIBLE_MEASURES",
    )


def test_a_spanish_language_deal_cannot_release_until_the_call_is_logged(client):
    """The closed rescission window is not enough: the recorded call is a second, independent gate.

    Where the agreement's `oral_confirmation_required` is true,
    `oral_confirmation_completed_at` must not be null, or the call fails with
    `ERR_ORAL_CONFIRMATION_REQUIRED`.

    Design: Corner/endpoints/oral_confirmation_call_gates_the_release_for_a_spanish_language_owner
    """
    fixtures.move_clock(client, fixtures.SIGNING_CLOCK)
    catalog = fixtures.seed_catalog(client)
    contractor = fixtures.seed_enrolled_contractor(client)
    parcel = fixtures.seed_parcel(
        client,
        payload=factories.property_payload(preferred_language="ES"),
        with_senior_lien=False,
    )
    owner = parcel["owner_headers"]

    application = A.expect_created(
        client.open_application(
            factories.application_payload(
                parcel["property_id"], contractor["contractor_id"], 20
            ),
            owner,
        )
    )
    A.assert_fields(application, oral_confirmation_required=True)
    measure = A.expect_created(
        client.add_measure(
            application["id"],
            factories.solar_measure_payload(
                catalog["solar_product_id"], application["version"]
            ),
            owner,
        )
    )
    A.expect_ok(client.submit_application(application["id"], owner))
    A.expect_ok(
        client.underwrite_application(
            application["id"],
            factories.underwrite_proceed_payload("ASSESSED"),
            UNDERWRITING_ANALYST,
        )
    )
    approved = A.expect_ok(
        client.approve_application(application["id"], COMPLIANCE_OFFICER)
    )
    agreement = A.expect_created(
        client.issue_agreement(
            factories.agreement_payload(application["id"], approved["version"], 20, 800),
            UNDERWRITING_ANALYST,
        )
    )
    A.assert_fields(
        agreement,
        oral_confirmation_required=True,
        financed_amount_cents=3084500,
        contractor_payable_cents=3000000,
    )
    signed = A.expect_ok(
        client.sign_agreement(
            agreement["id"],
            factories.sign_agreement_payload(parcel["owner_full_name"]),
            owner,
        )
    )
    A.assert_fields(signed, rescission_expires_at="2026-08-18T00:00:00Z")

    certificate = A.expect_created(
        client.file_certificate(
            factories.certificate_payload(
                application["id"], [measure["id"]], 3000000
            ),
            contractor_headers(contractor["contractor_id"]),
        )
    )
    A.expect_ok(
        client.sign_certificate(
            certificate["id"],
            factories.sign_certificate_payload(parcel["owner_full_name"]),
            owner,
        )
    )
    verified = A.expect_ok(
        client.verify_certificate(
            certificate["id"],
            factories.verify_certificate_payload("APPROVE"),
            FUNDING_OFFICER_VERIFIER,
        )
    )
    A.assert_fields(verified, status="VERIFIED", verified_by_user_id="u_fund_v")
    draw = A.expect_created(
        client.request_disbursement(
            factories.disbursement_payload(
                application["id"],
                certificate["id"],
                contractor["contractor_id"],
                3000000,
            ),
            FUNDING_OFFICER_VERIFIER,
        )
    )

    fixtures.move_clock(client, ORAL_RELEASE_CLOCK)
    A.expect_error(
        client.release_disbursement(draw["id"], FUNDING_OFFICER_RELEASER),
        ERR_ORAL_CONFIRMATION_REQUIRED,
    )
    A.assert_fields(
        A.expect_ok(client.get_disbursement(draw["id"], PROGRAM_ADMIN)),
        status="REQUESTED",
    )
    A.assert_contractor_ledger(
        A.expect_ok(
            client.get_contractor(contractor["contractor_id"], PROGRAM_ADMIN)
        ),
        0,
        0,
    )

    logged = A.expect_ok(
        client.record_oral_confirmation(
            agreement["id"],
            factories.oral_confirmation_payload("CALL-8891"),
            COMPLIANCE_OFFICER,
        )
    )
    A.assert_fields(
        logged,
        oral_confirmation_reference="CALL-8891",
        oral_confirmation_completed_at="2026-08-19T00:00:00Z",
        rescission_expires_at="2026-08-18T00:00:00Z",
        status="SIGNED",
    )

    released = A.expect_ok(
        client.release_disbursement(draw["id"], FUNDING_OFFICER_RELEASER)
    )
    A.assert_fields(released, status="RELEASED", released_by_user_id="u_fund_r")
    ledger = A.expect_ok(
        client.get_contractor(contractor["contractor_id"], PROGRAM_ADMIN)
    )
    A.assert_contractor_ledger(ledger, 3000000, 0)
    A.assert_fields(ledger, net_disbursed_cents=3000000)
    A.assert_fields(
        A.expect_ok(client.get_application(application["id"], PROGRAM_ADMIN)),
        status="FUNDED",
    )
    A.assert_fields(
        A.expect_ok(client.get_agreement(agreement["id"], PROGRAM_ADMIN)),
        status="EFFECTIVE",
    )
