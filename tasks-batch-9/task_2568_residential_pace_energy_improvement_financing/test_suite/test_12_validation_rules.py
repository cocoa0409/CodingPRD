"""Field-level and collective limits, each probed on both sides of its line.

The rejections here are all no-ops: nothing is created, no rollup moves, and — where the
program uses optimistic concurrency — the version the caller holds stays usable.
"""

from test_helpers import assertions as A
from test_helpers import factories, fixtures
from test_helpers.api_errors import (
    ERR_CERTIFICATE_ALREADY_DISBURSED,
    ERR_DISBURSEMENT_EXCEEDS_PAYABLE,
    ERR_DUPLICATE_ACTIVE_APPLICATION,
    ERR_INVALID_SUPERSEDE_TARGET,
    ERR_MEASURE_LIMIT_EXCEEDED,
    ERR_SAVINGS_EXCEEDS_PRODUCT_CAP,
    ERR_SIGNATURE_NAME_MISMATCH,
)
from test_helpers.test_users import (
    COMPLIANCE_OFFICER,
    FUNDING_OFFICER_VERIFIER,
    PROGRAM_ADMIN,
    UNDERWRITING_ANALYST,
)

SOLAR_ONLY_FINANCED_CENTS = 3084500


def _issued_on_a_free_and_clear_parcel(client):
    """A solar-only deal with nobody to consent, carried as far as an ISSUED agreement."""
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
    A.expect_created(
        client.add_measure(
            application["id"],
            factories.solar_measure_payload(
                catalog["solar_product_id"], application["version"]
            ),
            parcel["owner_headers"],
        )
    )
    A.expect_ok(client.submit_application(application["id"], parcel["owner_headers"]))
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
    return {
        "property_id": parcel["property_id"],
        "owner_headers": parcel["owner_headers"],
        "owner_full_name": parcel["owner_full_name"],
        "application_id": application["id"],
        "agreement_id": agreement["id"],
        "agreement": agreement,
    }


def test_capitalisation_and_extra_tokens_are_fatal_but_padding_is_trimmed(client):
    """Only the exact owner of record signs, and the ledger moves exactly once.

    The homeowner signs by submitting `signature_name`, which must match the parcel's
    `owner_full_name` exactly — the comparison is case-sensitive after trimming surrounding
    whitespace, so a name that differs only in capitalisation is rejected with
    `ERR_SIGNATURE_NAME_MISMATCH`.

    Design: Corner/validations/agreement_signature_name_must_match_owner_of_record
    """
    world = _issued_on_a_free_and_clear_parcel(client)
    A.assert_fields(
        world["agreement"],
        financed_amount_cents=SOLAR_ONLY_FINANCED_CENTS,
        contractor_payable_cents=3000000,
        annual_installment_cents=314163,
    )

    for wrong_name in ("ada ruiz", "Ada R. Ruiz"):
        A.expect_error(
            client.sign_agreement(
                world["agreement_id"],
                factories.sign_agreement_payload(wrong_name),
                world["owner_headers"],
            ),
            ERR_SIGNATURE_NAME_MISMATCH,
        )

    refused = A.expect_ok(
        client.get_agreement(world["agreement_id"], world["owner_headers"])
    )
    A.assert_fields(refused, status="ISSUED")
    A.assert_absent_or_none(
        refused, "signature_name", "signed_at", "rescission_expires_at"
    )
    A.assert_fields(
        A.expect_ok(client.get_application(world["application_id"], PROGRAM_ADMIN)),
        status="APPROVED",
    )
    A.assert_parcel_exposure(
        A.expect_ok(client.get_property(world["property_id"], PROGRAM_ADMIN)), 0, 0
    )

    signed = A.expect_ok(
        client.sign_agreement(
            world["agreement_id"],
            factories.sign_agreement_payload("  Ada Ruiz  "),
            world["owner_headers"],
        )
    )
    A.assert_fields(
        signed,
        status="SIGNED",
        signed_at="2026-08-12T00:00:00Z",
        rescission_expires_at="2026-08-18T00:00:00Z",
    )
    A.assert_parcel_exposure(
        A.expect_ok(client.get_property(world["property_id"], PROGRAM_ADMIN)),
        0,
        SOLAR_ONLY_FINANCED_CENTS,
    )


