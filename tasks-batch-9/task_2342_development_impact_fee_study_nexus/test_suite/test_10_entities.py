"""Record shapes as written and as read back: supplied inputs, declared
defaults, server-managed identity, computed fields, filtered pages and the
reference checks that guard a create."""

from test_helpers import ANALYST_1, api_errors as err
from test_helpers import assertions as check
from test_helpers import constants as K
from test_helpers import factories, fixtures, get_success_data, validate_error
from test_helpers import validate_paginated, validate_success
from test_helpers.fixtures import ADMIN, ANALYST, CLERK, DEVELOPER, FINANCE, PERMIT_OFFICER

TUNED_PROGRAM = {
    "name": "City of Seagate Impact Fee Program",
    "jurisdiction_code": "SEAGATE",
    "fiscal_year_start_month": 10,
    "statutory_expenditure_deadline_years": 7,
    "notice_min_days": 21,
    "protest_threshold_bp": 6000,
    "effective_delay_days": 45,
    "admin_charge_bp": 250,
    "credit_cap_bp": 4000,
    "los_policy": K.LOS_POLICY_PLANNED_STANDARD_ALLOWED,
    "discount_rate_bp": 500,
    "max_deferral_days": 540,
    "default_penalty_bp": 750,
    "at_risk_window_days": 180,
    "report_grace_days": 90,
}


def test_a_tuned_program_echoes_every_supplied_statutory_constant(api):
    """A `ProgramAdministrator` begins by creating the fee program itself,
    supplying at minimum a `name` and a `jurisdiction_code`; every statutory
    constant enumerated in §2.6 may be supplied in the same body or left to its
    default. The program comes back at `version` 1 with no effective study and
    with its report history empty.

    Design: Corner/entities/fee_program_creation_echoes_every_declared_constant
    """
    fixtures.set_clock(api, K.CLOCK_PROGRAM_SETUP)

    program = validate_success(api.create_fee_program(dict(TUNED_PROGRAM), ADMIN), 201)

    for field_name, expected in TUNED_PROGRAM.items():
        assert program[field_name] == expected, (
            f"{field_name}: expected the supplied {expected}, got {program[field_name]}"
        )
    check.assert_common_fields(program, 1)
    check.assert_timestamp_equals(program["created_at"], K.CLOCK_PROGRAM_SETUP, "created_at")
    check.assert_timestamp_equals(program["updated_at"], K.CLOCK_PROGRAM_SETUP, "updated_at")
    check.assert_fields_null(
        program,
        "effective_fee_study_id",
        "last_report_fiscal_year",
        "last_report_filed_at",
        "last_report_filed_by_user_id",
    )
    assert program["last_report_status"] == K.REPORT_NOT_FILED


def test_an_omitted_constant_falls_back_to_its_declared_default(api):
    """Everything else on the program is a statutory constant with a default, so
    a program can be created from a minimal body and tuned later.
    `notice_min_days`, 1 through 365 and defaulting to 14, is the shortest notice
    period the program will accept. `protest_threshold_bp`, 1 through 10000 and
    defaulting to 5000, is the affected-property weight at or above which a
    protest is sustained.

    Design: Corner/entities/fee_program_omitted_constants_fall_back_to_declared_defaults
    """
    fixtures.set_clock(api, K.CLOCK_PROGRAM_SETUP)

    program = validate_success(api.create_fee_program(factories.fee_program_payload(), ADMIN), 201)

    for field_name, expected in K.PROGRAM_CONSTANT_DEFAULTS.items():
        assert program[field_name] == expected, (
            f"{field_name}: expected the declared default {expected}, got {program[field_name]}"
        )
    assert program["version"] == 1
    assert program["last_report_status"] == K.REPORT_NOT_FILED
    check.assert_fields_null(program, "effective_fee_study_id")


