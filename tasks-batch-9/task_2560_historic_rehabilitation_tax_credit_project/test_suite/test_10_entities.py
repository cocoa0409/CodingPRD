"""Entity shape, defaults, derived fields and the two identity rows.

These cover what a row looks like the moment it is minted: which fields the client
supplies, which the server derives, which default when omitted, and which are
absent altogether from the two records that are never mutated.
"""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assertions,
    factories,
    fixtures,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    types,
    validate_error,
    validate_success,
)

PLACEHOLDER_PROJECT_ID = "11111111-1111-1111-1111-111111111111"
PLACEHOLDER_PART_APPLICATION_ID = "22222222-2222-2222-2222-222222222222"
PLACEHOLDER_DEVELOPER_ID = "33333333-3333-3333-3333-333333333333"
PLACEHOLDER_PROPERTY_ID = "44444444-4444-4444-4444-444444444444"


def test_recording_a_property_returns_the_created_row_with_its_derived_fields(api):
    """A new building is unevaluated, uncertified and carries no projects yet.

    The stored row echoes the nomination name, the year built and the register
    posture that were supplied, and the server supplies the evaluation posture: the
    building has not been evaluated, has no certification timestamp, and counts zero
    open projects. Its version starts at one.

    PRD: "A newly recorded property has not yet been evaluated: its `evaluation_status` is `UNEVALUATED`, its `certified_at` is null, and its `open_project_count` is zero."
    PRD: "Operations that mint a new resource return `201 Created`."
    PRD: "`version` is an integer that starts at 1 on creation and increments by exactly one on every mutation of that row; it is the value optimistic concurrency control is checked against."

    Design: Corner/entities/property_creation_returns_201_with_system_and_computed_fields
    """
    fixtures.set_clock(api, "2026-09-01T00:00:00Z")

    response = api.create_property(
        fixtures.ADMIN,
        name="Elm Mill",
        street_address="120 Elm Street",
        city="Dayton",
        state_code="OH",
        year_built=1912,
        listing_status="INDIVIDUAL_LISTED",
    )

    stored = validate_success(response, 201)
    body = response.json()
    assert body["response_type"] == "object", "a single resource is an object response"
    assert body["meta"]["api_request_id"].startswith("req_"), (
        "the envelope carries a server-generated request id"
    )
    assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"]), (
        "the envelope carries a server-generated request timestamp"
    )
    types.assert_is_property(stored)
    assertions.assert_fields(
        stored,
        "new property",
        name="Elm Mill",
        year_built=1912,
        listing_status="INDIVIDUAL_LISTED",
        evaluation_status="UNEVALUATED",
        certified_at=None,
        open_project_count=0,
        version=1,
    )


def test_reading_a_project_returns_both_stored_and_derived_fields(api):
    """The read echoes what was supplied and adds what the server computed.

    The project points at its developer and its building, keeps the elected structure
    and the supplied basis, and exposes the derived window end, the two starting
    state values, and a threshold derived immediately from the basis.

    PRD: "The project opens with `certification_status` at `PRE_CERTIFICATION` and `compliance_status` at `NOT_MONITORED`, with `placed_in_service_date` null, and with the whole credit ledger — `qre_total_final_cents`, `qre_total_provisional_cents`, `nonqualified_total_cents`, `classified_cost_total_cents`, `developer_fee_disallowed_cents`, `annual_credit_cents`, `total_claimable_credit_cents`, `credit_claimed_to_date_cents`, `credit_recaptured_cents`, `credit_unclaimed_cents`, `recapture_balance_cents`, `max_investor_risk_score` — at zero, with `substantial_test_status` at `NOT_MET` and `frozen_at_certification` false."
    PRD: "Its `substantial_test_threshold_cents` is derived immediately."

    Design: Corner/entities/project_retrieval_returns_stored_and_derived_fields
    """
    cast = fixtures.seed_cast(api)
    project = fixtures.open_project(
        api,
        cast,
        structure_type="MASTER_LEASE",
        adjusted_basis_cents=60_000_000,
        measuring_period_months=24,
        measuring_period_start_date="2026-09-01",
    )

    stored = validate_success(api.get_project(project["id"], cast.developer_headers))

    types.assert_is_project(stored)
    assertions.assert_fields(
        stored,
        "project read",
        developer_id=cast.developer_id,
        property_id=cast.property_id,
        structure_type="MASTER_LEASE",
        adjusted_basis_cents=60_000_000,
        measuring_period_end_date="2028-09-01",
        placed_in_service_date=None,
        frozen_at_certification=False,
    )
    assertions.assert_project_state(
        stored,
        certification_status="PRE_CERTIFICATION",
        compliance_status="NOT_MONITORED",
    )
    assertions.assert_ledger(
        stored,
        substantial_test_threshold_cents=60_000_000,
        substantial_test_status="NOT_MET",
    )


