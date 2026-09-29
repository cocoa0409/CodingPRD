"""Record shapes: declared defaults, computed fields, listings and rejections."""

from test_helpers import (
    ApiErrorId,
    api_client,
    factories,
    fixtures,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.assertions import (
    assert_borrower,
    assert_institution,
    assert_loan,
    assert_target_market,
)
from test_helpers.constants import TEST_DEFAULTS
from test_helpers.fixtures import ANALYST
from test_helpers.test_users import TEST_USERS

REGISTRAR = TEST_USERS["institution_officer_headers"]
MISSION = TEST_DEFAULTS["MISSION_STATEMENT"]


def test_registering_a_lender_returns_declared_defaults_and_zeroed_ledgers():
    """A freshly registered lender is inert on every derived field.

    PRD: "A freshly registered institution is deliberately inert. Its
    `certification_state` is `UNCERTIFIED` and its `compliance_posture` is
    `COMPLIANT`; `accountability_score` is 0.0000 and `accountability_satisfied`
    is false; `governing_seats_active` and `advisory_seats_active` are both 0;
    `portfolio_principal_outstanding_cents`,
    `portfolio_principal_disbursed_cents`,
    `loss_reserve_required_migration_cents`, `loss_reserve_required_static_cents`,
    `loss_reserve_required_cents` and `reserve_deficit_cents` are all 0;
    `reserve_coverage_ratio` is 1.0000 under the empty-portfolio pin;
    `target_market_lending_pct` is 0.00; `jobs_created_total`,
    `jobs_retained_total`, `housing_units_total` and `businesses_financed_total`
    are all 0; and both `certified_at` and `recertification_due_at` are null."

    Design: Corner/entities/institution_creation_returns_declared_defaults_and_zeroed_ledgers
    """
    created = validate_success(
        api_client.create_institution(
            {
                "legal_name": "Harborline Community Fund",
                "ein": "210000001",
                "entity_type": "CREDIT_UNION",
                "primary_mission_statement": MISSION,
                "asset_size_cents": 250_000_000,
                "reserve_method": "MIGRATION_ANALYSIS",
            },
            REGISTRAR,
        ),
        201,
    )
    assert_institution(created)
    assert created["legal_name"] == "Harborline Community Fund"
    assert created["ein"] == "210000001"
    assert created["entity_type"] == "CREDIT_UNION"
    assert created["asset_size_cents"] == 250_000_000
    assert created["loss_reserve_balance_cents"] == 0
    assert created["certification_state"] == "UNCERTIFIED"
    assert created["compliance_posture"] == "COMPLIANT"
    assert float(created["reserve_coverage_ratio"]) == 1.0000
    assert created["loss_reserve_required_cents"] == 0
    assert created["loss_reserve_required_migration_cents"] == 0
    assert created["loss_reserve_required_static_cents"] == 0
    assert created["reserve_deficit_cents"] == 0
    assert float(created["accountability_score"]) == 0.0000
    assert created["accountability_satisfied"] is False
    assert created["governing_seats_active"] == 0
    assert created["advisory_seats_active"] == 0
    assert created["portfolio_principal_outstanding_cents"] == 0
    assert created["portfolio_principal_disbursed_cents"] == 0
    assert float(created["target_market_lending_pct"]) == 0.00
    assert created["jobs_created_total"] == 0
    assert created["jobs_retained_total"] == 0
    assert created["housing_units_total"] == 0
    assert created["businesses_financed_total"] == 0
    assert created["certified_at"] is None
    assert created["recertification_due_at"] is None
    assert created["version"] == 1


def test_reading_an_underwritten_loan_returns_the_stored_pricing_row():
    """The read surfaces the frozen pricing figures and both lifecycle dimensions.

    PRD: "A **provisional monthly payment** is computed at the product's base
    rate under a simple declining method: one month of simple interest on the
    full requested principal — the requested principal multiplied by the base
    rate expressed as a decimal fraction, meaning `base_rate_bps` divided by ten
    thousand, then divided by twelve — plus straight-line principal, meaning the
    requested principal divided by `term_months`."
    PRD: "`dti_pct` is then one hundred multiplied by the sum of
    `existing_monthly_debt_cents` and `provisional_monthly_payment_cents`,
    divided by `verified_monthly_income_cents`, rounded half up to two decimal
    places."
    PRD: "Tier `A` requires a non-null credit score of at least 720 and a
    `dti_pct` at or below 36.00."

    Design: Corner/entities/loan_retrieval_returns_the_stored_pricing_row
    """
    scenario = fixtures.setup_lending_ready_institution()
    loan = fixtures.file_loan(
        scenario["institution"]["id"], scenario["borrower"]["id"],
        scenario["product"]["id"], 1_000_000,
    )
    fixtures.underwrite_loan(loan["id"])

    read = validate_success(api_client.get_loan(loan["id"], ANALYST))
    assert_loan(read)
    assert float(read["dti_pct"]) == 12.42
    assert read["risk_grade"] == "A"
    assert read["monthly_payment_cents"] == 24_167
    assert read["provisional_monthly_payment_cents"] == 24_167
    assert read["risk_spread_bps"] == 0
    assert read["final_rate_bps"] == 900
    assert read["underwriting_state"] == "UNDERWRITING"
    assert read["servicing_state"] == "NOT_DISBURSED"
    assert read["principal_outstanding_cents"] == 0


def test_the_institution_listing_paginates_with_total_count_and_has_more():
    """Both pages report the same total; only the first reports more to come.

    PRD: "Four pagination fields appear in `meta` on every list response:
    `limit` and `offset` echoing the effective values in force for that page,
    `total_count` giving the number of rows matching the filter across all
    pages, and `has_more` indicating whether any row remains beyond the current
    page."

    Design: Corner/entities/institution_listing_paginates_with_total_count_and_has_more
    """
    fixtures.create_institution(
        legal_name="Harborline Community Fund", ein="210000003"
    )
    fixtures.create_institution(
        legal_name="Riverbend Loan Fund", ein="210000004",
        reserve_method="STATIC_POOL", asset_size_cents=150_000_000,
    )
    fixtures.create_institution(
        legal_name="Foothill Credit Union", ein="210000005",
        entity_type="CREDIT_UNION", asset_size_cents=900_000_000,
    )

    first_page, first_meta = validate_paginated(
        api_client.list_institutions(ANALYST, {"limit": 2, "offset": 0})
    )
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0
    assert len(first_page) == 2

    second_page, second_meta = validate_paginated(
        api_client.list_institutions(ANALYST, {"limit": 2, "offset": 2})
    )
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False
    assert len(second_page) == 1

    filtered, filtered_meta = validate_paginated(
        api_client.list_institutions(ANALYST, {"certification_state": "CERTIFIED"})
    )
    assert filtered_meta["total_count"] == 0
    assert filtered_meta["has_more"] is False
    assert filtered == []


def test_publishing_a_product_without_a_term_is_rejected():
    """A missing required body field is a malformed request.

    PRD: "On every write endpoint, `ERR_INVALID_REQUEST` (HTTP 400) covers a
    missing required body field, a field of the wrong type, an enum value
    outside its declared set, a numeric field outside its declared range, and
    each conditionally required field that is absent while its condition holds."

    Design: Corner/entities/loan_product_creation_missing_term_months_rejected
    """
    institution = fixtures.create_institution(ein="210000006")
    institution_id = institution["id"]
    officer = fixtures.make_institution_officer_headers(institution_id)

    response = api_client.create_loan_product(
        institution_id,
        {
            "name": "Incomplete Product",
            "base_rate_bps": 900,
            "max_dti_pct": 50.00,
            "min_credit_score": 580,
            "allow_no_credit_score": True,
            "credit_building_features": [],
            "requires_ta_completion": False,
            "product_cap_cents": 100_000_000,
        },
        officer,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST)

    _rows, meta = validate_paginated(
        api_client.list_institution_loan_products(institution_id, ANALYST)
    )
    assert meta["total_count"] == 0


def test_a_targeted_population_market_defaults_to_draft_with_no_tract_codes():
    """The tract collection defaults to empty for a non-area market type.

    PRD: "An `INVESTMENT_AREA` is composed of eleven-character tract codes
    supplied in `census_tract_codes`, which must be non-empty for that market
    type and must be empty for the other two; the field defaults to an empty
    collection."
    PRD: "A new definition is created in `state` `DRAFT` with `approved_at`
    null."

    Design: Corner/entities/target_market_defaults_to_draft_with_an_empty_tract_list
    """
    institution = fixtures.create_institution(ein="210000007")
    institution_id = institution["id"]

    created = validate_success(
        api_client.create_target_market(
            institution_id,
            {
                "market_type": "LOW_INCOME_TARGETED_POPULATION",
                "name": "Households at or below 80 percent AMI",
                "ami_threshold_pct": 80.00,
            },
            fixtures.make_institution_officer_headers(institution_id),
        ),
        201,
    )
    assert_target_market(created)
    assert created["census_tract_codes"] == []
    assert float(created["ami_threshold_pct"]) == 80.00
    assert created["state"] == "DRAFT"
    assert created["approved_at"] is None
    assert created["version"] == 1

    unchanged = fixtures.read_institution(institution_id)
    assert float(unchanged["accountability_score"]) == 0.0000, (
        "a draft definition contributes nothing to the accountability score"
    )


def test_borrower_income_percentage_of_area_median_is_derived_at_intake():
    """The income percentage is computed by the platform, never supplied.

    PRD: "At intake the platform computes `income_pct_ami` as one hundred
    multiplied by `household_income_cents`, divided by
    `area_median_income_cents`, rounded half up to two decimal places."
    PRD: "The borrower is created with `geocode_state` `UNGEOCODED`,
    `geocode_attempts` 0, `census_tract_code` null, `in_target_market` false,
    `matched_target_market_type` null and `ta_hours_total` 0.00."

    Design: Corner/entities/borrower_income_pct_ami_is_computed_at_creation_not_supplied
    """
    institution = fixtures.create_institution(ein="210000008")
    institution_id = institution["id"]

    created = validate_success(
        api_client.create_borrower(
            institution_id,
            {
                "full_name": "Maria Ortiz",
                "street_address": TEST_DEFAULTS["STREET_ADDRESS"],
                "postal_code": TEST_DEFAULTS["POSTAL_CODE"],
                "household_income_cents": 4_200_000,
                "area_median_income_cents": 7_000_000,
                "credit_score": 740,
            },
            fixtures.make_institution_officer_headers(institution_id),
        ),
        201,
    )
    assert_borrower(created)
    assert float(created["income_pct_ami"]) == 60.00
    assert created["in_target_market"] is False
    assert created["geocode_state"] == "UNGEOCODED"
    assert created["geocode_attempts"] == 0
    assert created["census_tract_code"] is None
    assert created["matched_target_market_type"] is None
    assert float(created["ta_hours_total"]) == 0.00


def test_institution_identity_lifecycle_and_version_fields_are_server_minted():
    """Nothing the client sends decides the identifier, the state or the version.

    PRD: "Its `certification_state` is `UNCERTIFIED`."
    PRD: "and both `certified_at` and `recertification_due_at` are null."
    PRD: "the optional `loss_reserve_balance_cents`, the funded reserve on hand,
    which defaults to 0 and may never be negative."

    Design: Corner/entities/institution_system_fields_are_server_minted_on_creation
    """
    created = validate_success(
        api_client.create_institution(
            {
                "legal_name": "Harborline Community Fund",
                "ein": "210000009",
                "entity_type": "LOAN_FUND",
                "primary_mission_statement": MISSION,
                "asset_size_cents": 250_000_000,
                "reserve_method": "MIGRATION_ANALYSIS",
            },
            REGISTRAR,
        ),
        201,
    )
    assert is_valid_uuid(created["id"])
    assert is_iso8601_timestamp(created["created_at"])
    assert is_iso8601_timestamp(created["updated_at"])
    assert created["loss_reserve_balance_cents"] == 0
    assert created["version"] == 1
    assert created["certification_state"] == "UNCERTIFIED"
    assert created["certified_at"] is None
    assert created["recertification_due_at"] is None


def test_out_of_range_and_out_of_set_field_values_are_all_rejected():
    """A score above the range, an unknown market type and an empty tract list.

    PRD: "A supplied score must lie between 300 and 850 inclusive; a borrower
    with no scoreable credit file simply omits the field, leaving it null, and
    such credit-invisible borrowers are a first-class case rather than an error."
    PRD: "A target market is defined by its statutory `market_type` — one of
    `INVESTMENT_AREA`, `LOW_INCOME_TARGETED_POPULATION` or
    `OTHER_TARGETED_POPULATION` — together with a human-readable `name`."
    PRD: "On every write endpoint, `ERR_INVALID_REQUEST` (HTTP 400) covers a
    missing required body field, a field of the wrong type, an enum value
    outside its declared set, a numeric field outside its declared range, and
    each conditionally required field that is absent while its condition holds —
    a target market of type `INVESTMENT_AREA` without tract codes."

    Design: Corner/entities/borrower_credit_score_above_the_declared_range_rejected
    """
    institution = fixtures.create_institution(ein="210000010")
    institution_id = institution["id"]
    officer = fixtures.make_institution_officer_headers(institution_id)

    validate_error(
        api_client.create_borrower(
            institution_id,
            {
                "full_name": "Out Of Range",
                "street_address": "1 Test Way",
                "postal_code": TEST_DEFAULTS["POSTAL_CODE"],
                "household_income_cents": 4_200_000,
                "area_median_income_cents": 7_000_000,
                "credit_score": 900,
            },
            officer,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
    )
    validate_error(
        api_client.create_target_market(
            institution_id,
            {"market_type": "METRO_AREA", "name": "Bad Enum Market"},
            officer,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
    )
    validate_error(
        api_client.create_target_market(
            institution_id,
            {
                "market_type": "INVESTMENT_AREA",
                "name": "Tractless Investment Area",
                "census_tract_codes": [],
            },
            officer,
        ),
        ApiErrorId.ERR_INVALID_REQUEST,
    )

    _borrowers, borrower_meta = validate_paginated(
        api_client.list_institution_borrowers(institution_id, ANALYST)
    )
    assert borrower_meta["total_count"] == 0
    _markets, market_meta = validate_paginated(
        api_client.list_institution_target_markets(institution_id, ANALYST)
    )
    assert market_meta["total_count"] == 0


def test_filing_a_loan_against_another_lenders_borrower_or_product_is_not_found():
    """Parent lookups on loan filing are scoped to the booking institution.

    PRD: "`borrower_id` resolving to a borrower of the same institution
    (`ERR_BORROWER_NOT_FOUND`, on every borrower endpoint addressed by
    identifier, on loan filing and on engagement booking); `product_id`
    resolving to a loan product — of the same institution when an institution is
    addressed (`ERR_LOAN_PRODUCT_NOT_FOUND`, on loan filing and the loan-product
    read)."
    PRD: "A new request lands with `underwriting_state` `SCREENING` and
    `servicing_state` `NOT_DISBURSED`, `approved_principal_cents` null,
    `days_past_due` 0, and every money field — `principal_disbursed_cents`,
    `principal_repaid_cents`, `principal_outstanding_cents` and
    `charged_off_principal_cents` — at 0."

    Design: Corner/entities/loan_creation_rejects_a_borrower_owned_by_another_institution
    """
    alpha = fixtures.create_institution(
        legal_name="Alpha Community Fund", ein="210000011"
    )
    beta = fixtures.create_institution(
        legal_name="Beta Community Fund", ein="210000012"
    )
    alpha_officer = fixtures.make_institution_officer_headers(alpha["id"])
    alpha_product = fixtures.create_loan_product(alpha["id"], name="Alpha Product")
    beta_product = fixtures.create_loan_product(beta["id"], name="Beta Product")
    beta_borrower = fixtures.create_borrower(beta["id"], full_name="Beta Borrower")

    validate_error(
        api_client.create_loan(
            factories.loan_payload(
                alpha["id"], beta_borrower["id"], alpha_product["id"], 1_000_000
            ),
            alpha_officer,
        ),
        ApiErrorId.ERR_BORROWER_NOT_FOUND,
    )

    alpha_borrower = fixtures.create_borrower(alpha["id"], full_name="Alpha Borrower")
    validate_error(
        api_client.create_loan(
            factories.loan_payload(
                alpha["id"], alpha_borrower["id"], beta_product["id"], 1_000_000
            ),
            alpha_officer,
        ),
        ApiErrorId.ERR_LOAN_PRODUCT_NOT_FOUND,
    )

    accepted = validate_success(
        api_client.create_loan(
            factories.loan_payload(
                alpha["id"], alpha_borrower["id"], alpha_product["id"], 1_000_000
            ),
            alpha_officer,
        ),
        201,
    )
    assert_loan(accepted)
    assert accepted["underwriting_state"] == "SCREENING"
    assert accepted["servicing_state"] == "NOT_DISBURSED"
    assert accepted["approved_principal_cents"] is None
    assert accepted["days_past_due"] == 0
    assert accepted["principal_disbursed_cents"] == 0
    assert accepted["principal_repaid_cents"] == 0
    assert accepted["principal_outstanding_cents"] == 0
    assert accepted["charged_off_principal_cents"] == 0

    _alpha_loans, alpha_meta = validate_paginated(
        api_client.list_loans(ANALYST, {"institution_id": alpha["id"]})
    )
    assert alpha_meta["total_count"] == 1
    _beta_loans, beta_meta = validate_paginated(
        api_client.list_loans(ANALYST, {"institution_id": beta["id"]})
    )
    assert beta_meta["total_count"] == 0
