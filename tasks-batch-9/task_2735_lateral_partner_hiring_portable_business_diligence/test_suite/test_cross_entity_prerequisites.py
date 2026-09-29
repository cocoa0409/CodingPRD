"""Cross-aggregate prerequisites: a write into one aggregate refused because the state
of a different aggregate is not yet right."""

from test_helpers import (
    ApiErrorId,
    EXPECTED_SLIM_BOOK,
    TEST_USERS,
    api_client,
    assert_instant_equals,
    assert_money_equals,
    create_assessment,
    create_assessment_payload,
    create_integration_plan_payload,
    read_candidate,
    read_client_book_entry,
    read_practice_group,
    read_questionnaire,
    request_revision_payload,
    setup_approved_offer,
    setup_questionnaire_under_review,
    setup_submitted_questionnaire,
    terminate_engagement_payload,
    validate_error,
    validate_success,
)

COORDINATOR = TEST_USERS["recruiting_coordinator_headers"]


def test_an_integration_plan_cannot_be_drafted_before_the_candidate_is_hired():
    """A `PracticeGroupLeader` creates it against a candidate whose `pipeline_status` is
    `HIRED`, naming the `practice_group_id` that will receive them, the `offer_id` of the
    accepted offer the plan implements, an `onboarding_start_date` and an
    `onboarding_end_date` that must be strictly later than the start, a
    `planned_standard_rate_usd` greater than zero carried to two decimal places, and a
    `cross_sell_target_count` between 0 and 50 inclusive that records how many
    introductions the business plan commits to.
    The new plan lands with `status` `DRAFT` and both `introduction_count` and
    `completed_introduction_count` at `0`.
    Failure yields the invalid-state code for that entity:
    `ERR_CANDIDATE_INVALID_STATE`, `ERR_QUESTIONNAIRE_INVALID_STATE`,
    `ERR_ENGAGEMENT_INVALID_STATE`, `ERR_ASSESSMENT_INVALID_STATE`,
    `ERR_CONFLICT_CHECK_INVALID_STATE`, `ERR_WAIVER_INVALID_STATE`,
    `ERR_DECLINATION_INVALID_STATE`, `ERR_OFFER_INVALID_STATE`,
    `ERR_INTEGRATION_PLAN_INVALID_STATE`, or `ERR_INTRODUCTION_INVALID_STATE` (all 409).

    Design: Difficulty/cross_entity_state_dependency/integration_plan_create_requires_candidate_hired
    """
    ctx = setup_approved_offer("SLIM")
    assert read_candidate(ctx["candidate"]["id"])["pipeline_status"] == "OFFER_OUT"

    payload = create_integration_plan_payload(
        ctx["practice_group"]["id"], ctx["offer"]["id"]
    )
    response = api_client.create_integration_plan(
        ctx["candidate"]["id"], payload, ctx["leader_headers"]
    )
    validate_error(response, ApiErrorId.ERR_CANDIDATE_INVALID_STATE.value)

    validate_success(
        api_client.accept_offer(ctx["offer"]["id"], ctx["candidate_headers"])
    )

    plan = validate_success(
        api_client.create_integration_plan(
            ctx["candidate"]["id"], payload, ctx["leader_headers"]
        ),
        expected_status=201,
    )
    assert plan["status"] == "DRAFT"
    assert plan["introduction_count"] == 0
    assert plan["completed_introduction_count"] == 0

    # Drafting a plan does not consume onboarding capacity; activation does.
    assert read_practice_group(ctx["practice_group"]["id"])["active_onboarding_count"] == 0