def test_listing_projects_reports_total_count_and_has_more_per_page(api):
    """Two pages over three rows, with the counters describing the whole match set.

    Three projects, one per building so their measuring periods cannot contend, are
    listed two at a time. The first page carries two rows and reports three matches
    with more remaining; the second page carries the last row and reports no more.

    PRD: "Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope, where `total_count` is the number of rows matching the filters before pagination is applied and `has_more` states whether rows remain beyond the current page."
    PRD: "The `response_type` is either "object" for a single resource or "array" for a list of resources."

    Design: Corner/entities/project_listing_paginates_with_total_count_and_has_more
    """
    cast = fixtures.seed_cast(api)
    second_property = fixtures.create_property(
        api, name="Oak Foundry", street_address="44 Oak Street", year_built=1905
    )
    third_property = fixtures.create_property(
        api, name="Canal Warehouse", street_address="9 Canal Road", year_built=1898
    )
    fixtures.open_project(api, cast)
    fixtures.open_project(api, cast, property_id=second_property["id"])
    fixtures.open_project(api, cast, property_id=third_property["id"])

    first_page = api.list_projects(
        cast.developer_headers, developer_id=cast.developer_id, limit=2, offset=0
    )
    second_page = api.list_projects(
        cast.developer_headers, developer_id=cast.developer_id, limit=2, offset=2
    )

    assert first_page.json()["response_type"] == "array", "a list is an array response"
    first_items, _ = assertions.assert_page(
        first_page, total_count=3, has_more=True, limit=2, offset=0
    )
    assert len(first_items) == 2, "the first page holds two of the three rows"
    second_items, _ = assertions.assert_page(
        second_page, total_count=3, has_more=False, limit=2, offset=2
    )
    assert len(second_items) == 1, "the second page holds the remaining row"


def test_reading_an_unknown_project_id_returns_the_project_not_found_error(api):
    """An id that resolves to no row is the project entity's own 404.

    Nothing but a developer exists, so the requested project id cannot resolve, and
    the path-existence check reports the not-found error belonging to the project
    entity in the error envelope.

    PRD: "Each `{id}` in the path resolves to an existing row of its entity, else that entity's own not-found error (404)."
    PRD: "All error API responses (4xx status codes) follow this standard envelope format:"

    Design: Corner/entities/project_detail_read_with_unknown_id_returns_not_found
    """
    fixtures.set_clock(api, "2026-09-01T00:00:00Z")
    developer = fixtures.create_developer(api)

    response = api.get_project(
        PLACEHOLDER_PROJECT_ID, fixtures.make_developer_headers(developer["id"])
    )

    assert response.json()["response_type"] == "error", "a refusal is an error response"
    validate_error(response, ApiErrorId.PROJECT_NOT_FOUND.value, 404)


def test_opening_a_project_without_the_adjusted_basis_is_a_schema_violation(api):
    """A missing required field is rejected before anything is created.

    The basis is required, so a body that omits it never reaches the domain rules.
    No project appears under the developer and the building's open-project count is
    still zero.

    PRD: "Types, enum membership, numeric ranges, date formats, and required-field presence, else `ERR_INVALID_REQUEST` (400)."
    PRD: "`adjusted_basis_cents` records the adjusted basis of the building at the start of the measuring period and must be zero or greater."

    Design: Corner/entities/project_creation_missing_required_adjusted_basis_returns_invalid_request
    """
    cast = fixtures.seed_cast(api)

    response = api.create_project(
        cast.developer_headers,
        developer_id=cast.developer_id,
        property_id=cast.property_id,
        project_name="Elm Mill Rehab",
        structure_type="SINGLE_TIER",
        measuring_period_months=24,
        measuring_period_start_date="2026-09-01",
    )

    validate_error(response, ApiErrorId.INVALID_REQUEST.value, 400)
    assertions.assert_page(
        api.list_projects(cast.developer_headers, developer_id=cast.developer_id),
        total_count=0,
    )
    stored_property = get_success_data(
        api.get_property(cast.property_id, cast.developer_headers)
    )
    assertions.assert_fields(stored_property, "property", open_project_count=0)