def test_a_facility_standard_ignores_client_supplied_system_fields(api):
    """`version` (integer): starts at 1 on creation and increments by one on
    every mutation, including mutations of purely derived fields. A newly adopted
    standard is born with `fund_posture` `COMPLIANT` and every derived money
    figure at zero: `fund_balance_cents`, `refund_due_cents`,
    `committed_demand_units` and `deferred_receivable_cents` all start at 0 and
    `oldest_unexpended_vintage_at` starts null.

    Design: Corner/entities/facility_category_system_field_input_ignored
    """
    fixtures.set_clock(api, K.CLOCK_PROGRAM_SETUP)
    program = fixtures.create_program(api)

    category = validate_success(
        api.create_facility_category(
            factories.parks_category_payload(
                program["id"],
                id="cat-forced-1",
                version=99,
                created_at="2001-01-01T00:00:00Z",
                fund_balance_cents=777777,
                fund_posture=K.FUND_POSTURE_REFUND_DUE,
            ),
            ADMIN,
        ),
        201,
    )

    assert category["id"] != "cat-forced-1", "identity is server-minted, not client-chosen"
    check.assert_common_fields(category, 1)
    check.assert_timestamp_equals(category["created_at"], K.CLOCK_PROGRAM_SETUP, "created_at")
    check.assert_timestamp_equals(category["updated_at"], K.CLOCK_PROGRAM_SETUP, "updated_at")
    check.assert_category_fund(
        category,
        fund_balance_cents=0,
        refund_due_cents=0,
        fund_posture=K.FUND_POSTURE_COMPLIANT,
        committed_demand_units=0,
        deferred_receivable_cents=0,
    )
    check.assert_fields_null(category, "oldest_unexpended_vintage_at")
    check.assert_four_decimal_equals(
        category["existing_deficiency_demand_units"], 0, "existing_deficiency_demand_units"
    )
    check.assert_money_equals(
        category["unit_cost_cents"], K.PARKS_UNIT_COST_CENTS, "unit_cost_cents"
    )


def test_growth_demand_units_are_computed_before_any_allocation(api):
    """A projection of 1,200 dwellings at 1.0100 demand units each plus 200,000
    non-residential square feet at 3.7500 demand units per thousand yields 1,212
    plus 750, or 1962.0000 demand units. Until the component is allocated, its
    `allocation_status` is `PENDING`, `allocated_at` is null, and all four
    computed cost figures are null.

    Design: Corner/entities/nexus_component_growth_demand_units_computed_at_creation
    """
    chain = fixtures.program_with_categories(api)
    study = fixtures.create_study(api, chain.program_id)

    component = validate_success(
        api.create_nexus_component(
            factories.roads_component_payload(study["id"], chain.roads_category_id), ANALYST
        ),
        201,
    )

    check.assert_four_decimal_equals(
        component["growth_demand_units"], K.ROADS_GROWTH_DEMAND_UNITS, "growth_demand_units"
    )
    assert component["allocation_status"] == K.ALLOCATION_PENDING
    check.assert_fields_null(
        component,
        "allocated_at",
        "plan_based_cost_per_unit_cents",
        "standard_based_cost_per_unit_cents",
        "adopted_cost_per_unit_cents",
        "nexus_ratio",
    )
    assert component["version"] == 1


def test_a_certified_study_reads_back_its_certification_stamps(api):
    """Certification writes `certified_by_user_id` from the caller's `X-User-ID`
    and `certified_at` from the logical clock, and increments the study's
    `version`. A new study is born in status `DRAFT` with `revision_round` 0, a
    protest tally of zero on both counters, and every notice, adoption and
    activation timestamp null; the create additionally increments the parent
    program's `version`, because the program's roster of studies has changed.

    Design: Corner/entities/get_fee_study_returns_the_stored_certification_record
    """
    chain = fixtures.certified_program(api)

    study = validate_success(api.get_fee_study(chain.study_id, CLERK))

    assert study["id"] == chain.study_id
    assert study["fee_program_id"] == chain.program_id
    assert study["title"] == "2026 Impact Fee Study"
    assert study["methodology"] == K.METHODOLOGY_PLAN_BASED
    assert study["status"] == K.STUDY_NEXUS_CERTIFIED
    assert study["revision_round"] == 0
    assert study["certified_by_user_id"] == ANALYST_1
    check.assert_timestamp_equals(study["certified_at"], K.CLOCK_PROGRAM_SETUP, "certified_at")
    check.assert_fields_null(
        study,
        "notice_method",
        "notice_days",
        "notice_published_at",
        "protest_window_ends_at",
        "adopted_at",
        "adopted_by_user_id",
        "effective_at",
        "activated_at",
        "superseded_by_fee_study_id",
    )
    assert study["protest_weight_bp"] == 0
    assert study["protest_count"] == 0


