"""Record shapes, defaults, derived fields and identifier resolution."""
from test_helpers import caseworker_headers, fiscal_officer_headers, work_specialist_headers
from test_helpers import api_errors as errs
from test_helpers import assertions as asrt
from test_helpers import factories, fixtures as fx

UNKNOWN_ID = "00000000-0000-0000-0000-0000000000ff"


def test_registering_a_household_derives_its_family_type_and_zeroes_its_clocks(api):
    """PRD §3.1: "Fourth, a unit whose youngest child is younger than 72 months — that
    is, strictly under six years of age — is `SINGLE_PARENT_CHILD_UNDER_6`."
    PRD §3.1: "A freshly registered household starts with every time-limit rollup at
    zero and with no diversion ineligibility window: `prior_state_clock_months` and
    `prior_federal_clock_months` both default to 0, the four computed rollups
    `state_clock_months_used`, `federal_clock_months_used`, `extension_months_used` and
    `issued_countable_months` are all 0, and `diversion_ineligible_through_month` is
    null."

    Design: Corner/entities/household_creation_returns_declared_fields_and_derives_family_type
    """
    response = api.register_household(
        factories.household_payload(
            head_of_household_name="Corner Creation Household",
            household_size=4,
            adult_count=1,
            youngest_child_age_months=30,
            has_subsidized_child_care=False,
        ),
        caseworker_headers(),
    )

    household = asrt.assert_accepted(response, expected_status=201)
    assert household["family_type"] == "SINGLE_PARENT_CHILD_UNDER_6"
    assert household["household_size"] == 4
    assert household["prior_state_clock_months"] == 0
    assert household["prior_federal_clock_months"] == 0
    asrt.assert_household_clocks(
        household,
        state_clock_months_used=0,
        federal_clock_months_used=0,
        extension_months_used=0,
        issued_countable_months=0,
    )
    assert household["diversion_ineligible_through_month"] is None
    assert household["version"] == 1


def test_reading_a_household_back_returns_the_persisted_row(api):
    """PRD §3.1: "Third, a unit with two or more adults that does not is
    `TWO_PARENT_NO_SUBSIDIZED_CHILD_CARE`."
    PRD §3.1: "Reading a household returns the derived `family_type` together with all
    four rollups, and an `Applicant` may read only its own household."

    Design: Corner/entities/household_retrieval_returns_the_stored_representation
    """
    created = fx.create_household(
        api,
        head_of_household_name="Corner Retrieval Household",
        county_code="CAN",
        household_size=2,
        adult_count=2,
        youngest_child_age_months=40,
        has_subsidized_child_care=False,
    )

    stored = asrt.assert_accepted(api.get_household(created["id"], work_specialist_headers()))

    assert stored["head_of_household_name"] == "Corner Retrieval Household"
    assert stored["county_code"] == "CAN"
    assert stored["family_type"] == "TWO_PARENT_NO_SUBSIDIZED_CHILD_CARE"
    assert stored["version"] == 1
    asrt.assert_audited_record(stored)


def test_a_listing_reports_the_unpaginated_total_and_whether_more_remain(api):
    """PRD §2.3: "`limit` caps the number of rows returned; it defaults to 10, may not
    be smaller than 1, and may not be larger than 100."
    PRD §2.3: "List responses carry `limit`, `offset`, `total_count` and `has_more`
    inside the `meta` object of the envelope, where `total_count` is the number of rows
    matching the filters before pagination is applied and `has_more` indicates whether
    rows remain beyond the current window."

    Design: Corner/entities/application_listing_is_paginated_with_total_count_and_has_more
    """
    household = fx.create_household(
        api, head_of_household_name="Corner Listing Household"
    )
    for month in ("2026-06", "2026-07", "2026-08"):
        fx.create_application(api, household["id"], application_month=month)

    first = api.list_household_applications(
        household["id"], caseworker_headers(), params={"limit": 2, "offset": 0}
    )
    second = api.list_household_applications(
        household["id"], caseworker_headers(), params={"limit": 2, "offset": 2}
    )

    asrt.assert_page(
        first, total_count=3, limit=2, offset=0, has_more=True, row_count=2
    )
    asrt.assert_page(
        second, total_count=3, limit=2, offset=2, has_more=False, row_count=1
    )


