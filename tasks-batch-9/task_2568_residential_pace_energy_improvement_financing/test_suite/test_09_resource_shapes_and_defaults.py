"""Creation-time shapes: echoed inputs, applied defaults and server-owned fields.

Each test reads one freshly created row and checks the three kinds of field the program
distinguishes — what the client supplied, what the program defaulted, and what the
program derived — plus the two ways a malformed reference is refused.
"""

from test_helpers import assertions as A
from test_helpers import factories, fixtures
from test_helpers.api_errors import (
    ERR_ASSESSMENT_NOT_FOUND,
    ERR_PRODUCT_NOT_FOUND,
    ERR_VALIDATION,
)
from test_helpers.constants import NON_EXISTENT_UUID
from test_helpers.test_users import COUNTY_OFFICER, PROGRAM_ADMIN


def test_a_freshly_registered_parcel_starts_with_full_equity_and_no_exposure(client):
    """A parcel with no title against it derives 10000 basis points of equity.

    A freshly registered parcel starts with all four of its derived figures at rest:
    `senior_lien_balance_cents` at 0, `equity_ratio_bps` at 10000,
    `recorded_pace_principal_cents` at 0 and `committed_pace_principal_cents` at 0.

    Design: Corner/entities/property_creation_returns_computed_equity_and_zero_exposure
    """
    fixtures.move_clock(client, fixtures.SIGNING_CLOCK)

    parcel = A.expect_created(
        client.register_property(factories.property_payload(), PROGRAM_ADMIN)
    )

    A.assert_resource_envelope(parcel)
    A.assert_version(parcel, 1)
    A.assert_fields(
        parcel,
        apn="06073-118-204-011",
        county_code="06073",
        owner_full_name="Ada Ruiz",
        owner_birth_date="1971-04-09",
        owner_email="ada@example.com",
        occupancy_type="OWNER_OCCUPIED",
        assessed_value_cents=40000000,
        annual_property_tax_cents=420000,
    )
    A.assert_fields(parcel, senior_lien_balance_cents=0, equity_ratio_bps=10000)
    A.assert_parcel_exposure(parcel, 0, 0)


def test_omitted_optionals_take_their_defaults_and_the_lien_moves_the_parcel(client):
    """Defaults are applied, nullables stay null, and the lien re-derives the equity.

    `preferred_language` records the language the owner elected for disclosures — either
    `EN` or `ES` — and defaults to `EN`. Every new lien begins with its consent axis at
    rest: `consent_response` is `NOT_NOTIFIED`, and `consent_application_id`,
    `notified_at`, `consent_deadline_at` and `consent_responded_at` are all null.

    Design: Corner/entities/mortgage_lien_and_product_defaults_applied_when_optionals_omitted
    """
    fixtures.move_clock(client, fixtures.SIGNING_CLOCK)
    parcel = A.expect_created(
        client.register_property(factories.property_payload(), PROGRAM_ADMIN)
    )
    A.assert_fields(
        parcel, preferred_language="EN", tax_delinquency_count_36m=0, in_bankruptcy=False
    )
    A.assert_absent_or_none(parcel, "market_value_cents", "appraisal_effective_on")

    lien = A.expect_created(
        client.record_mortgage_lien(
            factories.mortgage_lien_payload(parcel["id"]), PROGRAM_ADMIN
        )
    )
    A.assert_fields(lien, status="ACTIVE", consent_response="NOT_NOTIFIED")
    A.assert_absent_or_none(
        lien,
        "consent_application_id",
        "notified_at",
        "consent_deadline_at",
        "consent_responded_at",
    )

    product = A.expect_created(
        client.create_product(factories.solar_product_payload(), PROGRAM_ADMIN)
    )
    A.assert_fields(product, requires_permit=True, status="ACTIVE")

    # Recording an active lien immediately re-derives the parcel's two title figures.
    A.assert_fields(
        A.expect_ok(client.get_property(parcel["id"], PROGRAM_ADMIN)),
        senior_lien_balance_cents=25000000,
        equity_ratio_bps=3750,
    )