def test_a_status_filtered_study_page_counts_the_filtered_population(api):
    """Every list response includes `limit`, `offset`, `total_count` and
    `has_more` inside the envelope's `meta` object, where `total_count` is the
    number of records matching the filters before pagination is applied and
    `has_more` states whether records remain beyond the returned page. Unless a
    specific endpoint's description in §4 says otherwise, list results are
    ordered by `created_at` ascending.

    Design: Corner/entities/fee_study_listing_filters_by_status_and_reports_pagination_totals
    """
    chain = fixtures.certified_program(api)
    draft = fixtures.create_study(api, chain.program_id, title="2027 Impact Fee Study")

    drafts, drafts_meta = validate_paginated(
        api.list_fee_studies(
            DEVELOPER,
            {"fee_program_id": chain.program_id, "status": K.STUDY_DRAFT, "limit": 1, "offset": 0},
        )
    )
    first_page, first_meta = validate_paginated(
        api.list_fee_studies(DEVELOPER, {"fee_program_id": chain.program_id, "limit": 1, "offset": 0})
    )
    second_page, second_meta = validate_paginated(
        api.list_fee_studies(DEVELOPER, {"fee_program_id": chain.program_id, "limit": 1, "offset": 1})
    )

    assert [row["id"] for row in drafts] == [draft["id"]]
    assert drafts[0]["status"] == K.STUDY_DRAFT
    check.assert_pagination_meta(drafts_meta, limit=1, offset=0, total_count=1, has_more=False)
    check.assert_pagination_meta(first_meta, limit=1, offset=0, total_count=2, has_more=True)
    check.assert_pagination_meta(second_meta, limit=1, offset=1, total_count=2, has_more=False)
    assert len(first_page) == 1 and len(second_page) == 1
    assert sorted([first_page[0]["id"], second_page[0]["id"]]) == sorted(
        [chain.study_id, draft["id"]]
    ), "the offset window neither repeats nor skips a row"


def test_an_application_page_tracks_the_filter_across_a_mutation(api):
    """`limit` caps the number of records returned; it defaults to 10, its
    minimum accepted value is 1 and its maximum is 100. Every list response
    includes `limit`, `offset`, `total_count` and `has_more` inside the
    envelope's `meta` object, where `total_count` is the number of records
    matching the filters before pagination is applied and `has_more` states
    whether records remain beyond the returned page.

    Design: Corner/entities/filtering_and_paging_stay_consistent_across_a_mutation
    """
    chain = fixtures.effective_program(api)
    first = fixtures.file_application(api, chain.program_id, permit_number="BP-1001")
    second = fixtures.file_application(api, chain.program_id, permit_number="BP-1002")
    third = fixtures.file_application(api, chain.program_id, permit_number="BP-1003")
    fixtures.set_clock(api, K.CLOCK_ASSESSMENT)
    fixtures.assess(api, first["id"])
    fixtures.assess(api, second["id"])
    assessed_filter = {
        "fee_program_id": chain.program_id,
        "assessment_status": K.ASSESSMENT_ASSESSED,
        "limit": 1,
    }

    page_one, meta_one = validate_paginated(
        api.list_development_applications(PERMIT_OFFICER, dict(assessed_filter, offset=0))
    )
    page_two, meta_two = validate_paginated(
        api.list_development_applications(PERMIT_OFFICER, dict(assessed_filter, offset=1))
    )

    check.assert_pagination_meta(meta_one, limit=1, offset=0, total_count=2, has_more=True)
    check.assert_pagination_meta(meta_two, limit=1, offset=1, total_count=2, has_more=False)
    assert sorted([page_one[0]["id"], page_two[0]["id"]]) == sorted([first["id"], second["id"]])

    fixtures.assess(api, third["id"])

    assessed, assessed_meta = validate_paginated(
        api.list_development_applications(
            PERMIT_OFFICER,
            {
                "fee_program_id": chain.program_id,
                "assessment_status": K.ASSESSMENT_ASSESSED,
                "limit": 10,
                "offset": 0,
            },
        )
    )
    unassessed, unassessed_meta = validate_paginated(
        api.list_development_applications(
            PERMIT_OFFICER,
            {
                "fee_program_id": chain.program_id,
                "assessment_status": K.ASSESSMENT_UNASSESSED,
                "limit": 10,
                "offset": 0,
            },
        )
    )
    due, due_meta = validate_paginated(
        api.list_development_applications(
            PERMIT_OFFICER,
            {
                "fee_program_id": chain.program_id,
                "collection_status": K.COLLECTION_DUE,
                "limit": 2,
                "offset": 0,
            },
        )
    )

    check.assert_pagination_meta(assessed_meta, total_count=3, has_more=False)
    assert len(assessed) == 3
    check.assert_pagination_meta(unassessed_meta, total_count=0, has_more=False)
    assert unassessed == []
    check.assert_pagination_meta(due_meta, total_count=3, has_more=True)
    assert len(due) == 2