def test_an_unknown_case_identifier_reports_the_case_specific_not_found(api):
    """PRD §2.8: "**Path existence** — every identifier embedded in the URL path
    resolves to an existing row, checked left to right, with the leftmost failure
    winning."
    PRD §2.8: "Each resource type has its own code, all HTTP 404:
    `ERR_HOUSEHOLD_NOT_FOUND`, `ERR_APPLICATION_NOT_FOUND`,
    `ERR_INCOME_SOURCE_NOT_FOUND`, `ERR_CASE_NOT_FOUND`, `ERR_EXTENSION_NOT_FOUND`,
    `ERR_WORK_ASSIGNMENT_NOT_FOUND`, `ERR_PARTICIPATION_REPORT_NOT_FOUND`,
    `ERR_COMPLIANCE_EPISODE_NOT_FOUND`, `ERR_AUTHORIZATION_NOT_FOUND`,
    `ERR_OVERPAYMENT_NOT_FOUND`, `ERR_DIVERSION_GRANT_NOT_FOUND`,
    `ERR_REPORTING_PERIOD_NOT_FOUND`."

    Design: Corner/entities/get_case_with_unknown_path_id_returns_case_not_found
    """
    response = api.get_case(UNKNOWN_ID, caseworker_headers())

    asrt.assert_rejected(response, errs.ERR_CASE_NOT_FOUND)


def test_filing_an_application_without_a_household_reference_is_a_body_error(api):
    """PRD §2.8: "**Schema** — the body parses as an object, all required fields are
    present, every field matches its declared type, enum domain, numeric bound and
    string format, and the pagination query parameters are within range."
    PRD §2.8: "Violations return `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/application_create_missing_required_household_id_is_rejected
    """
    household = fx.create_household(
        api, head_of_household_name="Corner Required Field Household"
    )

    response = api.file_application(
        {"application_month": "2026-08", "requested_program": "ONGOING_ASSISTANCE"},
        caseworker_headers(),
    )

    asrt.assert_rejected(response, errs.ERR_INVALID_REQUEST)
    asrt.assert_page(
        api.list_household_applications(household["id"], caseworker_headers()),
        total_count=0,
    )


def test_an_omitted_encumbrance_counts_as_zero_debt_against_the_asset(api):
    """PRD §3.2: "Property is recorded in parallel as **resource items**, each with an
    `item_type` of `LIQUID_ASSET`, `VEHICLE`, `REAL_PROPERTY` or `RETIREMENT`, a fair
    market `gross_value_cents` that may not be negative, an optional
    `encumbrance_cents` recording verified debt secured by the item and defaulting to
    0, and an `exclusion_type` of `NONE`, `PRIMARY_VEHICLE`, `HOMESTEAD` or
    `RETIREMENT_ACCOUNT` naming any statutory exclusion claimed."
    PRD §3.2: "The item's `countable_value_cents` is derived on write: an item claiming
    any exclusion other than `NONE` counts zero, and an item claiming `NONE` counts its
    gross value less its encumbrance, floored at zero so that an underwater asset
    counts nothing rather than a negative amount."

    Design: Corner/entities/resource_item_omitted_encumbrance_defaults_to_zero
    """
    household = fx.create_household(
        api, head_of_household_name="Corner Default Household"
    )
    application = fx.create_application(api, household["id"])

    response = api.add_resource_item(
        application["id"],
        {
            "item_type": "LIQUID_ASSET",
            "gross_value_cents": 150000,
            "exclusion_type": "NONE",
        },
        caseworker_headers(),
    )

    item = asrt.assert_accepted(response, expected_status=201)
    asrt.assert_money(item["encumbrance_cents"], 0, "encumbrance_cents")
    asrt.assert_money(item["countable_value_cents"], 150000, "countable_value_cents")
    asrt.assert_append_only_record(item)


