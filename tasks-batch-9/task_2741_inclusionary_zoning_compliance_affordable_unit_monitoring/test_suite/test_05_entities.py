"""Entity-row behaviour: declared defaults, payload shape, computed and system
fields, single-row retrieval, collection paging and the referential guard that
ties a restricted unit to an agreement of its own project.

Every test builds its own preconditions from declared endpoints only, because the
server is relaunched against an empty database before each one.
"""

from test_helpers import (
    AMI_2026_MEDIAN_INCOME_CENTS_BY_SIZE,
    CLOCK_STARTUP_DEFAULT,
    INCOME_LIMIT_SIZE_3_AT_5000_BPS,
    MAX_ALLOWED_RENT_2BR_AT_5000_BPS,
    NON_EXISTENT_UUID,
    ONE_UNIT_BPS,
    THRESHOLDS,
    ApiErrorId,
    assert_common_fields,
    assert_money_cents,
    assert_project_state,
    assert_unit_dimensions,
    assert_version_is,
    date_plus_days,
    factories,
    fixtures,
    round_half_up,
    same_instant,
    validate_error,
    validate_paginated,
    validate_success,
)

FOUR_PROJECT_INPUTS = {
    "name": "Creation Row",
    "zoning_district": "R-2",
    "total_units": 10,
    "approval_date": "2026-01-15",
}


# =============================================================================
# Creation and declared defaults
# =============================================================================
def test_create_project_returns_201_with_declared_defaults(api, developer):
    """A POST carrying only the four declared inputs lands every other field on its default.

    PRD: "The system stamps the acting `X-User-ID` onto `developer_user_id`, places the project in `state` `DRAFT` with `applicability` `PENDING` and `compliance_posture` `PENDING`, and leaves `ordinance_id`, `compliance_path` and `screened_at` null, `screen_count` at 0, and all four obligation figures at 0."

    Design: Corner/entities/create_project_returns_201_with_declared_defaults
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    fixtures.bootstrap_program()

    response = api.create_project(
        factories.create_project_payload(**FOUR_PROJECT_INPUTS), headers=developer
    )
    project = validate_success(response, 201)
    assert response.json()["response_type"] == "object"

    # The four inputs are echoed exactly as supplied.
    assert project["name"] == "Creation Row"
    assert project["zoning_district"] == "R-2"
    assert project["total_units"] == 10
    assert project["approval_date"] == "2026-01-15"

    # Nothing is screened at creation time.
    assert_project_state(
        project, state="DRAFT", applicability="PENDING", compliance_posture="PENDING"
    )
    assert project["required_affordable_units"] == 0
    assert project["fractional_obligation_bps"] == 0
    assert project["total_obligation_bps"] == 0
    assert project["onsite_unit_equivalents_bps"] == 0
    assert project["fee_covered_equivalents_bps"] == 0
    assert project["screen_count"] == 0
    assert project["screened_at"] is None

    # The ordinance is pinned at screening, never at creation.
    assert project["ordinance_id"] is None
    assert project["compliance_path"] is None

    assert_common_fields(project)
    assert_version_is(project, 1)


def test_create_project_missing_any_required_field_is_rejected(api, developer, fund_auditor):
    """Each of the four Project inputs is required, so omitting any one is a 400 and writes nothing.

    PRD: "This covers required fields being present, types being correct, enumerated values lying inside their declared domains, integer cent and basis-point fields lying inside their declared ranges, `limit` lying between 1 and 100 inclusive with `offset` not negative, `contract_rent_cents` being exactly 0 when the certified unit's `tenure` is `OWNERSHIP`, and `discount_tiers` arriving ascending by `min_pre_discount_cents` with a leading element whose `min_pre_discount_cents` is exactly 0."

    Design: Corner/entities/create_project_missing_required_field_returns_invalid_request
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    fixtures.bootstrap_program()

    complete = factories.create_project_payload(**FOUR_PROJECT_INPUTS)
    for omitted in ("name", "zoning_district", "total_units", "approval_date"):
        payload = {key: value for key, value in complete.items() if key != omitted}
        response = api.create_project(payload, headers=developer)
        error = validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)
        assert response.json()["response_type"] == "error"
        assert error["message"].strip(), f"a rejected {omitted} carried no message"

    rows, meta = validate_paginated(api.list_projects(headers=fund_auditor))
    assert meta["total_count"] == 0, "a rejected attempt wrote a partial row"
    assert rows == []


