"""
Entity surfaces: declared defaults, stored rows, listings, and the shape of a refusal.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
)

from test_helpers import (
    COUNSEL_HEADERS,
    ESCROW_AGENT_HEADERS,
    fixtures as fx,
    make_lead_organizer_headers,
)
from test_helpers.assertions import (
    assert_fields_equal,
    assert_system_fields,
    assert_two_decimal_places,
)
from test_helpers.factories import (
    DROP,
    organizing_group_payload,
    policy_document_payload,
    stress_scenario_payload,
    subscription_payload,
    vendor_contract_payload,
)
from test_helpers.types import (
    BLOCKED_REASON_NONE,
    CLEARANCE_UNSCREENED,
    COMPOSITION_FORMING,
    CRITICALITY_SIGNIFICANT,
    DOMAIN_LENDING,
    FUNDING_PLEDGED,
    PLAN_DRAFT,
    POLICY_DRAFT,
    SCENARIO_ADVERSE,
    SERVICE_DIGITAL_BANKING,
    STAGE_ORGANIZING,
    VENDOR_EVALUATING,
)


# ---------------------------------------------------------------------------
# Corner / entities
# ---------------------------------------------------------------------------
def test_a_new_organizing_group_carries_every_declared_default(api):
    """
    Opening the file writes back exactly what was declared and nothing the client could
    have chosen: the project is at its first stage, its board is still forming, every count
    and score is zero, nothing is blocking opening, supervision has not begun, and the row
    is at its first version inside the standard object envelope.

    PRD: "A newly opened file starts at `stage` `ORGANIZING` with `composition_status` `FORMING`, with `organizer_count`, `independent_organizer_count`, `max_affiliation_count` and `supervision_year_index` all at 0, `management_composite_score` at 0.00, `opening_blocked_reason` at `NONE`, `supervision_started_at` null, and `version` at 1."
    PRD: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."

    Design: Corner/entities/entity_creation_organizing_group_returns_declared_defaults
    """
    response = api.create_organizing_group(organizing_group_payload(), COUNSEL_HEADERS)
    body = response.json()
    assert body["response_type"] == "object", (
        f"a single created resource is an object envelope, got {body['response_type']!r}"
    )
    assert body["meta"]["api_request_id"].startswith("req_"), (
        f"api_request_id must start with req_: {body['meta']['api_request_id']!r}"
    )

    group = get_success_data(response, expected_status=201)
    assert_system_fields(group, expected_version=1)
    assert_fields_equal(
        group,
        proposed_bank_name="Cascade Charter Bank",
        home_state_code="WA",
        charter_type="NATIONAL",
        stage=STAGE_ORGANIZING,
        composition_status=COMPOSITION_FORMING,
        organizer_count=0,
        independent_organizer_count=0,
        max_affiliation_count=0,
        opening_blocked_reason=BLOCKED_REASON_NONE,
        supervision_started_at=None,
        supervision_year_index=0,
    )
    assert_two_decimal_places(
        group["management_composite_score"], 0.00, "management_composite_score"
    )
    assert group["target_opening_date"].startswith("2027-03-01T00:00:00"), (
        f"target_opening_date must be stored as declared: {group['target_opening_date']!r}"
    )


def test_reading_a_business_plan_returns_the_stored_projections(api):
    """
    A plan read back carries the projections as they were written, with money still in
    whole cents including the negative first-year net income, and with every derived
    counter at the value a plan with no overlays and no predecessor must show.

    PRD: "A new plan begins in `DRAFT` with `stress_scenario_count`, `breach_scenario_count` and `worst_governing_min_leverage_ratio_bps` all 0, and creating it increments the parent group's `version` by one."
    PRD: "`plan_revision_index` is 1 when `supersedes_plan_id` is omitted, and otherwise one more than the superseded plan's own `plan_revision_index`, so a chain of revisions is self-numbering."

    Design: Corner/entities/entity_retrieval_business_plan_get_returns_stored_row
    """
    world = fx.open_group(api)
    plan_id = fx.add_business_plan(api, world)

    plan = fx.read_plan(api, plan_id)
    assert_system_fields(plan, expected_version=1)
    assert_fields_equal(
        plan,
        group_id=world["group_id"],
        opening_tier1_capital_cents=4_000_000_000,
        projected_assets_y3_cents=43_000_000_000,
        projected_loans_y3_cents=28_000_000_000,
        projected_net_income_y1_cents=-250_000_000,
        projected_branch_count=3,
        supersedes_plan_id=None,
        plan_revision_index=1,
        status=PLAN_DRAFT,
        stress_scenario_count=0,
        breach_scenario_count=0,
        worst_governing_min_leverage_ratio_bps=0,
    )


def test_the_organizer_listing_pages_and_narrows_by_independence(api):
    """
    Six organizers sit on the file, three of them independent. A two-row page reports the
    whole matching population and says more remain, while narrowing to the independents
    returns those three alone with nothing beyond the page.

    PRD: "For list responses, the `meta` object carries `limit`, `offset`, `total_count` (the number of rows matching the filters before pagination is applied) and `has_more` (true when rows remain beyond the current page)."
    PRD: "The filters are the channel through which each foreign key becomes reverse-reachable: organizers may be narrowed by `group_id`, `role_on_board`, `qualification_status` and `is_independent`; business plans by `group_id`, `supersedes_plan_id` and `status`; stress scenarios by `business_plan_id`, `scenario_code` and `governing_variant`; capital raises by `group_id` and `status`; subscriptions by `capital_raise_id`, `organizer_id`, `funding_state`, `clearance_state` and `counts_toward_escrow`; regulatory filings by `group_id`, `pinned_business_plan_id`, `authority` and `status`; approval conditions by `filing_id`, `category`, `status` and `is_pre_opening_blocking`; policy documents by `group_id`, `drafted_by_organizer_id`, `adopted_by_organizer_id`, `domain` and `status`; vendor contracts by `group_id`, `service_domain`, `criticality` and `status`; conversion windows by `vendor_contract_id` and `status`; readiness exams by `group_id`, `exam_scope` and `status`; and deviation requests by `group_id`, `baseline_plan_id`, `metric`, `status` and `requires_regulator_approval`."

    Design: Corner/entities/entity_listing_organizers_paginates_and_filters_by_independence
    """
    world = fx.seated_group(api, seats=5, clear=False)
    fx.add_investor_only_organizer(api, world)

    page, meta = validate_paginated(
        api.list_organizers(
            COUNSEL_HEADERS, params={"group_id": world["group_id"], "limit": 2, "offset": 0}
        )
    )
    assert len(page) == 2, f"a limit of 2 must return 2 rows, got {len(page)}"
    assert (meta["limit"], meta["offset"], meta["total_count"], meta["has_more"]) == (
        2,
        0,
        6,
        True,
    ), f"unexpected pagination meta: {meta}"

    independents, ind_meta = validate_paginated(
        api.list_organizers(
            COUNSEL_HEADERS,
            params={
                "group_id": world["group_id"],
                "is_independent": True,
                "limit": 10,
                "offset": 0,
            },
        )
    )
    assert len(independents) == 3, (
        f"exactly three of the six organizers are independent, got {len(independents)}"
    )
    assert (ind_meta["total_count"], ind_meta["has_more"]) == (3, False)
    for row in independents + page:
        assert row["is_independent"] in (True, False)
        assert row["group_id"] == world["group_id"], (
            "no row of either page may belong to another group"
        )
    for row in independents:
        assert row["is_independent"] is True, "the filter must exclude affiliated organizers"


def test_reading_an_unknown_subscription_reports_its_own_not_found_code(api):
    """
    An identifier that names no subscription produces that entity's own not-found code in
    the standard error envelope, with a human-readable message and the same request
    identifier a success would have carried.

    PRD: "The thirteen not-found codes are `ERR_GROUP_NOT_FOUND`, `ERR_ORGANIZER_NOT_FOUND`, `ERR_BUSINESS_PLAN_NOT_FOUND`, `ERR_STRESS_SCENARIO_NOT_FOUND`, `ERR_CAPITAL_RAISE_NOT_FOUND`, `ERR_SUBSCRIPTION_NOT_FOUND`, `ERR_FILING_NOT_FOUND`, `ERR_CONDITION_NOT_FOUND`, `ERR_POLICY_NOT_FOUND`, `ERR_VENDOR_CONTRACT_NOT_FOUND`, `ERR_CONVERSION_WINDOW_NOT_FOUND`, `ERR_EXAM_NOT_FOUND` and `ERR_DEVIATION_NOT_FOUND`, each carrying HTTP 404."
    PRD: "The `message` provides a human-readable explanation of what went wrong."

    Design: Corner/entities/entity_not_found_get_subscription_unknown_id_returns_404
    """
    response = api.get_subscription(NON_EXISTENT_UUID, ESCROW_AGENT_HEADERS)
    error = validate_error(response, "ERR_SUBSCRIPTION_NOT_FOUND", expected_status=404)

    body = response.json()
    assert body["response_type"] == "error", (
        f"a refusal is an error envelope, got {body['response_type']!r}"
    )
    assert isinstance(error["message"], str) and error["message"].strip(), (
        "the error must carry a non-empty human-readable message"
    )
    assert body["meta"]["api_request_id"].startswith("req_"), (
        "the error envelope carries the request identifier too"
    )


def test_opening_a_file_without_a_charter_type_is_a_schema_failure(api):
    """
    The charter type is what later selects the base leverage requirement, so it is not
    optional. Omitting it fails schema validation and no file is opened.

    PRD: "**Request schema** — required fields present and well-typed, enum members declared, numeric ranges and string lengths respected (`ERR_INVALID_REQUEST`)."

    Design: Corner/entities/entity_required_field_missing_charter_type_is_rejected
    """
    error = validate_error(
        api.create_organizing_group(
            organizing_group_payload(charter_type=DROP), COUNSEL_HEADERS
        ),
        "ERR_INVALID_REQUEST",
        expected_status=422,
    )
    assert "id" not in error, (
        "a rejected create must not mint a row identifier: no file was opened"
    )


def test_a_new_vendor_contract_starts_evaluating_with_no_windows(api):
    """
    A vendor is registered long before anyone commits to it, so the contract begins under
    evaluation with an empty conversion calendar, carrying the criticality and diligence
    rating as supplied — a rating of 61 is perfectly acceptable on a contract that is not
    critical.

    PRD: "A new contract begins in `EVALUATING` with `active_window_count` 0, and the group's `version` increments by one."

    Design: Corner/entities/entity_defaults_vendor_contract_starts_evaluating_with_zero_windows
    """
    world = fx.open_group(api)

    contract = get_success_data(
        api.create_vendor_contract(
            vendor_contract_payload(
                world["group_id"],
                service_domain=SERVICE_DIGITAL_BANKING,
                vendor_name="Northlight Digital",
                criticality=CRITICALITY_SIGNIFICANT,
                due_diligence_score=61,
                annual_cost_cents=24_000_000,
                contract_term_months=36,
            ),
            COUNSEL_HEADERS,
        ),
        expected_status=201,
    )
    assert_system_fields(contract, expected_version=1)
    assert_fields_equal(
        contract,
        status=VENDOR_EVALUATING,
        active_window_count=0,
        criticality=CRITICALITY_SIGNIFICANT,
        due_diligence_score=61,
    )


def test_a_subscription_amount_is_shares_times_the_pinned_offering_price(api):
    """
    Money on a subscription is never supplied: 1,250,000 shares at the offering's price of
    1000 cents is 1,250,000,000 cents exactly. The row starts pledged and unscreened, so it
    counts toward nothing yet, and the raise records the pledge without any of it reaching
    the funded or cleared balances.

    PRD: "`amount_cents` is derived as `shares` multiplied by the raise's `offering_price_cents_per_share` — an exact integer multiplication with no rounding possible — and the price is read from the raise once, at creation, and pinned into the row; if the raise's price is later changed, existing `amount_cents` values do not move."
    PRD: "A new subscription starts with `funding_state` `PLEDGED`, `clearance_state` `UNSCREENED` and `counts_toward_escrow` false, then the raise's aggregates and its release waterfall are re-derived and the raise's `version` increments by one."

    Design: Corner/entities/entity_computed_field_subscription_amount_is_shares_times_price
    """
    world = fx.bare_open_raise(api)

    subscription = get_success_data(
        api.create_subscription(
            subscription_payload(
                world["raise_id"], subscriber_name="Olympic Coast Holdings", shares=1_250_000
            ),
            ESCROW_AGENT_HEADERS,
        ),
        expected_status=201,
    )
    assert_fields_equal(
        subscription,
        amount_cents=1_250_000_000,
        funding_state=FUNDING_PLEDGED,
        clearance_state=CLEARANCE_UNSCREENED,
        counts_toward_escrow=False,
    )

    assert_fields_equal(
        fx.read_raise(api, world["raise_id"]),
        subscribed_shares=1_250_000,
        pledged_gross_cents=1_250_000_000,
        funded_gross_cents=0,
        cleared_escrow_cents=0,
        projected_reimbursement_cents=0,
        projected_net_release_cents=0,
    )


def test_system_fields_on_a_policy_document_are_minted_by_the_server(api):
    """
    A freshly drafted policy carries a server-minted identifier and timestamps the client
    never supplied, sits at its first version, records the drafter it named, and leaves the
    adoption and examiner-finding fields empty because neither has happened yet.

    PRD: "A new policy begins in `DRAFT` with `adopted_by_organizer_id`, `adopted_at` and `finding_note` all null, and the parent group's `version` increments by one."
    PRD: "`version` (integer): begins at 1 when the row is created and increments by exactly 1 on every mutation of that row."

    Design: Corner/entities/entity_system_fields_are_server_minted_on_policy_document
    """
    world = fx.composition_met_group(api)

    policy = get_success_data(
        api.create_policy_document(
            policy_document_payload(
                world["group_id"],
                world["o1"],
                domain=DOMAIN_LENDING,
                document_title="Lending and Credit Administration Policy",
            ),
            make_lead_organizer_headers(world["o1"]),
        ),
        expected_status=201,
    )
    assert_system_fields(policy, expected_version=1)
    assert is_valid_uuid(policy["id"]), f"id must be a UUID: {policy['id']!r}"
    assert is_iso8601_timestamp(policy["created_at"]), (
        f"created_at must be an ISO 8601 UTC timestamp: {policy['created_at']!r}"
    )
    assert is_iso8601_timestamp(policy["updated_at"]), (
        f"updated_at must be an ISO 8601 UTC timestamp: {policy['updated_at']!r}"
    )
    assert_fields_equal(
        policy,
        status=POLICY_DRAFT,
        drafted_by_organizer_id=world["o1"],
        adopted_by_organizer_id=None,
        adopted_at=None,
        finding_note=None,
    )


def test_an_undeclared_charter_type_is_rejected_as_an_enum_failure(api):
    """
    The charter type is a closed set of three, because it selects the base leverage
    requirement the plan will be judged against. A fourth value is not a business conflict
    but a schema failure, and no file is opened.

    PRD: "The payload is short: `proposed_bank_name`, the proposed legal name of the de novo bank, between 1 and 120 characters and not blank; `home_state_code`, the two-letter code of the state where the main office will sit, which must be exactly two uppercase letters; `charter_type`, which is one of `NATIONAL`, `STATE_MEMBER` or `STATE_NONMEMBER` and which later selects the base leverage requirement the plan is judged against; and `target_opening_date`, the planned first day of business as an ISO 8601 UTC instant."

    Design: Corner/entities/entity_type_constraint_invalid_charter_type_enum_rejected
    """
    error = validate_error(
        api.create_organizing_group(
            organizing_group_payload(charter_type="FEDERAL_THRIFT"), COUNSEL_HEADERS
        ),
        "ERR_INVALID_REQUEST",
        expected_status=422,
    )
    assert "id" not in error, "a rejected create must not mint a row identifier"


def test_a_stress_overlay_under_an_unknown_plan_stops_at_the_parent(api):
    """
    The plan in the path is resolved before any overlay logic runs, so an identifier naming
    no plan reports the plan's own not-found code. The real plan that does exist is left
    with no overlays attached.

    PRD: "Where a path contains more than one identifier — for example a stress scenario created under a business plan, or a readiness exam scheduled under an organizing group — identifiers are resolved strictly left to right, and the first identifier that resolves to nothing terminates the request with that identifier's own 404."

    Design: Corner/entities/entity_parent_stress_scenario_under_unknown_plan_not_found
    """
    world = fx.open_group(api)
    plan_id = fx.add_business_plan(api, world)

    validate_error(
        api.create_stress_scenario(
            NON_EXISTENT_UUID,
            stress_scenario_payload(SCENARIO_ADVERSE),
            COUNSEL_HEADERS,
        ),
        "ERR_BUSINESS_PLAN_NOT_FOUND",
        expected_status=404,
    )
    assert_fields_equal(fx.read_plan(api, plan_id), stress_scenario_count=0)


def test_naming_a_drafter_from_another_group_is_refused_after_the_row_resolves(api):
    """
    The named drafter exists, so this is not a missing row: it is a row in the wrong place.
    Eligibility is checked after existence, and the refusal names the group mismatch while
    the foreign organizer stays exactly where he belongs and no policy is written.

    PRD: "The named drafter must be an organizer of the same group as the policy, and a drafter from another group is refused with `ERR_DRAFTER_NOT_IN_GROUP`."
    PRD: "Whether the row that *does* exist is also *eligible* — the right group, the right status — is a separate and later check with its own conflict code, described with the workflow it guards."

    Design: Corner/entities/entity_fk_policy_drafter_from_another_group_rejected
    """
    world = fx.composition_met_group(api)
    other = fx.second_group(api)

    validate_error(
        api.create_policy_document(
            policy_document_payload(
                world["group_id"],
                other["ob1"],
                domain=DOMAIN_LENDING,
                document_title="Lending and Credit Administration Policy",
            ),
            make_lead_organizer_headers(world["o1"]),
        ),
        "ERR_DRAFTER_NOT_IN_GROUP",
        expected_status=409,
    )

    policies, meta = validate_paginated(
        api.list_policy_documents(COUNSEL_HEADERS, params={"group_id": world["group_id"]})
    )
    assert meta["total_count"] == 0, (
        f"no policy may have been written for the group, found {meta['total_count']}"
    )
    foreign_organizer = get_success_data(
        api.get_organizer(other["ob1"], COUNSEL_HEADERS)
    )
    assert_fields_equal(foreign_organizer, group_id=other["group_id"])