def test_a_registered_contractor_starts_unenrolled_with_a_clean_slate(client):
    """Registration is the application, not the approval, and every ledger opens at rest.

    Registration lands the contractor in `enrollment_status` `PENDING_REVIEW` with a
    clean slate: `workmanship_score` and `lifetime_workmanship_score` both at 10000 basis
    points, `upheld_open_remedy_count` at 0, and `gross_disbursed_cents`,
    `clawed_back_total_cents` and `net_disbursed_cents` all at 0.

    Design: Corner/entities/contractor_retrieval_returns_stored_and_baseline_scores
    """
    fixtures.move_clock(client, fixtures.SIGNING_CLOCK)
    created = A.expect_created(
        client.create_contractor(factories.contractor_payload(), PROGRAM_ADMIN)
    )

    contractor = A.expect_ok(client.get_contractor(created["id"], PROGRAM_ADMIN))

    A.assert_fields(
        contractor,
        legal_name="Ridgeline Retrofit LLC",
        license_number="CSLB-884120",
        license_expires_on="2030-06-30",
        workmanship_warranty_years=10,
        counties_served=["06073"],
    )
    A.assert_fields(
        contractor,
        enrollment_status="PENDING_REVIEW",
        workmanship_score=10000,
        lifetime_workmanship_score=10000,
        upheld_open_remedy_count=0,
    )
    A.assert_absent_or_none(contractor, "suspension_reason")
    A.assert_contractor_ledger(contractor, 0, 0)
    A.assert_version(contractor, 1)
    assert contractor["updated_at"] == contractor["created_at"]


def test_the_catalog_listing_counts_the_filtered_set_before_paginating(client):
    """total_count describes the match, has_more describes the window.

    `total_count` is the number of rows matching the filters before pagination is
    applied, and `has_more` is true when rows remain beyond the current window.

    Design: Corner/entities/products_listing_paginates_with_total_count_and_has_more
    """
    fixtures.move_clock(client, fixtures.SIGNING_CLOCK)
    A.expect_created(
        client.create_product(factories.solar_product_payload(), PROGRAM_ADMIN)
    )
    A.expect_created(
        client.create_product(factories.hvac_product_payload(), PROGRAM_ADMIN)
    )
    A.expect_created(
        client.create_product(
            factories.product_payload("WINDOWS_LOWE", "WINDOWS", 20, 60000),
            PROGRAM_ADMIN,
        )
    )

    first_rows, first_meta = A.expect_page(
        client.list_products(PROGRAM_ADMIN, {"limit": 2, "offset": 0})
    )
    assert len(first_rows) == 2
    A.assert_page_meta(first_meta, 3, limit=2, offset=0)
    assert first_meta["has_more"] is True

    second_rows, second_meta = A.expect_page(
        client.list_products(PROGRAM_ADMIN, {"limit": 2, "offset": 2})
    )
    assert len(second_rows) == 1
    A.assert_page_meta(second_meta, 3, limit=2, offset=2)
    assert second_meta["has_more"] is False

    filtered_rows, filtered_meta = A.expect_page(
        client.list_products(PROGRAM_ADMIN, {"category": "SOLAR_PV"})
    )
    A.assert_total_count(filtered_meta, 1)
    assert filtered_meta["has_more"] is False
    A.assert_fields(
        filtered_rows[0],
        product_code="SOLAR_PV_ROOF",
        useful_life_years=25,
        max_annual_savings_cents=300000,
        requires_permit=True,
        status="ACTIVE",
    )


