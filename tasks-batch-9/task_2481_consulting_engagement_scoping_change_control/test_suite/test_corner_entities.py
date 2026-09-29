"""Entity surfaces: declared defaults, computed fields, audit set and identity."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import ConsultingApiClient
from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_audit_fields,
    assert_fields,
    assert_freshly_created,
    assert_no_mutable_audit_fields,
    assert_pagination_meta,
    assert_two_dp,
)


def test_client_creation_returns_every_declared_default(
    api: ConsultingApiClient,
) -> None:
    """The three system properties are written by the server, not the caller.

    PRD 3.1: "The two counters `completed_engagement_count` and
    `at_risk_engagement_count` both begin at 0 and are maintained entirely by
    the system: the former counts the client's engagements whose delivery has
    reached `CLOSED` and feeds the relationship term of the qualification score,
    while the latter counts the client's engagements currently carrying at least
    one risk escalation of severity `HIGH` or `CRITICAL` in `OPEN`,
    `ACKNOWLEDGED` or `DELIVERY_HELD` handling state."

    Design: Corner/entities/client_creation_returns_defaults_and_system_fields
    """
    fx.set_clock(api, C.SEED_CLOCK)

    response = api.create_client(F.client_payload(), fx.PRACTICE_ADMIN_HEADERS)
    row = validate_success(response, 201)

    envelope = response.json()
    assert envelope["response_type"] == "object"
    assert envelope["meta"]["api_request_id"].startswith("req_")
    assert_fields(
        row,
        status="ACTIVE",
        completed_engagement_count=0,
        at_risk_engagement_count=0,
        client_code=C.SEED_CLIENT_CODE,
        decision_process=C.SEED_CLIENT_DECISION_PROCESS,
        stated_budget_authority_cents=C.SEED_CLIENT_BUDGET_AUTHORITY_CENTS,
        adverse_party_codes=list(C.SEED_CLIENT_ADVERSE_PARTY_CODES),
    )
    assert_freshly_created(row)


def test_consultant_retrieval_returns_the_stored_row(
    api: ConsultingApiClient,
) -> None:
    """The read echoes the written row, computed lead count included.

    PRD 3.1: "The computed `active_lead_deliverable_count` begins at 0 and
    always equals the number of deliverables anywhere in the firm whose lead is
    this consultant and whose status has not yet reached `ACCEPTED`."

    Design: Corner/entities/consultant_retrieval_returns_stored_row
    """
    sc = fx.build_master_data(api)

    row = get_success_data(api.get_consultant(sc.partner_id, sc.partner))

    assert_fields(
        row,
        id=sc.partner_id,
        grade=C.GRADE_PARTNER,
        practice_code=C.SEED_PRACTICE_CODE,
        cost_rate_cents_per_hour=C.SEED_PARTNER_COST_RATE,
        quality_reviewer_certified=False,
        active_lead_deliverable_count=0,
    )


def test_opportunity_listing_paginates_with_a_stable_total_count(
    api: ConsultingApiClient,
) -> None:
    """total_count counts filter matches, not page contents.

    PRD 2.3: "The `meta` block of a list response carries `limit`, `offset`,
    `total_count` and `has_more`, where `total_count` is the number of rows
    matching the supplied filters before pagination is applied and `has_more`
    is true when rows remain beyond the current page."

    Design: Corner/entities/opportunity_listing_paginates_with_total_count
    """
    sc = fx.build_screening_pursuit(api)
    for _ in range(2):
        fx.build_sibling_screening_pursuit(sc)

    first, meta = validate_paginated(
        api.list_opportunities(
            sc.partner, {"client_id": sc.client_id, "limit": 2, "offset": 0}
        )
    )
    assert len(first) == 2
    assert_pagination_meta(meta, total_count=3, has_more=True)
    assert meta["limit"] == 2 and meta["offset"] == 0

    second, meta_two = validate_paginated(
        api.list_opportunities(
            sc.partner, {"client_id": sc.client_id, "limit": 2, "offset": 2}
        )
    )
    assert len(second) == 1
    assert_pagination_meta(meta_two, total_count=3, has_more=False)
    assert {row["id"] for row in first}.isdisjoint({row["id"] for row in second})


def test_an_unknown_opportunity_id_returns_the_entity_specific_404(
    api: ConsultingApiClient,
) -> None:
    """A well-formed identifier that resolves to nothing is a 404, not an empty 200.

    PRD 2.5: "A missing row yields HTTP 404 with the error code specific to the
    entity that was not found: `ERR_CLIENT_NOT_FOUND`,
    `ERR_CONSULTANT_NOT_FOUND`, `ERR_OPPORTUNITY_NOT_FOUND`,
    `ERR_DELIVERABLE_NOT_FOUND`, `ERR_SOW_NOT_FOUND`,
    `ERR_ENGAGEMENT_NOT_FOUND`, `ERR_CHANGE_REQUEST_NOT_FOUND`,
    `ERR_TIME_ENTRY_NOT_FOUND`, `ERR_QUALITY_REVIEW_NOT_FOUND`,
    `ERR_RISK_ESCALATION_NOT_FOUND` or `ERR_SATISFACTION_ASSESSMENT_NOT_FOUND`."

    Design: Corner/entities/opportunity_not_found_returns_404
    """
    sc = fx.build_master_data(api)

    response = api.get_opportunity(C.NON_EXISTENT_ID, sc.partner)

    validate_error(response, E.ERR_OPPORTUNITY_NOT_FOUND)
    body = response.json()
    assert body["response_type"] == "error"
    assert isinstance(body["data"]["message"], str) and body["data"]["message"]


def test_an_opportunity_missing_a_required_field_writes_nothing(
    api: ConsultingApiClient,
) -> None:
    """estimated_value_cents is required, and its absence is a shape error.

    PRD 3.2: "It also carries `requested_practice_code`, the practice the client
    is buying, drawn from the same four-value set as a consultant's practice;
    `estimated_value_cents`, the firm's own estimate of contract value, which
    must be greater than zero and which becomes the denominator of the
    budget-coverage term in scoring; `stated_budget_cents`, the budget the client
    verbally states at intake, which must be zero or greater; the boolean
    `decision_maker_identified`, true only when an economic buyer with signature
    authority has actually been named; the requested delivery window
    `target_start_date` and `target_end_date`, both plain `YYYY-MM-DD` dates; and
    `objective_summary`, a one-paragraph statement of the client's objective."

    Design: Corner/entities/opportunity_missing_required_field_returns_invalid_request
    """
    sc = fx.build_master_data(api)
    payload = F.opportunity_payload(sc.client_id, sc.partner_id, sc.manager_id)
    payload.pop("estimated_value_cents")

    validate_error(api.create_opportunity(payload, sc.partner), E.ERR_INVALID_REQUEST)

    _, meta = validate_paginated(
        api.list_opportunities(sc.partner, {"client_id": sc.client_id})
    )
    assert_pagination_meta(meta, total_count=0, has_more=False)


def test_a_fresh_opportunity_carries_the_declared_empty_lists(
    api: ConsultingApiClient,
) -> None:
    """Nothing about the scope narrative is supplied at intake.

    PRD 3.2: "Every new pursuit lands in `SCREENING` status with
    `conflict_status` at `NOT_CHECKED`, an empty `screened_adverse_party_codes`
    list, empty `assumptions`, `exclusions` and `client_responsibilities` lists,
    and null values for `verified_budget_cents`, `qualification_score_verified`,
    `total_estimated_hours`, `scope_discount_pct`,
    `baseline_effort_cost_cents`, `longest_dependency_chain` and
    `baselined_at`."

    Design: Corner/entities/opportunity_scope_lists_default_to_empty_arrays
    """
    sc = fx.build_master_data(api)

    row = fx.open_pursuit(sc)

    assert_fields(
        row,
        status="SCREENING",
        conflict_status="NOT_CHECKED",
        assumptions=[],
        exclusions=[],
        client_responsibilities=[],
        screened_adverse_party_codes=[],
        verified_budget_cents=None,
        origin_engagement_id=None,
        baselined_at=None,
    )


def test_the_intake_score_is_computed_and_the_baseline_figures_stay_null(
    api: ConsultingApiClient,
) -> None:
    """Two computed families: one written at once, one deferred to baselining.

    PRD 3.2: "At intake, the budget figure fed into the budget ratio is
    `stated_budget_cents`, the client's self-reported number, and the result is
    written to `qualification_score_intake` while `verified_budget_cents`
    remains null."

    Design: Corner/entities/opportunity_intake_score_and_hours_are_computed_not_input
    """
    sc = fx.build_master_data(api)

    row = fx.open_pursuit(sc)

    # 30 * 0.80 + 40 * 0.60 + 20 + 0, never submitted by the caller
    assert_two_dp(row, "qualification_score_intake", 68.00)
    assert_fields(
        row,
        qualification_score_verified=None,
        total_estimated_hours=None,
        scope_discount_pct=None,
        baseline_effort_cost_cents=None,
        longest_dependency_chain=None,
    )


def test_the_audit_set_is_server_generated_and_moves_only_on_writes(
    api: ConsultingApiClient,
) -> None:
    """A PATCH moves updated_at and version and leaves identity alone.

    PRD 2.4: "`version` is an integer that starts at 1 when the row is created
    and is incremented by exactly 1 on every mutation of that row, including
    mutations that a cascade from another entity performs rather than a direct
    client write."

    Design: Corner/entities/system_fields_are_server_generated_on_every_write
    """
    sc = fx.build_scoped_pursuit(api)
    before = fx.read_deliverable(sc, sc.d1_id)
    assert_audit_fields(before)

    get_success_data(
        api.patch_deliverable(
            sc.d1_id, {"name": "Current-state diagnostic (rev A)"}, sc.manager
        )
    )

    after = fx.read_deliverable(sc, sc.d1_id)
    assert_fields(
        after,
        id=before["id"],
        created_at=before["created_at"],
        version=before["version"] + 1,
        name="Current-state diagnostic (rev A)",
        status=C.DELIVERABLE_PLANNED,
    )
    assert after["updated_at"].startswith("2026-08-03T09:00:00")


def test_an_unknown_consultant_grade_is_refused_and_stored_nowhere(
    api: ConsultingApiClient,
) -> None:
    """grade is a closed four-value enum.

    PRD 3.1: "A consultant carries a `name` of between 1 and 120 characters,
    required; a `grade`, which must be `PARTNER`, `MANAGER`, `CONSULTANT` or
    `ANALYST` and which selects the billing rate every fee formula in this
    system reaches for; a `practice_code`, one of `OPS`, `STRATEGY`, `DIGITAL` or
    `RISK`; and a `cost_rate_cents_per_hour`, the individual's internal cost
    rate, which must be greater than zero."

    Design: Corner/entities/consultant_invalid_grade_enum_returns_invalid_request
    """
    fx.set_clock(api, C.SEED_CLOCK)
    payload = F.consultant_payload(name="X. Nobody", grade="DIRECTOR")

    validate_error(
        api.create_consultant(payload, fx.PRACTICE_ADMIN_HEADERS), E.ERR_INVALID_REQUEST
    )

    _, meta = validate_paginated(
        api.list_consultants(fx.PRACTICE_ADMIN_HEADERS, {"grade": C.GRADE_PARTNER})
    )
    assert_pagination_meta(meta, total_count=0, has_more=False)


def test_an_inverted_planned_window_is_refused_as_a_date_range(
    api: ConsultingApiClient,
) -> None:
    """The range rule is distinct from the shape and enum rules.

    PRD 3.3: "and a planned window of `planned_start_date` and
    `planned_end_date`, where the end must be strictly after the start."

    Design: Corner/entities/deliverable_invalid_planned_window_returns_invalid_date_range
    """
    sc = fx.build_qualified_pursuit(api)
    fx.edit_scope(sc)
    payload = F.deliverable_payload(
        sc.opportunity_id,
        name="Backwards window",
        planned_start_date="2026-10-15",
        planned_end_date="2026-09-01",
    )

    validate_error(api.create_deliverable(payload, sc.manager), E.ERR_INVALID_DATE_RANGE)

    _, meta = validate_paginated(
        api.list_deliverables(sc.manager, {"opportunity_id": sc.opportunity_id})
    )
    assert_pagination_meta(meta, total_count=0, has_more=False)


def test_a_satisfaction_assessment_is_immutable_and_filed_only_once(
    api: ConsultingApiClient,
) -> None:
    """No version field, no second row, and the first row is left as filed.

    PRD 3.9: "An assessment filed against an engagement that has not reached
    `CLOSED` is refused with `ERR_ENGAGEMENT_STATE_INVALID`, and so is a second
    assessment against an engagement that already has one."

    PRD 2.4: "`SatisfactionAssessment` is the single exception. It is immutable
    once created — there is no operation that edits or withdraws one — and it
    therefore carries only `id` and `created_at`."

    Design: Corner/entities/satisfaction_assessment_is_immutable_and_single
    """
    sc = fx.build_closed_engagement(api)
    filed = fx.file_satisfaction(sc)

    assert_no_mutable_audit_fields(filed)
    # 0.40 * 8 + 0.35 * 7 + 0.25 * 9 plus the 0.25 referral bonus
    assert_two_dp(filed, "csat_score", 8.15)

    response = api.create_satisfaction_assessment(
        F.satisfaction_payload(
            sc.engagement_id, delivery_score=10, value_score=10, communication_score=10
        ),
        sc.client_contact,
    )

    validate_error(response, E.ERR_ENGAGEMENT_STATE_INVALID)
    rows, meta = validate_paginated(
        api.list_satisfaction_assessments(
            sc.partner, {"engagement_id": sc.engagement_id}
        )
    )
    assert_pagination_meta(meta, total_count=1, has_more=False)
    assert_two_dp(rows[0], "csat_score", 8.15)


def test_a_deliverable_naming_an_unknown_pursuit_is_a_body_foreign_key_404(
    api: ConsultingApiClient,
) -> None:
    """The parent arrives in the body here, and its absence is still a 404.

    PRD 2.10: "Existence checks follow — path identifiers first, then body
    foreign keys, both at HTTP 404."

    Design: Corner/entities/deliverable_unknown_opportunity_id_returns_not_found
    """
    sc = fx.build_master_data(api)
    payload = F.deliverable_payload(C.NON_EXISTENT_ID, name="Orphan")

    validate_error(
        api.create_deliverable(payload, sc.manager), E.ERR_OPPORTUNITY_NOT_FOUND
    )

    _, meta = validate_paginated(api.list_deliverables(sc.manager, {}))
    assert_pagination_meta(meta, total_count=0, has_more=False)


def test_a_time_entry_against_another_pursuits_deliverable_is_out_of_scope(
    api: ConsultingApiClient,
) -> None:
    """Both foreign keys resolve; the relationship between them does not.

    PRD 3.7: "The named deliverable must belong to the same pursuit as the named
    engagement, otherwise `ERR_DELIVERABLE_NOT_IN_ENGAGEMENT_SCOPE`."

    Design: Corner/entities/time_entry_cross_opportunity_deliverable_returns_scope_error
    """
    sc = fx.build_started_engagement(api)
    sibling = fx.build_sibling_pursuit(
        sc,
        # The clock has already reached the delivery phase, so this second
        # pursuit needs a target start that is not in the past (PRD 2.10).
        target_start_date="2026-10-01",
        objective_summary="Working-capital diagnostic",
        deliverables=[dict(C.SEED_D1, name="Payables baseline")],
    )
    outsider_id = sibling.d1_id

    response = api.create_time_entry(
        F.time_entry_payload(
            sc.engagement_id, outsider_id, sc.partner_id, C.SEED_WEEK_1, 8.0
        ),
        sc.partner,
    )

    validate_error(response, E.ERR_DELIVERABLE_NOT_IN_ENGAGEMENT_SCOPE)
    assert_two_dp(fx.read_engagement(sc), "approved_hours_burned", 0.00)
    _, meta = validate_paginated(
        api.list_time_entries(sc.manager, {"engagement_id": sc.engagement_id})
    )
    assert_pagination_meta(meta, total_count=0, has_more=False)

    # The identical call against an in-scope deliverable is accepted
    accepted = fx.log_time(sc, 8.0, C.SEED_WEEK_1)
    assert_fields(accepted, deliverable_id=sc.d1_id, status=C.TIME_ENTRY_SUBMITTED)