def test_omitted_optional_fields_take_their_declared_defaults(api):
    """Listing posture, credential status and classification all default.

    A building recorded without a register posture is NOT_LISTED, a reviewer
    registered without a credential status is ACTIVE, and a cost recorded without a
    classification is PENDING_CLASSIFICATION with no exclusion reason. That pending
    cost counts toward the provisional qualified total but toward neither the final
    total nor the classified total.

    PRD: "Its register posture at intake is `listing_status`, defaulting to `NOT_LISTED` and otherwise one of `INDIVIDUAL_LISTED`, `DISTRICT_CONTRIBUTING`, or `DISTRICT_NONCONTRIBUTING`."
    PRD: "A reviewer carries a `full_name` of 1 to 80 characters, an `agency` of either `SHPO` or `NPS`, a `state_code` giving the two-letter uppercase USPS code of the reviewer's office, and a `credential_status` that defaults to `ACTIVE` and may alternatively be `SUSPENDED`."
    PRD: "A line item may be recorded unclassified, in which case its `classification` is `PENDING_CLASSIFICATION`, or classified immediately by supplying the optional `classification` field with either `QRE` or `NON_QRE`."

    Design: Corner/entities/property_and_reviewer_optional_fields_apply_declared_defaults
    """
    fixtures.set_clock(api, "2026-09-01T00:00:00Z")
    developer = fixtures.create_developer(api)
    headers = fixtures.make_developer_headers(developer["id"])

    stored_property = validate_success(
        api.create_property(
            fixtures.ADMIN,
            name="Elm Mill",
            street_address="120 Elm Street",
            city="Dayton",
            state_code="OH",
            year_built=1912,
        ),
        201,
    )
    reviewer = validate_success(
        api.create_reviewer(
            fixtures.ADMIN, full_name="S. Hale", agency="SHPO", state_code="OH"
        ),
        201,
    )
    project = validate_success(
        api.create_project(
            headers,
            **factories.project_payload(
                developer["id"],
                stored_property["id"],
                structure_type="SINGLE_TIER",
                adjusted_basis_cents=60_000_000,
            ),
        ),
        201,
    )
    cost = validate_success(
        api.create_cost_line_item(
            headers,
            project_id=project["id"],
            vendor_name="Keystone Masonry",
            category="HARD_CONSTRUCTION",
            amount_cents=100_000,
            incurred_date="2027-05-10",
        ),
        201,
    )

    assertions.assert_fields(
        stored_property, "property without a listing status", listing_status="NOT_LISTED"
    )
    assertions.assert_fields(
        reviewer, "reviewer without a credential status", credential_status="ACTIVE"
    )
    assertions.assert_fields(
        cost,
        "unclassified cost",
        classification="PENDING_CLASSIFICATION",
        exclusion_reason="NONE",
        in_measuring_period=True,
    )
    assertions.assert_ledger(
        get_success_data(api.get_project(project["id"], headers)),
        classified_cost_total_cents=0,
        qre_total_provisional_cents=100_000,
        qre_total_final_cents=0,
    )


def test_a_sixty_month_window_ends_five_years_after_its_start_date(api):
    """The window end is the start advanced by the elected number of months.

    A 60-month window opened on 2026-09-01 ends on 2031-09-01, so a cost incurred on
    2031-08-31 is still inside it. Opening the project also raises the building's
    open-project count to one.

    PRD: "`measuring_period_months` must be exactly 24 or exactly 60 — the two statutory windows a taxpayer may elect — and `measuring_period_start_date` gives the inclusive first date of that window."
    PRD: "From these the server derives `measuring_period_end_date` as the start date advanced by that many calendar months on the same day of month, and this derived date is the exclusive upper bound of the window."

    Design: Corner/entities/project_measuring_period_end_date_is_computed_from_months
    """
    cast = fixtures.seed_cast(api)

    project = fixtures.open_project(
        api,
        cast,
        project_name="Elm Mill Phased Rehab",
        structure_type="SINGLE_TIER",
        adjusted_basis_cents=60_000_000,
        measuring_period_months=60,
        measuring_period_start_date="2026-09-01",
    )
    late_cost = fixtures.add_cost(
        api,
        cast,
        project["id"],
        amount_cents=100_000,
        incurred_date="2031-08-31",
    )

    assertions.assert_fields(
        project, "sixty-month project", measuring_period_end_date="2031-09-01"
    )
    assertions.assert_fields(
        late_cost, "cost in the fifth year", in_measuring_period=True
    )
    stored_property = get_success_data(
        api.get_property(cast.property_id, cast.developer_headers)
    )
    assertions.assert_fields(stored_property, "property", open_project_count=1)