def test_reading_an_assessment_that_was_never_recorded_is_a_not_found(client):
    """The path identifier is resolved before anything else can be attempted.

    Every identifier appearing in the request path must resolve to a live row, reporting
    `ERR_PROPERTY_NOT_FOUND`, `ERR_MORTGAGE_LIEN_NOT_FOUND`, `ERR_PRODUCT_NOT_FOUND`,
    `ERR_CONTRACTOR_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_MEASURE_NOT_FOUND`,
    `ERR_AGREEMENT_NOT_FOUND`, `ERR_CERTIFICATE_NOT_FOUND`, `ERR_DISBURSEMENT_NOT_FOUND`,
    `ERR_COMPLAINT_NOT_FOUND`, `ERR_ASSESSMENT_NOT_FOUND`, `ERR_INSTALLMENT_NOT_FOUND` or
    `ERR_TRANSFER_NOT_FOUND` as appropriate — all HTTP 404.

    Design: Corner/entities/assessment_lookup_with_unknown_id_returns_not_found
    """
    fixtures.move_clock(client, fixtures.SIGNING_CLOCK)

    body = A.expect_error(
        client.get_assessment(NON_EXISTENT_UUID, COUNTY_OFFICER),
        ERR_ASSESSMENT_NOT_FOUND,
    )
    assert isinstance(body.get("message"), str) and body["message"]

    _rows, meta = A.expect_page(client.list_assessments(COUNTY_OFFICER))
    A.assert_total_count(meta, 0)


def test_opening_an_application_without_a_contractor_is_a_shape_failure(client):
    """The one missing required field is caught before any row is touched.

    All required body fields present, all types and enum values valid, cents and
    basis-point amounts non-negative, `limit` within 1 through 100 and `offset` at least
    0, and a `market_value_cents` update accompanied by an `appraisal_effective_on`.
    Otherwise `ERR_VALIDATION` (400).

    Design: Corner/entities/application_missing_required_contractor_id_rejected
    """
    world = fixtures.seed_program(client, fixtures.SIGNING_CLOCK)

    A.expect_error(
        client.open_application(
            {"property_id": world["property_id"], "requested_term_years": 20},
            world["owner_headers"],
        ),
        ERR_VALIDATION,
    )

    _rows, meta = A.expect_page(
        client.list_applications(
            PROGRAM_ADMIN, {"property_id": world["property_id"]}
        )
    )
    A.assert_total_count(meta, 0)
    assert meta["has_more"] is False
    A.assert_fields(
        fixtures.read_property(client, world), committed_pace_principal_cents=0
    )
    A.assert_fields(
        fixtures.read_contractor(client, world), enrollment_status="ENROLLED"
    )


def test_an_undeclared_category_and_a_negative_ceiling_are_both_refused(client):
    """Enum membership and sign are both pure shape checks, and neither persists a row.

    Neither kind of field ever accepts a negative value in a request body, and a negative
    cents or basis-point amount is rejected with `ERR_VALIDATION`.

    Design: Corner/entities/product_category_invalid_enum_rejected
    """
    fixtures.move_clock(client, fixtures.SIGNING_CLOCK)

    A.expect_error(
        client.create_product(
            factories.product_payload("GEO_LOOP", "GEOTHERMAL", 30, 400000),
            PROGRAM_ADMIN,
        ),
        ERR_VALIDATION,
    )
    A.expect_error(
        client.create_product(
            factories.product_payload("SOLAR_PV_ROOF", "SOLAR_PV", 25, -1),
            PROGRAM_ADMIN,
        ),
        ERR_VALIDATION,
    )

    _rows, meta = A.expect_page(client.list_products(PROGRAM_ADMIN))
    A.assert_total_count(meta, 0)