def test_every_unresolvable_path_identifier_names_its_own_resource(api):
    """Where a path does carry an identifier, that identifier is resolved before
    any body or business rule is examined, and the 404 that comes back names the
    resource type that failed to resolve: `ERR_FEE_PROGRAM_NOT_FOUND`,
    `ERR_FACILITY_CATEGORY_NOT_FOUND`, `ERR_FEE_STUDY_NOT_FOUND`,
    `ERR_NEXUS_COMPONENT_NOT_FOUND`, `ERR_DEVELOPMENT_APPLICATION_NOT_FOUND`,
    `ERR_CREDIT_CLAIM_NOT_FOUND`, `ERR_DEFERRAL_AGREEMENT_NOT_FOUND`,
    `ERR_PROTEST_FILING_NOT_FOUND` or `ERR_FUND_LEDGER_ENTRY_NOT_FOUND`.

    Design: Corner/entities/unknown_path_ids_return_their_matching_not_found_error
    """
    chain = fixtures.effective_program(api)
    assessed = fixtures.assessed_application(api, chain)

    validate_error(
        api.get_fee_program(K.UNKNOWN_ID_1, DEVELOPER), err.ERR_FEE_PROGRAM_NOT_FOUND, 404
    )
    validate_error(
        api.get_facility_category(K.UNKNOWN_ID_2, DEVELOPER),
        err.ERR_FACILITY_CATEGORY_NOT_FOUND,
        404,
    )
    validate_error(api.get_fee_study(K.UNKNOWN_ID_3, DEVELOPER), err.ERR_FEE_STUDY_NOT_FOUND, 404)
    validate_error(
        api.get_nexus_component(K.UNKNOWN_ID_4, DEVELOPER), err.ERR_NEXUS_COMPONENT_NOT_FOUND, 404
    )
    validate_error(
        api.get_development_application(K.UNKNOWN_ID_5, DEVELOPER),
        err.ERR_DEVELOPMENT_APPLICATION_NOT_FOUND,
        404,
    )
    validate_error(
        api.get_fund_ledger_entry(K.UNKNOWN_ID_6, FINANCE), err.ERR_FUND_LEDGER_ENTRY_NOT_FOUND, 404
    )
    validate_error(
        api.decide_credit_claim(
            K.UNKNOWN_ID_7,
            factories.credit_decision_payload(assessed["version"], K.DECISION_DENY),
            ANALYST,
        ),
        err.ERR_CREDIT_CLAIM_NOT_FOUND,
        404,
    )
    validate_error(
        api.decide_deferral_agreement(
            K.UNKNOWN_ID_8, factories.deferral_decision_payload(K.DEFERRAL_DECISION_DENY), PERMIT_OFFICER
        ),
        err.ERR_DEFERRAL_AGREEMENT_NOT_FOUND,
        404,
    )
    validate_error(
        api.withdraw_protest_filing(K.UNKNOWN_ID_9, CLERK), err.ERR_PROTEST_FILING_NOT_FOUND, 404
    )
    application = get_success_data(api.get_development_application(chain.application_id, ADMIN))
    assert application["assessment_status"] == K.ASSESSMENT_ASSESSED
    assert application["version"] == assessed["version"], "a 404 mutates nothing"


def test_a_study_create_without_its_methodology_is_a_schema_violation(api):
    """A `NexusAnalyst` opens the technical study, supplying the
    `fee_program_id`, a `title` of 1 to 200 characters, and the `methodology` the
    study adopts as its fee basis — either `PLAN_BASED` or `STANDARD_BASED`. The
    create also requires `expected_fee_program_version` under the rule in §2.8.

    Design: Corner/entities/fee_study_create_without_methodology_returns_invalid_request
    """
    fixtures.set_clock(api, K.CLOCK_PROGRAM_SETUP)
    program = fixtures.create_program(api)

    response = api.create_fee_study(
        {
            "fee_program_id": program["id"],
            "title": "2026 Impact Fee Study",
            "expected_fee_program_version": program["version"],
        },
        ANALYST,
    )

    validate_error(response, err.ERR_INVALID_REQUEST, 422)
    studies, meta = validate_paginated(
        api.list_fee_studies(ADMIN, {"fee_program_id": program["id"]})
    )
    assert studies == []
    check.assert_pagination_meta(meta, total_count=0)
    unchanged = get_success_data(api.get_fee_program(program["id"], ADMIN))
    assert unchanged["version"] == 1, "a rejected create leaves the parent version alone"