def test_accepting_the_offer_commits_the_guarantee_and_crystallises_the_search_fee():
    """**Hop 2**: the candidate moves `OFFER_OUT → HIRED`, with `resignation_date` and
    `hire_date` both set to the current logical clock and `earliest_start_date` computed
    as that instant advanced by `notice_period_days` days.
    The money then converts rather than releases: the group's
    `reserved_guarantee_budget_usd` is reduced by `guaranteed_comp_usd`, its
    `committed_guarantee_total_usd` is increased by the same amount, and
    `available_guarantee_budget_usd` is **unchanged** — the reservation becomes a
    commitment.

    Design: Difficulty/cross_entity_state_dependency/integration_plan_create_requires_candidate_hired
    """
    ctx = setup_approved_offer("SLIM")

    accepted = validate_success(
        api_client.accept_offer(ctx["offer"]["id"], ctx["candidate_headers"])
    )
    assert accepted["status"] == "ACCEPTED"
    assert_instant_equals(accepted["accepted_at"], "2026-08-01T00:00:00.000Z", "accepted_at")

    candidate = read_candidate(ctx["candidate"]["id"])
    assert candidate["pipeline_status"] == "HIRED"
    assert_instant_equals(
        candidate["resignation_date"], "2026-08-01T00:00:00.000Z", "resignation_date"
    )
    assert_instant_equals(candidate["hire_date"], "2026-08-01T00:00:00.000Z", "hire_date")
    assert_instant_equals(
        candidate["earliest_start_date"], "2026-09-15T00:00:00.000Z", "earliest_start_date"
    )

    group = read_practice_group(ctx["practice_group"]["id"])
    assert_money_equals(
        group["committed_guarantee_total_usd"], 500000.00, "committed_guarantee_total_usd"
    )
    assert_money_equals(
        group["reserved_guarantee_budget_usd"], 0.00, "reserved_guarantee_budget_usd"
    )
    assert_money_equals(
        group["available_guarantee_budget_usd"], 4500000.00, "available_guarantee_budget_usd"
    )

    engagement = validate_success(
        api_client.get_search_firm_engagement(ctx["engagement"]["id"], COORDINATOR)
    )
    assert engagement["fee_status"] == "FEE_DUE"
    assert engagement["fee_basis"] == "DIRECT_PLACEMENT"
    assert_money_equals(engagement["fee_amount_usd"], 137500.00, "fee_amount_usd")


def test_an_assessment_cannot_be_run_while_the_questionnaire_is_only_submitted():
    """The questionnaire's `status` must be `UNDER_REVIEW` or `ACCEPTED`.
    Failure yields the invalid-state code for that entity:
    `ERR_CANDIDATE_INVALID_STATE`, `ERR_QUESTIONNAIRE_INVALID_STATE`,
    `ERR_ENGAGEMENT_INVALID_STATE`, `ERR_ASSESSMENT_INVALID_STATE`,
    `ERR_CONFLICT_CHECK_INVALID_STATE`, `ERR_WAIVER_INVALID_STATE`,
    `ERR_DECLINATION_INVALID_STATE`, `ERR_OFFER_INVALID_STATE`,
    `ERR_INTEGRATION_PLAN_INVALID_STATE`, or `ERR_INTRODUCTION_INVALID_STATE` (all 409).

    Design: Difficulty/cross_entity_state_dependency/assessment_create_requires_questionnaire_under_review
    """
    ctx = setup_submitted_questionnaire("SLIM")
    submitted = read_questionnaire(ctx["questionnaire"]["id"])
    assert submitted["status"] == "SUBMITTED"

    response = api_client.create_portability_assessment(
        submitted["id"],
        create_assessment_payload(submitted["version"]),
        COORDINATOR,
    )
    error = validate_error(response, ApiErrorId.ERR_QUESTIONNAIRE_INVALID_STATE.value)
    assert error["error_id"] != ApiErrorId.ERR_STALE_QUESTIONNAIRE_VERSION.value

    reviewing = validate_success(
        api_client.start_review_questionnaire(submitted["id"], COORDINATOR)
    )
    assert reviewing["status"] == "UNDER_REVIEW"

    assessment = create_assessment(ctx)
    assert assessment["status"] == "CURRENT"
    assert assessment["governing_basis"] == "VALIDATED"
    assert assessment["entry_count_in_scope"] == 1


def test_the_accepted_assessment_becomes_the_questionnaires_latest_pointer():
    """**Supersession and staleness.** Creating an assessment writes it with `status`
    `CURRENT`, turns every earlier assessment on the same questionnaire whose `status` is
    `CURRENT` or `STALE` to `SUPERSEDED`, writes the new assessment's identifier into the
    questionnaire's `latest_assessment_id`, and increments the questionnaire's `version`
    by 1.
    `gross_baseline_total_usd` is the plain sum of every in-scope entry's
    `baseline_portable_amount_usd`.

    Design: Difficulty/cross_entity_state_dependency/assessment_create_requires_questionnaire_under_review
    """
    ctx = setup_submitted_questionnaire("SLIM")
    validate_success(
        api_client.start_review_questionnaire(ctx["questionnaire"]["id"], COORDINATOR)
    )

    assessment = create_assessment(ctx)

    questionnaire = read_questionnaire(ctx["questionnaire"]["id"])
    assert questionnaire["status"] == "UNDER_REVIEW"
    assert questionnaire["entry_count"] == 1
    assert questionnaire["latest_assessment_id"] == assessment["id"]

    assert_money_equals(
        assessment["gross_baseline_total_usd"],
        EXPECTED_SLIM_BOOK["gross_baseline_total_usd"],
        "gross_baseline_total_usd",
    )
    assert_money_equals(
        assessment["adjusted_portable_total_usd"],
        EXPECTED_SLIM_BOOK["adjusted_portable_total_usd"],
        "adjusted_portable_total_usd",
    )
    assert (
        read_client_book_entry(ctx["entries"]["Northwind Holdings"]["id"])[
            "portable_status"
        ]
        == "VALIDATED"
    )