def test_project_identity_and_audit_fields_are_generated_by_the_server(api):
    """The id is a server-minted UUID and both stamps come from the logical clock.

    The client supplies none of the identity or audit fields. The row is minted with
    a UUID that carries no type prefix, both timestamps taken from the logical clock
    the platform admin pinned, and a version of one.

    PRD: "Every resource the API mints carries an `id`: a server-generated UUID string with no type prefix and no client control over its value."
    PRD: "Every resource also carries `created_at`, an ISO 8601 UTC timestamp with three fractional digits recording when the row was created."
    PRD: "Every `created_at`, `updated_at`, `certified_at`, `submitted_at`, `review_window_end`, `decision_at`, `election_at`, and `filed_at` value is taken from this clock, and so is every comparison phrased against "the logical clock date"."

    Design: Corner/entities/project_system_fields_are_server_generated
    """
    cast = fixtures.seed_cast(api)

    project = fixtures.open_project(
        api, cast, structure_type="SINGLE_TIER", adjusted_basis_cents=60_000_000
    )

    assert is_valid_uuid(project["id"]), "the id is a server-generated UUID"
    assert project["created_at"].startswith("2026-09-01T00:00:00"), (
        "created_at is taken from the pinned logical clock"
    )
    assertions.assert_fields(
        project,
        "newly opened project",
        updated_at=project["created_at"],
        version=1,
    )


def test_unknown_enum_values_and_undeclared_month_counts_are_schema_violations(api):
    """A structure type outside the enum and a 36-month window are both rejected.

    Neither TRIPLE_TIER nor a 36-month measuring period is declared, so both bodies
    fail schema validation and no project is created by either attempt.

    PRD: "Types, enum membership, numeric ranges, date formats, and required-field presence, else `ERR_INVALID_REQUEST` (400)."
    PRD: "The project carries an internal `project_name` of 1 to 120 characters and elects its investor vehicle up front through `structure_type`, which is either `MASTER_LEASE` or `SINGLE_TIER`."

    Design: Corner/entities/project_creation_rejects_unknown_structure_type_enum_value
    """
    cast = fixtures.seed_cast(api)

    bad_structure = api.create_project(
        cast.developer_headers,
        **factories.project_payload(
            cast.developer_id, cast.property_id, structure_type="TRIPLE_TIER"
        ),
    )
    bad_months = api.create_project(
        cast.developer_headers,
        **factories.project_payload(
            cast.developer_id,
            cast.property_id,
            structure_type="SINGLE_TIER",
            measuring_period_months=36,
        ),
    )

    validate_error(bad_structure, ApiErrorId.INVALID_REQUEST.value, 400)
    validate_error(bad_months, ApiErrorId.INVALID_REQUEST.value, 400)
    assertions.assert_page(
        api.list_projects(cast.developer_headers, developer_id=cast.developer_id),
        total_count=0,
    )


def test_year_built_above_the_declared_range_is_rejected_but_the_bound_is_allowed(api):
    """2015 is outside the range; 2010 is the inclusive upper bound.

    The year built must fall in the inclusive range 1600 through 2010, so a building
    dated 2015 is refused while one dated exactly 2010 is recorded.

    PRD: "A property carries the `name` under which the building or complex appears on its nomination (1 to 120 characters, non-blank), its `street_address` (1 to 160 characters), its `city` (1 to 80 characters), its `state_code` (exactly two uppercase letters), and its `year_built`, which must fall in the inclusive range 1600 through 2010 and which feeds the evaluation of significance."

    Design: Corner/entities/property_year_built_above_declared_range_is_rejected
    """
    fixtures.set_clock(api, "2026-09-01T00:00:00Z")

    too_new = api.create_property(
        fixtures.ADMIN,
        name="New Build",
        street_address="1 New Way",
        city="Dayton",
        state_code="OH",
        year_built=2015,
        listing_status="NOT_LISTED",
    )
    on_the_bound = api.create_property(
        fixtures.ADMIN,
        name="Boundary Block",
        street_address="2 Edge Way",
        city="Dayton",
        state_code="OH",
        year_built=2010,
        listing_status="NOT_LISTED",
    )

    validate_error(too_new, ApiErrorId.INVALID_REQUEST.value, 400)
    stored = validate_success(on_the_bound, 201)
    assertions.assert_fields(stored, "building on the bound", year_built=2010)