def test_a_draft_sibling_blocks_a_new_filing_and_a_supersede_pointer_does_not_help(client):
    """The parcel carries one live application at a time, and only a dead one can be superseded.

    No other application on the parcel may have a status other than `DECLINED`, `WITHDRAWN`
    or `ASSESSED`, otherwise `ERR_DUPLICATE_ACTIVE_APPLICATION` (409).

    Design: Corner/validations/duplicate_active_application_blocked_until_first_one_is_declined
    """
    fixtures.move_clock(client, fixtures.SIGNING_CLOCK)
    catalog = fixtures.seed_catalog(client)
    contractor = fixtures.seed_enrolled_contractor(client)
    parcel = fixtures.seed_parcel(client, with_senior_lien=False)
    owner = parcel["owner_headers"]

    first = A.expect_created(
        client.open_application(
            factories.application_payload(
                parcel["property_id"], contractor["contractor_id"], 20
            ),
            owner,
        )
    )
    second_attempt = factories.application_payload(
        parcel["property_id"], contractor["contractor_id"], 15
    )
    A.expect_error(
        client.open_application(second_attempt, owner), ERR_DUPLICATE_ACTIVE_APPLICATION
    )
    A.expect_error(
        client.open_application(
            factories.application_payload(
                parcel["property_id"],
                contractor["contractor_id"],
                15,
                supersedes_application_id=first["id"],
            ),
            owner,
        ),
        ERR_INVALID_SUPERSEDE_TARGET,
    )

    A.expect_created(
        client.add_measure(
            first["id"],
            factories.solar_measure_payload(
                catalog["solar_product_id"], first["version"]
            ),
            owner,
        )
    )
    A.expect_ok(client.submit_application(first["id"], owner))
    declined = A.expect_ok(
        client.underwrite_application(
            first["id"],
            factories.underwrite_decline_payload("CLTV_LIMIT"),
            UNDERWRITING_ANALYST,
        )
    )
    A.assert_fields(declined, status="DECLINED", decline_reason_code="CLTV_LIMIT")

    replacement = A.expect_created(
        client.open_application(
            factories.application_payload(
                parcel["property_id"],
                contractor["contractor_id"],
                15,
                supersedes_application_id=first["id"],
            ),
            owner,
        )
    )
    A.assert_fields(
        replacement, status="DRAFT", supersedes_application_id=first["id"]
    )

    _dead, dead_meta = A.expect_page(
        client.list_measures(
            PROGRAM_ADMIN,
            params={"application_id": first["id"], "status": "INELIGIBLE"},
        )
    )
    A.assert_total_count(dead_meta, 1)
    _apps, app_meta = A.expect_page(
        client.list_applications(
            PROGRAM_ADMIN, params={"property_id": parcel["property_id"]}
        )
    )
    A.assert_total_count(app_meta, 2)


def test_the_same_savings_figure_passes_one_product_and_breaches_the_other(client):
    """130000 is legal under a 300000 cap and illegal under a 120000 one, and 120000 exactly is legal.

    A measure's `estimated_annual_savings_cents` may not exceed the catalog product's
    `max_annual_savings_cents`, otherwise `ERR_SAVINGS_EXCEEDS_PRODUCT_CAP` (422).

    Design: Corner/validations/savings_cap_is_read_from_the_referenced_product_row
    """
    world = fixtures.seed_program(client, fixtures.SIGNING_CLOCK)
    fixtures.open_draft_application(client, world, 20)
    owner = world["owner_headers"]

    generous = A.expect_created(
        client.add_measure(
            world["application_id"],
            factories.measure_payload(
                world["solar_product_id"],
                world["application"]["version"],
                3000000,
                130000,
            ),
            owner,
        )
    )
    A.assert_fields(generous, estimated_annual_savings_cents=130000, status="PROPOSED")

    version_after_solar = fixtures.current_version(client, world)
    A.expect_error(
        client.add_measure(
            world["application_id"],
            factories.measure_payload(
                world["hvac_product_id"], version_after_solar, 1200000, 130000
            ),
            owner,
        ),
        ERR_SAVINGS_EXCEEDS_PRODUCT_CAP,
    )

    at_the_cap = A.expect_created(
        client.add_measure(
            world["application_id"],
            factories.measure_payload(
                world["hvac_product_id"], version_after_solar, 1200000, 120000
            ),
            owner,
        )
    )
    A.assert_fields(at_the_cap, estimated_annual_savings_cents=120000)

    _rows, meta = A.expect_page(
        client.list_measures(owner, params={"application_id": world["application_id"]})
    )
    A.assert_total_count(meta, 2)
    A.assert_fields(
        fixtures.read_application(client, world), requested_principal_cents=0
    )