def test_project_enum_and_range_violations_are_rejected(api, developer, fund_auditor):
    """An enum outside its domain and an integer outside its range are both invalid requests.

    PRD: "A `Developer` registers a development by supplying a `name` of 1 to 120 characters, a `zoning_district` of `R-2`, `R-4` or `C-2`, a `total_units` count of at least 1, and an `approval_date` as a `YYYY-MM-DD` calendar date."

    Design: Corner/entities/out_of_domain_enum_and_range_values_return_invalid_request
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    fixtures.bootstrap_program()

    out_of_domain_enum = api.create_project(
        factories.create_project_payload(
            name="Bad District", zoning_district="R-9", total_units=10, approval_date="2026-01-15"
        ),
        headers=developer,
    )
    validate_error(out_of_domain_enum, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    out_of_range_integer = api.create_project(
        factories.create_project_payload(
            name="Zero Units", zoning_district="R-2", total_units=0, approval_date="2026-01-15"
        ),
        headers=developer,
    )
    validate_error(out_of_range_integer, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    rows, meta = validate_paginated(api.list_projects(headers=fund_auditor))
    assert meta["total_count"] == 0, "a malformed payload reached the datastore"
    assert rows == []


def test_ordinance_discount_tiers_must_start_at_a_zero_threshold(api, program_admin, fund_auditor):
    """A discount schedule whose leading tier does not start at 0 is a malformed payload.

    PRD: "A malformed schedule is rejected as an invalid request."

    Design: Corner/entities/out_of_domain_enum_and_range_values_return_invalid_request
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    fixtures.bootstrap_program()

    response = api.create_ordinance(
        factories.create_ordinance_payload(
            code="IZ-BAD-TIERS",
            discount_tiers=[{"min_pre_discount_cents": 500, "discount_bps": 100}],
            alternative_paths_allowed=[],
        ),
        headers=program_admin,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    rows, meta = validate_paginated(api.list_ordinances(headers=fund_auditor))
    assert meta["total_count"] == 1, "the rejected vintage was published anyway"
    assert [row["code"] for row in rows] == ["IZ-2024-01"]


def test_registered_household_starts_with_declared_defaults(api, program_admin):
    """A household registered from its three declared inputs holds every declared default.

    PRD: "A registered household starts in `state` `REGISTERED` with `preference_score` 0, `rank_position` null and `lottery_event_id` null."

    Design: Corner/entities/household_optional_input_falls_back_to_declared_default
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    fixtures.bootstrap_program()

    response = api.create_household(
        factories.create_household_payload(
            applicant_name="Default Dora", household_size=3, gross_annual_income_cents=6000000
        ),
        headers=program_admin,
    )
    household = validate_success(response, 201)

    assert household["state"] == "REGISTERED"
    assert household["preference_score"] == 0
    assert household["rank_position"] is None
    # lottery_event_id is only ever written by an accepted application.
    assert household["lottery_event_id"] is None

    assert household["applicant_name"] == "Default Dora"
    assert household["household_size"] == 3
    assert household["gross_annual_income_cents"] == 6000000
    assert_common_fields(household)
    assert_version_is(household, 1)


# =============================================================================
# Computed fields and server-written fields
# =============================================================================
def test_certification_pins_the_five_computed_figures(api, compliance_officer):
    """None of the five computed certification figures is an input; each comes from the active schedule.

    PRD: "Recording the certification pins five computed figures onto the row, and once pinned they are never rewritten by a later schedule."

    Design: Corner/entities/certification_computed_fields_are_derived_from_the_active_schedule
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    ctx = fixtures.project_with_unit(
        unit_overrides={
            "unit_number": "CC-101",
            "bedrooms": 2,
            "sqft": 900,
            "market_comparable_sqft": 1000,
            "tenure": "RENTAL",
            "affordability_level_bps": 5000,
        }
    )
    household = fixtures.register_household(
        applicant_name="Hana Iyer", household_size=3, gross_annual_income_cents=6000000
    )

    response = api.create_certification(
        factories.create_certification_payload(
            household["id"],
            ctx["unit"]["id"],
            certified_income_cents=6000000,
            contract_rent_cents=140000,
            effective_date="2026-08-01",
        ),
        headers=compliance_officer,
    )
    certification = validate_success(response, 201)

    # The 2026 schedule is the only ACTIVE one, so it is the one that is pinned.
    assert certification["ami_schedule_year"] == 2026
    assert certification["income_limit_cents"] == INCOME_LIMIT_SIZE_3_AT_5000_BPS
    assert certification["max_rent_cents"] == MAX_ALLOWED_RENT_2BR_AT_5000_BPS
    assert certification["ami_pct_bps"] == round_half_up(
        6000000 * 10000, AMI_2026_MEDIAN_INCOME_CENTS_BY_SIZE["3"]
    )
    assert certification["expires_at"].startswith(
        date_plus_days("2026-08-01", THRESHOLDS["CERTIFICATION_TERM_DAYS"])
    )

    assert certification["state"] == "CERTIFIED"
    assert certification["is_recertification"] is False
    assert certification["certified_by_user_id"] == compliance_officer["X-User-ID"]
    assert_money_cents(certification["income_limit_cents"], "income_limit_cents")
    assert_money_cents(certification["max_rent_cents"], "max_rent_cents")


def test_certification_refreshes_the_units_rent_ceiling_and_occupant(api, compliance_officer):
    """The certification's computed ceiling is the value the unit itself starts carrying.

    PRD: "From `PLANNED` the unit moves `PLANNED → OCCUPIED` — direct placement without a lottery, which is the normal path for `OWNERSHIP` units — additionally setting `occupant_household_id` from the certification."

    Design: Corner/entities/certification_computed_fields_are_derived_from_the_active_schedule
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    ctx = fixtures.project_with_unit(
        unit_overrides={
            "unit_number": "CC-101",
            "bedrooms": 2,
            "sqft": 900,
            "market_comparable_sqft": 1000,
            "tenure": "RENTAL",
            "affordability_level_bps": 5000,
        }
    )
    assert ctx["unit"]["occupancy_status"] == "PLANNED"

    household = fixtures.register_household(
        applicant_name="Hana Iyer", household_size=3, gross_annual_income_cents=6000000
    )
    certification = validate_success(
        api.create_certification(
            factories.create_certification_payload(
                household["id"],
                ctx["unit"]["id"],
                certified_income_cents=6000000,
                contract_rent_cents=140000,
                effective_date="2026-08-01",
            ),
            headers=compliance_officer,
        ),
        201,
    )

    unit = validate_success(api.get_unit(ctx["unit"]["id"], headers=compliance_officer))
    assert_unit_dimensions(unit, occupancy_status="OCCUPIED")
    assert unit["max_allowed_rent_cents"] == certification["max_rent_cents"]
    assert unit["max_allowed_rent_cents"] == MAX_ALLOWED_RENT_2BR_AT_5000_BPS
    assert unit["current_rent_cents"] == 140000
    assert unit["occupant_household_id"] == household["id"]


def test_project_developer_user_id_comes_from_the_acting_header(api, developer):
    """developer_user_id is not a payload field: the server copies it off the acting header.

    PRD: "The server records it as `developer_user_id` on a `Project` at registration time and thereafter compares it to that stored value: every `Developer` write against a project, one of its restricted units, one of its marketing plans, one of its in-lieu assessments, or one of its monitoring reviews is refused with `ERR_NOT_RESOURCE_OWNER` unless `X-User-ID` equals the owning project's `developer_user_id`."

    Design: Corner/entities/project_system_fields_come_from_the_server_not_the_payload
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    fixtures.bootstrap_program()

    project = validate_success(
        api.create_project(
            factories.create_project_payload(
                name="System Fields",
                zoning_district="C-2",
                total_units=40,
                approval_date="2026-01-15",
            ),
            headers=developer,
        ),
        201,
    )
    assert project["developer_user_id"] == developer["X-User-ID"]

    stored = validate_success(api.get_project(project["id"], headers=developer))
    assert stored["developer_user_id"] == developer["X-User-ID"]


def test_screening_stamps_screened_at_from_the_logical_clock(api, developer, program_admin):
    """screened_at and screen_count are server-written and read the logical clock, not wall time.

    PRD: "Screening also sets `screened_at` to the current logical instant, increases `screen_count` by one, recomputes `compliance_posture`, and increments the project's `version`."

    Design: Corner/entities/project_system_fields_come_from_the_server_not_the_payload
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    fixtures.bootstrap_program()

    project = validate_success(
        api.create_project(
            factories.create_project_payload(
                name="System Fields",
                zoning_district="C-2",
                total_units=40,
                approval_date="2026-01-15",
            ),
            headers=developer,
        ),
        201,
    )
    assert project["screened_at"] is None
    assert project["screen_count"] == 0
    assert_version_is(project, 1)

    screened = validate_success(api.screen_project(project["id"], headers=program_admin))

    assert same_instant(screened["screened_at"], CLOCK_STARTUP_DEFAULT), screened["screened_at"]
    assert screened["screen_count"] == 1
    assert_project_state(
        screened,
        state="SCREENED_SUBJECT",
        applicability="SUBJECT",
        compliance_posture="DEFICIENT",
    )
    # 40 units at the C-2 rate of 2000 bps is exactly eight whole dwellings.
    assert screened["required_affordable_units"] == 8
    assert screened["fractional_obligation_bps"] == 0
    assert screened["total_obligation_bps"] == 8 * ONE_UNIT_BPS
    assert screened["ordinance_id"] is not None
    # Creation set version 1 and the screen bumped it exactly once.
    assert_version_is(screened, 2)


# =============================================================================
# Single-row retrieval
# =============================================================================
def test_get_affordable_unit_echoes_the_stored_row(api, fund_auditor):
    """The single-row GET returns what the create stored, including all three state dimensions.

    PRD: "A new unit begins with three independent state dimensions, all set at once: `occupancy_status` `PLANNED`, `compliance_status` `COMPLIANT`, and `restriction_state` `NOT_RECORDED`."

    Design: Corner/entities/get_affordable_unit_by_id_returns_the_stored_row
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    ctx = fixtures.project_with_unit(
        unit_overrides={
            "unit_number": "RR-101",
            "bedrooms": 2,
            "sqft": 900,
            "market_comparable_sqft": 1000,
            "tenure": "RENTAL",
            "affordability_level_bps": 5000,
        }
    )

    response = api.get_unit(ctx["unit"]["id"], headers=fund_auditor)
    unit = validate_success(response, 200)
    assert response.json()["response_type"] == "object"

    assert unit["project_id"] == ctx["project"]["id"]
    assert unit["agreement_id"] == ctx["agreement"]["id"]
    assert unit["unit_number"] == "RR-101"
    assert unit["bedrooms"] == 2
    assert unit["sqft"] == 900
    assert unit["market_comparable_sqft"] == 1000
    assert unit["tenure"] == "RENTAL"
    assert unit["affordability_level_bps"] == 5000

    assert_unit_dimensions(
        unit,
        occupancy_status="PLANNED",
        compliance_status="COMPLIANT",
        restriction_state="NOT_RECORDED",
    )
    assert unit["occupant_household_id"] is None
    assert unit["withdrawn_reason"] is None
    assert_common_fields(unit)


def test_unpriced_unit_money_fields_are_integer_zero(api, fund_auditor):
    """No certification, restriction or refinance has run, so the unit's money fields are 0 cents.

    PRD: "Every field whose name ends in `_cents` is a whole number of cents, never a decimal fraction and never a string."

    Design: Corner/entities/get_affordable_unit_by_id_returns_the_stored_row
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    ctx = fixtures.project_with_unit(
        unit_overrides={
            "unit_number": "RR-101",
            "bedrooms": 2,
            "sqft": 900,
            "market_comparable_sqft": 1000,
            "tenure": "RENTAL",
            "affordability_level_bps": 5000,
        }
    )

    unit = validate_success(api.get_unit(ctx["unit"]["id"], headers=fund_auditor))
    for field in (
        "max_allowed_rent_cents",
        "current_rent_cents",
        "original_purchase_price_cents",
        "ami_income_at_purchase_cents",
        "approved_refinance_cap_cents",
    ):
        assert_money_cents(unit[field], field)
        assert unit[field] == 0, f"{field} was priced before any pricing event"


# =============================================================================
# Collection reads
# =============================================================================
def _three_projects(developer_headers):
    """Alpha, Bravo and Charlie in creation order; only Alpha is screened."""
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    fixtures.bootstrap_program()
    alpha = fixtures.register_project(
        headers=developer_headers,
        name="Alpha",
        zoning_district="R-2",
        total_units=10,
        approval_date="2026-01-15",
    )
    bravo = fixtures.register_project(
        headers=developer_headers,
        name="Bravo",
        zoning_district="R-4",
        total_units=27,
        approval_date="2026-01-16",
    )
    charlie = fixtures.register_project(
        headers=developer_headers,
        name="Charlie",
        zoning_district="C-2",
        total_units=40,
        approval_date="2026-01-17",
    )
    fixtures.screen_project(alpha["id"])
    return alpha, bravo, charlie


def test_list_projects_pages_through_the_collection(api, developer, fund_auditor):
    """Two pages of two split three rows, and the envelope reports the window it served.

    PRD: "Both parameters, along with `total_count` and `has_more`, are echoed in the `meta` object of the response envelope."

    Design: Corner/entities/list_projects_paginates_and_rejects_an_out_of_range_limit
    """
    alpha, bravo, charlie = _three_projects(developer)

    first_response = api.list_projects(limit=2, offset=0, headers=fund_auditor)
    first_page, first_meta = validate_paginated(first_response)
    assert first_response.json()["response_type"] == "array"
    assert first_meta["limit"] == 2
    assert first_meta["offset"] == 0
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True
    assert len(first_page) == 2
    # Collections are sorted by created_at ascending.
    assert [row["id"] for row in first_page] == [alpha["id"], bravo["id"]]

    second_page, second_meta = validate_paginated(
        api.list_projects(limit=2, offset=2, headers=fund_auditor)
    )
    assert second_meta["limit"] == 2
    assert second_meta["offset"] == 2
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False
    assert [row["id"] for row in second_page] == [charlie["id"]]

    paged_ids = [row["id"] for row in first_page] + [row["id"] for row in second_page]
    for project_id in (alpha["id"], bravo["id"], charlie["id"]):
        assert paged_ids.count(project_id) == 1, "a row was dropped or repeated across pages"


def test_list_projects_narrows_to_one_state(api, developer, fund_auditor):
    """The state filter narrows the same collection to the single screened row.

    PRD: "Projects can be narrowed by `ordinance_id`, `state`, `applicability`, or `compliance_posture`."

    Design: Corner/entities/list_projects_paginates_and_rejects_an_out_of_range_limit
    """
    alpha, _bravo, _charlie = _three_projects(developer)

    rows, meta = validate_paginated(
        api.list_projects(state="SCREENED_SUBJECT", headers=fund_auditor)
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [alpha["id"]]


def test_list_projects_rejects_a_limit_above_the_ceiling(api, developer, fund_auditor):
    """A limit of 101 is refused rather than silently clamped to the 100 ceiling.

    PRD: "`limit` caps the number of rows returned; it defaults to 10 when omitted, accepts a minimum of 1 and a maximum of 100, and a value outside that range is a malformed request rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/entities/list_projects_paginates_and_rejects_an_out_of_range_limit
    """
    _three_projects(developer)

    response = api.list_projects(limit=101, headers=fund_auditor)
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


# =============================================================================
# Existence checks
# =============================================================================
def test_unknown_path_ids_return_entity_specific_not_found_codes(api, fund_auditor):
    """The same unknown id yields a different 404 code on each of the thirteen families.

    PRD: "Each entity family has its own not-found code — `ERR_ORDINANCE_NOT_FOUND`, `ERR_AMI_SCHEDULE_NOT_FOUND`, `ERR_PROJECT_NOT_FOUND`, `ERR_UNIT_NOT_FOUND`, `ERR_AGREEMENT_NOT_FOUND`, `ERR_MARKETING_PLAN_NOT_FOUND`, `ERR_LOTTERY_EVENT_NOT_FOUND`, `ERR_HOUSEHOLD_NOT_FOUND`, `ERR_CERTIFICATION_NOT_FOUND`, `ERR_MONITORING_REVIEW_NOT_FOUND`, `ERR_RESALE_TRANSACTION_NOT_FOUND`, `ERR_FEE_NOT_FOUND`, and `ERR_DISBURSEMENT_NOT_FOUND` — all carrying HTTP 404."

    Design: Corner/entities/unknown_path_ids_return_entity_specific_not_found_errors
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    fixtures.bootstrap_program()

    reads = [
        (api.get_project, ApiErrorId.ERR_PROJECT_NOT_FOUND),
        (api.get_unit, ApiErrorId.ERR_UNIT_NOT_FOUND),
        (api.get_agreement, ApiErrorId.ERR_AGREEMENT_NOT_FOUND),
        (api.get_marketing_plan, ApiErrorId.ERR_MARKETING_PLAN_NOT_FOUND),
        (api.get_lottery_event, ApiErrorId.ERR_LOTTERY_EVENT_NOT_FOUND),
        (api.get_household, ApiErrorId.ERR_HOUSEHOLD_NOT_FOUND),
        (api.get_certification, ApiErrorId.ERR_CERTIFICATION_NOT_FOUND),
        (api.get_monitoring_review, ApiErrorId.ERR_MONITORING_REVIEW_NOT_FOUND),
        (api.get_resale, ApiErrorId.ERR_RESALE_TRANSACTION_NOT_FOUND),
        (api.get_in_lieu_fee, ApiErrorId.ERR_FEE_NOT_FOUND),
        (api.get_disbursement, ApiErrorId.ERR_DISBURSEMENT_NOT_FOUND),
        (api.get_ordinance, ApiErrorId.ERR_ORDINANCE_NOT_FOUND),
        (api.get_ami_schedule, ApiErrorId.ERR_AMI_SCHEDULE_NOT_FOUND),
    ]
    for read, expected in reads:
        response = read(NON_EXISTENT_UUID, headers=fund_auditor)
        assert response.status_code == 404, f"{read.__name__} returned {response.status_code}"
        assert response.json()["response_type"] == "error"
        validate_error(response, expected.value, 404)


def test_unknown_project_on_an_action_route_returns_404_not_a_state_error(api, compliance_officer):
    """Existence is resolved before any state rule, so an action on an unknown id is a 404.

    PRD: "Every identifier appearing in the URL path resolves, checked left to right, else the matching 404 code from §2.4."

    Design: Corner/entities/unknown_path_ids_return_entity_specific_not_found_errors
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    fixtures.bootstrap_program()

    response = api.screen_project(NON_EXISTENT_UUID, headers=compliance_officer)
    validate_error(response, ApiErrorId.ERR_PROJECT_NOT_FOUND.value, 404)


# =============================================================================
# Parent relationships
# =============================================================================
def test_unit_creation_requires_an_agreement_of_its_own_project(
    api, developer, rival_developer, fund_auditor
):
    """Two resolvable foreign keys that name different projects fail the referential rule, not a 404.

    PRD: "Each restricted unit is created against a `project_id` and an `agreement_id`; the named agreement must belong to the same project as the unit, and a mismatch is refused with `ERR_UNIT_PROJECT_MISMATCH`."

    Design: Corner/entities/unit_creation_requires_an_agreement_of_its_own_project
    """
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    fixtures.bootstrap_program()

    own = fixtures.register_project(
        headers=developer,
        name="Mismatch One",
        zoning_district="R-2",
        total_units=10,
        approval_date="2026-01-15",
    )
    fixtures.screen_project(own["id"])
    fixtures.elect_path(own["id"], "ONSITE", headers=developer)
    own_agreement = fixtures.record_agreement(
        fixtures.draft_agreement(own["id"])["id"],
        doc_number="DOC-MM-0001",
        recorded_at="2026-08-01",
    )

    foreign = fixtures.register_project(
        headers=rival_developer,
        name="Mismatch Two",
        zoning_district="R-2",
        total_units=10,
        approval_date="2026-01-15",
    )
    fixtures.screen_project(foreign["id"])
    fixtures.elect_path(foreign["id"], "ONSITE", headers=rival_developer)
    foreign_agreement = fixtures.record_agreement(
        fixtures.draft_agreement(foreign["id"])["id"],
        doc_number="DOC-MM-0002",
        recorded_at="2026-08-01",
    )

    unit_payload = factories.create_unit_payload(
        own["id"],
        foreign_agreement["id"],
        unit_number="MM-101",
        bedrooms=2,
        sqft=900,
        market_comparable_sqft=1000,
        tenure="RENTAL",
        affordability_level_bps=5000,
    )
    refused = api.create_unit(unit_payload, headers=developer)
    validate_error(refused, ApiErrorId.ERR_UNIT_PROJECT_MISMATCH.value, 422)

    after_refusal = fixtures.live_project(own["id"])
    assert after_refusal["onsite_unit_equivalents_bps"] == 0, "the refused unit still counted"

    # The identical payload, with this project's own agreement, is accepted.
    unit_payload["agreement_id"] = own_agreement["id"]
    unit = validate_success(api.create_unit(unit_payload, headers=developer), 201)
    assert unit["agreement_id"] == own_agreement["id"]
    assert unit["project_id"] == own["id"]

    after_accept = fixtures.live_project(own["id"])
    assert after_accept["onsite_unit_equivalents_bps"] == ONE_UNIT_BPS
    assert_project_state(after_accept, compliance_posture="COMPLIANT_ONSITE")

    _rows, meta = validate_paginated(
        api.list_units(project_id=foreign["id"], headers=fund_auditor)
    )
    assert meta["total_count"] == 0, "a unit was attached to the wrong project"