def test_developers_and_reviewers_carry_no_mutation_tracking_fields(api):
    """The two identity rows expose only an id and a creation timestamp.

    Both records are seeded once and never mutated, so neither carries a version nor
    an updated timestamp, while the values they were registered with read back
    unchanged.

    PRD: "Two identity records are exceptions. A Developer record and a Reviewer record carry only `id` and `created_at`; both `updated_at` and `version` are absent from their representations, because these rows are seeded once and never mutated by any operation in this specification."

    Design: Corner/entities/developer_and_reviewer_are_immutable_identity_rows
    """
    fixtures.set_clock(api, "2026-09-01T00:00:00Z")
    developer = fixtures.create_developer(api, legal_name="Elm Mill Partners LLC")
    reviewer = fixtures.create_reviewer(api, "SHPO")

    stored_developer = validate_success(
        api.get_developer(developer["id"], fixtures.ADMIN)
    )
    stored_reviewer = validate_success(api.get_reviewer(reviewer["id"], fixtures.ADMIN))

    types.assert_is_developer(stored_developer)
    types.assert_is_reviewer(stored_reviewer)
    assertions.assert_no_mutation_fields(stored_developer, "developer")
    assertions.assert_no_mutation_fields(stored_reviewer, "reviewer")
    assertions.assert_fields(
        stored_developer, "developer", legal_name="Elm Mill Partners LLC"
    )
    assertions.assert_fields(stored_reviewer, "reviewer", agency="SHPO")


def test_raising_a_finding_on_an_unknown_application_is_a_path_not_found(api):
    """The parent in the path must exist before the finding body is considered.

    No application carries the requested id, so the path-existence check reports the
    part application's own not-found error rather than creating an orphan finding.

    PRD: "Path existence resolves before any body reference, so an unknown path id always yields the path entity's 404 rather than a body reference error."
    PRD: "Each `{id}` in the path resolves to an existing row of its entity, else that entity's own not-found error (404)."

    Design: Corner/entities/standard_finding_rejects_unknown_parent_part_application
    """
    fixtures.set_clock(api, "2026-09-01T00:00:00Z")
    reviewer = fixtures.create_reviewer(api, "SHPO")

    response = api.create_finding(
        PLACEHOLDER_PART_APPLICATION_ID,
        fixtures.make_shpo_reviewer_headers(reviewer["id"]),
        standard_number=2,
        severity="CONDITION",
        description="Orphan finding.",
    )

    validate_error(response, ApiErrorId.PART_APPLICATION_NOT_FOUND.value, 404)


def test_an_unknown_developer_reference_is_reported_before_an_unknown_property(api):
    """Two dangling references in one body, and the developer is the one reported.

    Both foreign keys in the body point at rows that do not exist. The refusal names
    the developer, not the property, so the body references are resolved in the order
    the contract declares rather than in whatever order is convenient.

    PRD: "Every foreign key supplied in the body resolves to an existing row of its declared parent entity, else that parent entity's not-found error (404)."
    PRD: "A `Developer` opens a project on a recorded building, naming the building through `property_id` and itself through `developer_id`, which must equal the caller's `X-User-ID` — a developer cannot open a project in another taxpayer's name."

    Design: Corner/entities/project_creation_rejects_unknown_developer_id_before_unknown_property_id
    """
    fixtures.set_clock(api, "2026-09-01T00:00:00Z")
    developer = fixtures.create_developer(api)

    response = api.create_project(
        fixtures.make_developer_headers(developer["id"]),
        developer_id=PLACEHOLDER_DEVELOPER_ID,
        property_id=PLACEHOLDER_PROPERTY_ID,
        project_name="Ghost Rehab",
        structure_type="SINGLE_TIER",
        adjusted_basis_cents=60_000_000,
        measuring_period_months=24,
        measuring_period_start_date="2026-09-01",
    )

    error = validate_error(response, ApiErrorId.DEVELOPER_NOT_FOUND.value, 404)
    assert error["error_id"] != ApiErrorId.PROPERTY_NOT_FOUND.value, (
        "the property reference must not be the one reported"
    )
    assert NON_EXISTENT_UUID != PLACEHOLDER_DEVELOPER_ID, (
        "the placeholder ids used here are distinct from the framework's own"
    )
