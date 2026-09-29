"""The generic rungs of the precedence ladder: existence, authentication, ownership,
version pinning and schema, each answering with its own identifier."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_money_equals,
    create_assessment_payload,
    create_candidate_payload,
    create_offer_payload,
    headers_with_unknown_role,
    headers_without_role,
    make_candidate_headers,
    read_candidate,
    read_practice_group,
    read_questionnaire,
    setup_book,
    setup_config,
    setup_questionnaire_in_draft,
    setup_questionnaire_under_review,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["system_admin_headers"]
COORDINATOR = TEST_USERS["recruiting_coordinator_headers"]
CHAIR = TEST_USERS["committee_chair_headers"]

PROBE_UUID = "00000000-0000-4000-8000-000000000000"


def test_each_collection_answers_a_missing_row_with_its_own_not_found_identifier():
    """Failure yields the 404 code for the resource that could not be found:
    `ERR_PRACTICE_GROUP_NOT_FOUND`, `ERR_SEARCH_FIRM_NOT_FOUND`, `ERR_ENGAGEMENT_NOT_FOUND`,
    `ERR_CANDIDATE_NOT_FOUND`, `ERR_QUESTIONNAIRE_NOT_FOUND`,
    `ERR_CLIENT_BOOK_ENTRY_NOT_FOUND`, `ERR_COLLECTION_RECORD_NOT_FOUND`,
    `ERR_ASSESSMENT_NOT_FOUND`, `ERR_CONFLICT_CHECK_NOT_FOUND`, `ERR_WAIVER_NOT_FOUND`,
    `ERR_DECLINATION_NOT_FOUND`, `ERR_OFFER_NOT_FOUND`, `ERR_VOTE_NOT_FOUND`,
    `ERR_INTEGRATION_PLAN_NOT_FOUND`, `ERR_INTRODUCTION_NOT_FOUND`, or
    `ERR_PERFORMANCE_REVIEW_NOT_FOUND`. Applies to every endpoint carrying a path or body
    resource reference.

    Design: Corner/errors/every_collection_has_its_own_not_found_error_id
    """
    probes = [
        (api_client.get_practice_group, ApiErrorId.ERR_PRACTICE_GROUP_NOT_FOUND),
        (api_client.get_search_firm, ApiErrorId.ERR_SEARCH_FIRM_NOT_FOUND),
        (api_client.get_search_firm_engagement, ApiErrorId.ERR_ENGAGEMENT_NOT_FOUND),
        (api_client.get_candidate, ApiErrorId.ERR_CANDIDATE_NOT_FOUND),
        (api_client.get_questionnaire, ApiErrorId.ERR_QUESTIONNAIRE_NOT_FOUND),
        (api_client.get_client_book_entry, ApiErrorId.ERR_CLIENT_BOOK_ENTRY_NOT_FOUND),
        (api_client.get_collection_record, ApiErrorId.ERR_COLLECTION_RECORD_NOT_FOUND),
        (api_client.get_portability_assessment, ApiErrorId.ERR_ASSESSMENT_NOT_FOUND),
        (api_client.get_conflict_check, ApiErrorId.ERR_CONFLICT_CHECK_NOT_FOUND),
        (api_client.get_conflict_waiver, ApiErrorId.ERR_WAIVER_NOT_FOUND),
        (api_client.get_matter_declination, ApiErrorId.ERR_DECLINATION_NOT_FOUND),
        (api_client.get_offer, ApiErrorId.ERR_OFFER_NOT_FOUND),
        (api_client.get_vote, ApiErrorId.ERR_VOTE_NOT_FOUND),
        (api_client.get_integration_plan, ApiErrorId.ERR_INTEGRATION_PLAN_NOT_FOUND),
        (api_client.get_introduction, ApiErrorId.ERR_INTRODUCTION_NOT_FOUND),
        (api_client.get_performance_review, ApiErrorId.ERR_PERFORMANCE_REVIEW_NOT_FOUND),
    ]

    seen = []
    for getter, expected in probes:
        error = validate_error(getter(PROBE_UUID, ADMIN), expected.value, 404)
        seen.append(error["error_id"])

    assert len(seen) == 16
    assert len(set(seen)) == 16


def test_a_missing_or_unrecognised_role_is_unauthenticated_rather_than_unauthorized():
    """**Authentication** — `X-User-Role` and `X-User-ID` present, and `X-User-Role` one of
    the seven declared roles. Failure: `ERR_UNAUTHENTICATED` (401). Applies to every
    endpoint.
    **Authorization** — `X-User-Role` listed among the target endpoint's roles. Failure:
    `ERR_UNAUTHORIZED` (403). Applies to every endpoint.

    Design: Corner/errors/practice_group_read_with_a_missing_or_unknown_role_returns_unauthenticated
    """
    ctx = setup_config()
    group_id = ctx["practice_group"]["id"]

    roleless = validate_error(
        api_client.get_practice_group(group_id, headers_without_role()),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
        401,
    )
    assert roleless["error_id"] != ApiErrorId.ERR_UNAUTHORIZED.value

    unknown = validate_error(
        api_client.get_practice_group(group_id, headers_with_unknown_role()),
        ApiErrorId.ERR_UNAUTHENTICATED.value,
        401,
    )
    assert unknown["error_id"] != ApiErrorId.ERR_UNAUTHORIZED.value

    group = validate_success(api_client.get_practice_group(group_id, ADMIN))
    assert group["status"] == "OPEN"
    assert read_practice_group(group_id)["active_onboarding_count"] == 0


def test_a_foreign_candidate_submitting_someone_elses_questionnaire_is_not_the_owner():
    """Authorization is by the `X-User-Role` header as described in §2.1; where a role is
    entity-backed, the `X-User-ID` header must additionally resolve to the owning row, or the
    call is refused with `ERR_NOT_RESOURCE_OWNER`.
    Submission is the candidate's own act: the acting `Candidate` must be the questionnaire's
    own candidate, the questionnaire's `status` must be `DRAFT` or `REVISION_REQUESTED`,
    `entry_count` must be at least 1, and the candidate's sourcing engagement must still be
    `ACTIVE`.

    Design: Corner/errors/questionnaire_submit_by_a_foreign_candidate_is_not_resource_owner
    """
    ctx = setup_questionnaire_in_draft()
    setup_book(ctx, "SLIM")
    outsider = validate_success(
        api_client.create_candidate(
            create_candidate_payload(
                ctx["practice_group"]["id"],
                ctx["engagement"]["id"],
                full_name="Priya Raghavan",
            ),
            COORDINATOR,
        ),
        expected_status=201,
    )

    foreign = api_client.submit_questionnaire(
        ctx["questionnaire"]["id"], make_candidate_headers(outsider["id"])
    )
    error = validate_error(foreign, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value, 403)
    assert error["error_id"] != ApiErrorId.ERR_QUESTIONNAIRE_NOT_FOUND.value

    submitted = validate_success(
        api_client.submit_questionnaire(
            ctx["questionnaire"]["id"], ctx["candidate_headers"]
        )
    )
    assert submitted["status"] == "SUBMITTED"
    assert submitted["entry_count"] == 1
    assert read_candidate(outsider["id"])["pipeline_status"] == "SOURCED"


def test_both_pinned_versions_answer_412_with_their_own_identifiers():
    """Creating a `PortabilityAssessment` on a questionnaire requires
    `expected_questionnaire_version`, carrying the `version` of that `LateralQuestionnaire` as
    the client last observed it. If the questionnaire's current `version` differs, the create
    is rejected with `ERR_STALE_QUESTIONNAIRE_VERSION` (HTTP 412).
    Creating a `CompensationOffer` for a candidate requires `expected_candidate_version`,
    carrying the `version` of that `Candidate` as the client last observed it. If the
    candidate's current `version` differs from the supplied value, the create is rejected with
    `ERR_STALE_CANDIDATE_VERSION` (HTTP 412).

    Design: Corner/errors/stale_expected_versions_on_both_occ_endpoints_returns_412
    """
    ctx = setup_questionnaire_under_review("SLIM")
    questionnaire_version = read_questionnaire(ctx["questionnaire"]["id"])["version"]

    stale_lpq = api_client.create_portability_assessment(
        ctx["questionnaire"]["id"],
        create_assessment_payload(questionnaire_version - 1),
        COORDINATOR,
    )
    lpq_error = validate_error(
        stale_lpq, ApiErrorId.ERR_STALE_QUESTIONNAIRE_VERSION.value, 412
    )

    assessment = validate_success(
        api_client.create_portability_assessment(
            ctx["questionnaire"]["id"],
            create_assessment_payload(questionnaire_version),
            COORDINATOR,
        ),
        expected_status=201,
    )
    assert assessment["status"] == "CURRENT"
    assert_money_equals(
        assessment["gross_baseline_total_usd"], 1269000.00, "gross_baseline_total_usd"
    )

    candidate_version = read_candidate(ctx["candidate"]["id"])["version"]
    stale_candidate = api_client.create_offer(
        ctx["candidate"]["id"],
        create_offer_payload(
            assessment["id"],
            candidate_version - 1,
            guaranteed_comp_usd=400000.00,
            signing_bonus_usd=40000.00,
        ),
        CHAIR,
    )
    candidate_error = validate_error(
        stale_candidate, ApiErrorId.ERR_STALE_CANDIDATE_VERSION.value, 412
    )
    assert lpq_error["error_id"] != candidate_error["error_id"]

    offer = validate_success(
        api_client.create_offer(
            ctx["candidate"]["id"],
            create_offer_payload(
                assessment["id"],
                candidate_version,
                guaranteed_comp_usd=400000.00,
                signing_bonus_usd=40000.00,
            ),
            CHAIR,
        ),
        expected_status=201,
    )
    assert offer["status"] == "DRAFTED"
    assert_money_equals(
        offer["total_first_year_comp_usd"], 440000.00, "total_first_year_comp_usd"
    )
    assert_money_equals(
        offer["search_fee_amount_usd"], 110000.00, "search_fee_amount_usd"
    )
    assert_money_equals(
        offer["net_first_year_economics_usd"], 401381.27, "net_first_year_economics_usd"
    )


def test_candidate_numerics_outside_their_declared_ranges_are_schema_failures():
    """A `RecruitingCoordinator` opens the record with the candidate's `full_name` and
    `prior_firm_name` (each 1 to 120 characters), the `target_practice_group_id` of the group
    that would receive the lateral, the `sourcing_engagement_id` of the engagement that
    surfaced them, a `sponsor_user_id` of 1 to 64 characters naming the internal partner
    championing the hire, a `current_standard_rate_usd` greater than zero carried to two
    decimal places (the candidate's standard hourly rate at the prior firm, which becomes the
    denominator of the rate-alignment factor), a `notice_period_days` between 0 and 365
    inclusive, a `non_solicit_days` between 0 and 730 inclusive, and optionally
    `approach_confidential`, which defaults to true when omitted.
    **Schema** — required body fields present, types correct, enum members recognised, numeric
    ranges honoured, array cardinalities honoured, ISO 8601 datetimes parseable, and
    pagination `limit` within 1 through 100 with `offset` at least 0. Failure:
    `ERR_INVALID_REQUEST` (400). Applies to every endpoint.

    Design: Corner/errors/out_of_range_candidate_numerics_returns_invalid_request
    """
    ctx = setup_config()
    group_id = ctx["practice_group"]["id"]
    engagement_id = ctx["engagement"]["id"]

    for bad in (
        {"full_name": "Over Notice", "notice_period_days": 400},
        {"full_name": "Over Solicit", "non_solicit_days": 800},
        {"full_name": "Negative Rate", "current_standard_rate_usd": -875.00},
    ):
        response = api_client.create_candidate(
            create_candidate_payload(group_id, engagement_id, **bad), COORDINATOR
        )
        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    candidate = validate_success(
        api_client.create_candidate(
            create_candidate_payload(group_id, engagement_id, approach_confidential=True),
            COORDINATOR,
        ),
        expected_status=201,
    )
    assert candidate["notice_period_days"] == 45
    assert candidate["non_solicit_days"] == 30
    assert candidate["pipeline_status"] == "SOURCED"
    assert candidate["clearance_status"] == "NOT_STARTED"

    _rows, meta = validate_paginated(api_client.list_candidates(COORDINATOR))
    assert meta["total_count"] == 1