def test_a_questionnaire_cannot_be_resubmitted_once_its_engagement_is_terminated():
    """Submission is the candidate's own act: the acting `Candidate` must be the
    questionnaire's own candidate, the questionnaire's `status` must be `DRAFT` or
    `REVISION_REQUESTED`, `entry_count` must be at least 1, and the candidate's sourcing
    engagement must still be `ACTIVE`.
    Submitting with an empty book is refused with `ERR_EMPTY_CLIENT_BOOK`; submitting
    through a dead engagement is refused with `ERR_ENGAGEMENT_INVALID_STATE`.

    Design: Difficulty/cross_entity_state_dependency/questionnaire_submit_requires_engagement_active
    """
    ctx = _setup_questionnaire_sent_back_for_revision()

    validate_success(
        api_client.terminate_search_firm_engagement(
            ctx["engagement"]["id"],
            terminate_engagement_payload(
                reason="Search firm breached the confidentiality undertaking."
            ),
            COORDINATOR,
        )
    )

    response = api_client.submit_questionnaire(
        ctx["questionnaire"]["id"], ctx["candidate_headers"]
    )
    validate_error(response, ApiErrorId.ERR_ENGAGEMENT_INVALID_STATE.value)

    questionnaire = read_questionnaire(ctx["questionnaire"]["id"])
    assert questionnaire["status"] == "REVISION_REQUESTED"
    assert questionnaire["revision_round"] == 1
    assert questionnaire["entry_count"] == 1


def test_termination_waives_the_fee_and_leaves_the_candidate_where_it_stood():
    """A coordinator may terminate an `ACTIVE` engagement, supplying a `reason`; the
    engagement moves `ACTIVE → TERMINATED`, its `fee_status` is set to `FEE_WAIVED`, its
    `fee_basis` is reset to `NONE`, and its `fee_amount_usd` is reset to `0.00`.
    Termination deliberately cascades nowhere: candidates whose `sourcing_engagement_id`
    names this engagement and whose `pipeline_status` is `SOURCED` or `APPROACHED` are
    left untouched and remain sourceable.

    Design: Difficulty/cross_entity_state_dependency/questionnaire_submit_requires_engagement_active
    """
    ctx = _setup_questionnaire_sent_back_for_revision()

    terminated = validate_success(
        api_client.terminate_search_firm_engagement(
            ctx["engagement"]["id"], terminate_engagement_payload(), COORDINATOR
        )
    )
    assert terminated["status"] == "TERMINATED"
    assert terminated["fee_status"] == "FEE_WAIVED"
    assert terminated["fee_basis"] == "NONE"
    assert_money_equals(terminated["fee_amount_usd"], 0.00, "fee_amount_usd")

    candidate = read_candidate(ctx["candidate"]["id"])
    assert candidate["pipeline_status"] == "DILIGENCE"
    assert candidate["clearance_status"] == "NOT_STARTED"

    firm = validate_success(
        api_client.get_search_firm(ctx["search_firm"]["id"], COORDINATOR)
    )
    assert firm["engagement_count"] == 1


# ----------------------------------------------------------------------
# Local scenario glue
# ----------------------------------------------------------------------


def _setup_questionnaire_sent_back_for_revision():
    """SLIM BOOK questionnaire pushed back once, so it sits in REVISION_REQUESTED with
    revision_round 1 and is submittable again."""
    ctx = setup_questionnaire_under_review("SLIM")
    ctx["questionnaire"] = validate_success(
        api_client.request_revision_questionnaire(
            ctx["questionnaire"]["id"], request_revision_payload(), COORDINATOR
        )
    )
    return ctx