def test_approval_freezes_the_family_type_and_derives_the_highest_hour_tier(api):
    """PRD §3.3: "Three values are frozen out of the household and application at this
    moment and never re-read afterwards: the case's own `family_type`, its
    `household_size`, and its `countable_income_cents`."
    PRD §3.3: "Weekly core hours are 0 for `CHILD_ONLY`, 20 for
    `SINGLE_PARENT_CHILD_UNDER_6`, 20 for `SINGLE_PARENT`, 30 for
    `TWO_PARENT_NO_SUBSIDIZED_CHILD_CARE` and 50 for
    `TWO_PARENT_WITH_SUBSIDIZED_CHILD_CARE`; those land in
    `required_core_weekly_hours`."
    PRD §3.2: "Step one establishes the **payment standard** for the household size:
    26000 cents for a unit of one, 39000 for two, 49000 for three, 59000 for four,
    68000 for five and 76000 for six; for a unit larger than six, the standard is the
    six-person figure of 76000 cents plus 7000 cents for each person beyond the sixth."

    Design: Corner/entities/case_hour_requirements_are_computed_at_approve_from_family_type
    """
    built = fx.build_determined_application(
        api,
        household_overrides={
            "head_of_household_name": "Corner Computed Household",
            "household_size": 4,
            "adult_count": 2,
            "youngest_child_age_months": 40,
            "has_subsidized_child_care": True,
        },
        incomes=(),
    )
    application = built["application"]
    asrt.assert_money(application["countable_income_cents"], 0, "countable income")
    asrt.assert_money(application["determined_benefit_cents"], 50150, "determined benefit")

    case = fx.approve(api, application["id"])

    assert case["family_type"] == "TWO_PARENT_WITH_SUBSIDIZED_CHILD_CARE"
    assert case["household_size"] == 4
    assert case["required_weekly_hours"] == 55
    assert case["required_core_weekly_hours"] == 50
    assert case["required_monthly_hours"] == 220
    assert case["required_core_monthly_hours"] == 200
    asrt.assert_case_state(
        case,
        benefit_amount_cents=50150,
        sanction_level=0,
        compliance_status="ASSIGNED",
    )


def test_client_supplied_system_fields_are_ignored_rather_than_honoured(api):
    """PRD §2.8: "Unknown fields are ignored rather than rejected, but they are never
    honoured."
    PRD §2.4: "`id` — a server-minted UUID string with no type prefix."
    PRD §3.1: "Family classification is derived immediately at registration rather than
    supplied, and it drives the weekly hour requirements a case will later inherit."

    Design: Corner/entities/household_create_ignores_client_supplied_system_extra_field
    """
    response = api.register_household(
        factories.household_payload(
            head_of_household_name="Corner System Field Household",
            id="00000000-0000-0000-0000-00000000abcd",
            version=99,
            family_type="CHILD_ONLY",
        ),
        caseworker_headers(),
    )

    household = asrt.assert_accepted(response, expected_status=201)
    assert household["id"] != "00000000-0000-0000-0000-00000000abcd"
    assert household["version"] == 1
    assert household["family_type"] == "SINGLE_PARENT"
    asrt.assert_audited_record(household)


def test_an_out_of_domain_budgeting_method_is_refused_as_a_body_error(api):
    """PRD §3.1: "An optional `budgeting_method` selects which income-budgeting pipeline
    the determination will use and takes either `PROSPECTIVE` or `RETROSPECTIVE`,
    defaulting to `PROSPECTIVE` when omitted."
    PRD §2.8: "Violations return `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/application_create_invalid_enum_budgeting_method_rejected
    """
    household = fx.create_household(api, head_of_household_name="Corner Enum Household")

    response = api.file_application(
        factories.application_payload(
            household["id"], budgeting_method="MONTHLY_AVERAGE"
        ),
        caseworker_headers(),
    )

    asrt.assert_rejected(response, errs.ERR_INVALID_REQUEST)
    asrt.assert_page(
        api.list_household_applications(household["id"], caseworker_headers()),
        total_count=0,
    )


def test_an_unknown_parent_application_is_reported_before_the_body_is_read(api):
    """PRD §2.9: "Path identifiers are always resolved strictly left to right, and the
    first identifier that fails to resolve determines the error."
    PRD §2.9: "A request to issue a month against a case identifier that does not
    resolve yields `ERR_CASE_NOT_FOUND` before the body is examined for a benefit
    month."

    Design: Corner/entities/income_source_under_unknown_parent_application_not_found
    """
    response = api.add_income_source(
        UNKNOWN_ID, factories.income_source_payload(), caseworker_headers()
    )

    asrt.assert_rejected(response, errs.ERR_APPLICATION_NOT_FOUND)


def test_an_unknown_case_in_the_claim_body_is_reported_as_a_missing_case(api):
    """PRD §2.8: "**Body foreign-key existence** — every foreign key supplied in the
    request body resolves, checked in the order the fields are declared for that
    endpoint, reusing the same twelve not-found codes."
    PRD §2.8: "This applies to application filing, the case-scoped creation endpoints,
    compliance episode creation, supportive service authorization creation and
    overpayment claim drafting."

    Design: Corner/entities/overpayment_body_foreign_key_to_unknown_case_not_found
    """
    response = api.draft_overpayment(
        factories.overpayment_payload(
            UNKNOWN_ID,
            claim_type="CLIENT_ERROR",
            months_covered=["2026-08"],
            gross_amount_cents=30000,
            computation_method="GROSS",
        ),
        fiscal_officer_headers(),
    )

    asrt.assert_rejected(response, errs.ERR_CASE_NOT_FOUND)