def test_the_fifth_measure_is_accepted_and_the_sixth_is_refused_on_count(client):
    """The cardinality limit is exactly five, and it does not consume the version it rejects.

    An application may hold at most 5 project measures, otherwise
    `ERR_MEASURE_LIMIT_EXCEEDED` (422) on measure addition.

    Design: Corner/validations/five_legal_measures_then_sixth_breaches_the_collective_limit
    """
    fixtures.move_clock(client, fixtures.SIGNING_CLOCK)
    catalog = [
        A.expect_created(
            client.create_product(
                factories.product_payload(code, category, 25, 300000), PROGRAM_ADMIN
            )
        )["id"]
        for code, category in (
            ("SOLAR_PV_ROOF", "SOLAR_PV"),
            ("SOLAR_PV_CARPORT", "SOLAR_PV"),
            ("ROOF_COOL_MEMBRANE", "ROOF"),
            ("WINDOWS_TRIPLE_PANE", "WINDOWS"),
            ("WATER_CISTERN", "WATER_EFFICIENCY"),
            ("SOLAR_PV_BATTERY_READY", "SOLAR_PV"),
        )
    ]
    contractor = fixtures.seed_enrolled_contractor(client)
    parcel = fixtures.seed_parcel(client, with_senior_lien=False)
    owner = parcel["owner_headers"]

    application = A.expect_created(
        client.open_application(
            factories.application_payload(
                parcel["property_id"], contractor["contractor_id"], 20
            ),
            owner,
        )
    )
    version = application["version"]
    for product_id in catalog[:5]:
        accepted = A.expect_created(
            client.add_measure(
                application["id"],
                factories.measure_payload(product_id, version, 100000, 10000),
                owner,
            )
        )
        A.assert_fields(accepted, status="PROPOSED", installed_cost_cents=100000)
        version = A.expect_ok(client.get_application(application["id"], owner))["version"]

    A.expect_error(
        client.add_measure(
            application["id"],
            factories.measure_payload(catalog[5], version, 100000, 10000),
            owner,
        ),
        ERR_MEASURE_LIMIT_EXCEEDED,
    )
    _rows, meta = A.expect_page(
        client.list_measures(owner, params={"application_id": application["id"]})
    )
    A.assert_total_count(meta, 5)
    A.assert_fields(
        A.expect_ok(client.get_application(application["id"], owner)), version=version
    )

    submitted = A.expect_ok(client.submit_application(application["id"], owner))
    A.assert_fields(
        submitted,
        status="UNDER_REVIEW",
        requested_principal_cents=500000,
        weighted_useful_life_years=25,
    )


def test_progress_draws_stack_up_to_the_payable_and_then_the_certificate_closes(client):
    """3000000 then 1200000 exactly exhausts a 4200000 payable; 1500000 in between does not fit.

    The sum of `amount_cents` over the application's disbursements in status `REQUESTED`,
    `HELD` or `RELEASED` may not exceed the agreement's `contractor_payable_cents`, otherwise
    `ERR_DISBURSEMENT_EXCEEDS_PAYABLE` (422).

    Design: Corner/validations/progress_draws_are_legal_until_they_breach_the_payable
    """
    world = fixtures.verified_certificate(client)
    A.assert_fields(
        world["agreement"],
        financed_amount_cents=4314500,
        contractor_payable_cents=4200000,
    )

    def draw(amount_cents):
        return client.request_disbursement(
            factories.disbursement_payload(
                world["application_id"],
                world["certificate_id"],
                world["contractor_id"],
                amount_cents,
            ),
            FUNDING_OFFICER_VERIFIER,
        )

    first = A.expect_created(draw(3000000))
    A.assert_fields(first, status="REQUESTED", amount_cents=3000000)

    A.expect_error(draw(1500000), ERR_DISBURSEMENT_EXCEEDS_PAYABLE)
    _rows, meta = A.expect_page(
        client.list_disbursements(
            PROGRAM_ADMIN, params={"application_id": world["application_id"]}
        )
    )
    A.assert_total_count(meta, 1)

    second = A.expect_created(draw(1200000))
    A.assert_fields(second, status="REQUESTED", amount_cents=1200000)

    A.expect_error(draw(1), ERR_CERTIFICATE_ALREADY_DISBURSED)

    A.assert_fields(fixtures.read_application(client, world), status="FUNDING_PENDING")
    A.assert_contractor_ledger(fixtures.read_contractor(client, world), 0, 0)