def test_a_measure_prices_itself_and_discards_the_clients_own_figures(client):
    """The two computed fields open at zero and are filled by the submit, not the body.

    An accepted measure is stored with `status` `PROPOSED`, with `pv_savings_cents` and
    `sir_bps` both at 0 until the next submit or cure recomputes them, and with the parent
    application's `version` incremented by one.

    Design: Corner/entities/measure_computed_pv_and_sir_input_ignored
    """
    world = fixtures.seed_program(client, fixtures.SIGNING_CLOCK)
    fixtures.open_draft_application(client, world, 20)

    measure = A.expect_created(
        client.add_measure(
            world["application_id"],
            factories.measure_payload(
                world["solar_product_id"],
                fixtures.current_version(client, world),
                3000000,
                220000,
                pv_savings_cents=99999999,
                sir_bps=99999,
            ),
            world["owner_headers"],
        )
    )
    A.assert_fields(measure, pv_savings_cents=0, sir_bps=0, status="PROPOSED")

    submitted = A.expect_ok(
        client.submit_application(world["application_id"], world["owner_headers"])
    )
    A.assert_fields(
        fixtures.read_measure(client, measure["id"]),
        pv_savings_cents=3830892,
        sir_bps=12770,
    )
    A.assert_fields(
        submitted,
        status="UNDER_REVIEW",
        requested_principal_cents=3000000,
        min_measure_sir_bps=12770,
        portfolio_sir_bps=12770,
        weighted_useful_life_years=25,
        screening_cltv_bps=7000,
    )


def test_an_opened_application_ignores_a_body_that_tries_to_own_its_state(client):
    """Identity, version and every computed figure are the program's to set.

    The new application lands in `status` `DRAFT` with `requested_principal_cents` at 0,
    `cure_round_count` at 0, `consent_posture` at `NOT_STARTED`, `notified_lien_count` at
    0, and every computed eligibility figure — `screening_cltv_bps`,
    `underwriting_cltv_bps`, `valuation_basis`, `portfolio_sir_bps`,
    `min_measure_sir_bps` and `weighted_useful_life_years` — null.

    Design: Corner/entities/application_system_fields_and_status_input_ignored
    """
    world = fixtures.seed_program(client, fixtures.SIGNING_CLOCK)
    planted_id = "11111111-1111-4111-8111-111111111111"

    application = A.expect_created(
        client.open_application(
            factories.application_payload(
                world["property_id"],
                world["contractor_id"],
                20,
                id=planted_id,
                version=7,
                status="APPROVED",
                requested_principal_cents=9999999,
            ),
            world["owner_headers"],
        )
    )

    A.assert_resource_envelope(application)
    assert application["id"] != planted_id
    A.assert_version(application, 1)
    assert application["updated_at"] == application["created_at"]
    A.assert_fields(
        application,
        status="DRAFT",
        requested_principal_cents=0,
        cure_round_count=0,
        consent_posture="NOT_STARTED",
        notified_lien_count=0,
        oral_confirmation_required=False,
    )
    A.assert_absent_or_none(
        application,
        "screening_cltv_bps",
        "underwriting_cltv_bps",
        "valuation_basis",
        "portfolio_sir_bps",
        "min_measure_sir_bps",
        "weighted_useful_life_years",
    )


def test_a_measure_naming_a_product_outside_the_catalog_is_a_not_found(client):
    """The body foreign key is resolved after the path and before anything is written.

    Every foreign key supplied in the request body must resolve to a live row, reporting
    the same 404 family (`ERR_PROPERTY_NOT_FOUND`, `ERR_CONTRACTOR_NOT_FOUND`,
    `ERR_PRODUCT_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`, `ERR_CERTIFICATE_NOT_FOUND`,
    `ERR_ASSESSMENT_NOT_FOUND`, `ERR_MEASURE_NOT_FOUND`).

    Design: Corner/entities/measure_with_unknown_product_id_returns_not_found
    """
    world = fixtures.seed_program(client, fixtures.SIGNING_CLOCK)
    fixtures.open_draft_application(client, world, 20)
    opening_version = fixtures.current_version(client, world)

    A.expect_error(
        client.add_measure(
            world["application_id"],
            factories.measure_payload(
                NON_EXISTENT_UUID, opening_version, 3000000, 220000
            ),
            world["owner_headers"],
        ),
        ERR_PRODUCT_NOT_FOUND,
    )

    _rows, meta = A.expect_page(
        client.list_measures(
            world["owner_headers"], {"application_id": world["application_id"]}
        )
    )
    A.assert_total_count(meta, 0)
    # A rejected addition must not consume the optimistic-concurrency version.
    assert fixtures.current_version(client, world) == opening_version