def test_out_of_range_and_off_enum_program_constants_are_refused(api):
    """`los_policy` is an enum of `EXISTING_DEFICIENCY_EXCLUDED` (the default) or
    `PLANNED_STANDARD_ALLOWED` and decides whether the standard-based methodology
    may price the planned level of service or is held to the existing one.
    `admin_charge_bp`, 0 through 2000 and defaulting to 300, is the
    administrative charge added to each assessed line. A `FeeProgram` is the root
    of everything: a jurisdiction's impact fee program, identified by a legal
    `name` of 1 to 200 non-blank characters and a `jurisdiction_code` of 2 to 10
    uppercase letters and digits that must be unique across all programs.

    Design: Corner/entities/fee_program_rejects_invalid_los_policy_enum
    """
    fixtures.set_clock(api, K.CLOCK_PROGRAM_SETUP)

    off_enum = api.create_fee_program(
        factories.fee_program_payload(los_policy="PLANNED_STANDARD_FORCED", admin_charge_bp=4000),
        ADMIN,
    )
    out_of_range = api.create_fee_program(
        factories.fee_program_payload(
            los_policy=K.LOS_POLICY_PLANNED_STANDARD_ALLOWED, admin_charge_bp=4000
        ),
        ADMIN,
    )
    bad_code = api.create_fee_program(
        factories.fee_program_payload(jurisdiction_code="harbor-1", admin_charge_bp=300), ADMIN
    )

    validate_error(off_enum, err.ERR_INVALID_REQUEST, 422)
    validate_error(out_of_range, err.ERR_INVALID_REQUEST, 422)
    validate_error(bad_code, err.ERR_INVALID_REQUEST, 422)
    accepted = fixtures.create_program(api)
    assert accepted["jurisdiction_code"] == "HARBOR", (
        "no rejected create may have claimed the jurisdiction code"
    )
    assert accepted["admin_charge_bp"] == K.DEFAULT_ADMIN_CHARGE_BP


def test_a_component_may_not_price_a_standard_of_another_program(api):
    """Once both references resolve on a component create, they must
    additionally belong to the same program; a component whose study and facility
    category come from different programs is rejected with
    `ERR_PROGRAM_SCOPE_MISMATCH` (HTTP 422).

    Design: Corner/entities/nexus_component_rejects_category_from_another_program
    """
    chain = fixtures.program_with_categories(api, with_roads=False)
    other_program = fixtures.create_program(api, factories.second_fee_program_payload())
    other_study = fixtures.create_study(api, other_program["id"])

    response = api.create_nexus_component(
        factories.parks_component_payload(other_study["id"], chain.parks_category_id), ANALYST
    )

    validate_error(response, err.ERR_PROGRAM_SCOPE_MISMATCH, 422)
    components, meta = validate_paginated(
        api.list_nexus_components(ADMIN, {"fee_study_id": other_study["id"]})
    )
    assert components == []
    check.assert_pagination_meta(meta, total_count=0)


def test_a_body_reference_that_resolves_to_nothing_is_an_invalid_reference(api):
    """A `fee_program_id`, `fee_study_id` or `facility_category_id` in a body
    that does not resolve yields `ERR_INVALID_REFERENCE` (HTTP 404), and this
    applies when creating a facility category, when opening a fee study and when
    adding a nexus component. Opening a fee study at `POST /fee-studies` requires
    `expected_fee_program_version` carrying the client's last observed `version`
    of the target `FeeProgram`.

    Design: Corner/entities/fee_study_create_with_unknown_program_id_returns_invalid_reference
    """
    fixtures.set_clock(api, K.CLOCK_PROGRAM_SETUP)
    program = fixtures.create_program(api)

    response = api.create_fee_study(
        factories.fee_study_payload(
            K.UNKNOWN_ID_1,
            program["version"],
            title="Phantom Study",
            methodology=K.METHODOLOGY_STANDARD_BASED,
        ),
        ANALYST,
    )

    validate_error(response, err.ERR_INVALID_REFERENCE, 404)
    unchanged = get_success_data(api.get_fee_program(program["id"], ADMIN))
    assert unchanged["version"] == 1
    studies, meta = validate_paginated(
        api.list_fee_studies(ADMIN, {"fee_program_id": program["id"]})
    )
    assert studies == []
    check.assert_pagination_meta(meta, total_count=0)
