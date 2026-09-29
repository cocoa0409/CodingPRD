"""The reduction plan: opening it, freezing its criteria, and the governance axis."""

from test_helpers import (
    ALICE,
    BEN_CLASS_B,
    ApiErrorId,
    TEST_USERS,
    USER_IDS,
    assert_reduction_plan,
    create_reduction_plan_payload,
    create_locked_plan,
    make_lead_headers,
    read_plan,
    run_and_clear_analysis,
    setup_selected_scenario,
    STANDARD_CRITERIA,
    submit_for_review,
    validate_error,
    validate_success,
)

LEAD = TEST_USERS["lead_headers"]
COUNSEL = TEST_USERS["counsel_headers"]


def test_new_plan_opens_with_every_declared_zero_point(api):
    """PRD 3.1: "Its `criteria_status` begins at `DRAFT`, its `approval_status` at
    `DRAFT`, and its `warn_status` at `NOT_ASSESSED`. Its `version` begins at 1.
    Every derived figure starts at its zero point: `severance_reserve_cents`,
    `benefit_liability_cents`, `selected_count`, `pool_count`,
    `legal_return_count` and `required_notice_days` all start at 0,
    `owbpa_consideration_days` starts at 21, `owbpa_required` starts false, and
    `earliest_separation_date`, `notice_deadline_utc`, `submitted_by_user_id`
    and `approved_by_user_id` all start null."
    PRD 4: "Endpoints that bring a new resource into existence answer with HTTP
    201; endpoints that read or modify an existing resource answer with HTTP 200."

    Design: Corner/entities/create_reduction_plan_returns_201_with_declared_defaults
    """
    response = api.create_reduction_plan(create_reduction_plan_payload(), LEAD)
    plan = validate_success(response, 201)

    assert_reduction_plan(plan)
    assert plan["criteria_status"] == "DRAFT"
    assert plan["approval_status"] == "DRAFT"
    assert plan["warn_status"] == "NOT_ASSESSED"
    assert plan["version"] == 1
    assert plan["severance_reserve_cents"] == 0
    assert plan["benefit_liability_cents"] == 0
    assert plan["selected_count"] == 0
    assert plan["pool_count"] == 0
    assert plan["legal_return_count"] == 0
    assert plan["required_notice_days"] == 0
    assert plan["owbpa_consideration_days"] == 21
    assert plan["owbpa_required"] is False
    assert plan["earliest_separation_date"] is None
    assert plan["notice_deadline_utc"] is None
    assert plan["submitted_by_user_id"] is None
    assert plan["approved_by_user_id"] is None

    body = response.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")
    assert isinstance(body["meta"]["api_request_timestamp"], str)


def test_lock_criteria_freezes_the_ranking_basis_and_bumps_the_version(api):
    """PRD 3.1: "Locking the criteria advances `criteria_status` from `DRAFT` to
    `LOCKED` and increments the plan's `version` by 1."
    PRD 3.1: "The compliance axis, `warn_status`, moves `NOT_ASSESSED →
    THRESHOLD_PENDING → NOTICES_ISSUED → NOTICE_PERIOD_SATISFIED` and is
    advanced only by system cascades from site recomputation, notice issuance
    and plan execution."

    Design: Corner/state_machines/lock_criteria_moves_plan_criteria_status_to_locked
    """
    plan = validate_success(
        api.create_reduction_plan(create_reduction_plan_payload(), LEAD), 201
    )
    locked = validate_success(api.lock_criteria(plan["id"], LEAD))

    assert locked["criteria_status"] == "LOCKED"
    assert locked["version"] == 2, "locking must increment the plan's version by 1"
    assert locked["approval_status"] == "DRAFT"
    assert locked["warn_status"] == "NOT_ASSESSED"


def test_locking_already_locked_criteria_is_refused(api):
    """PRD 2.6: "Declared transition availability — the target resource must
    currently sit in a state from which the requested transition is declared,
    otherwise `ERR_INVALID_PLAN_STATE`, `ERR_INVALID_SELECTION_STATE`,
    `ERR_INVALID_ANALYSIS_STATE`, `ERR_INVALID_NOTICE_STATE`,
    `ERR_INVALID_OFFER_STATE` or `ERR_INVALID_RESTRICTION_STATE` (409). Applies
    to every state-changing endpoint."
    PRD 3.1: "Locking the criteria advances `criteria_status` from `DRAFT` to
    `LOCKED` and increments the plan's `version` by 1."

    Design: Corner/state_machines/lock_criteria_twice_returns_invalid_plan_state
    """
    plan = create_locked_plan()

    response = api.lock_criteria(plan["id"], LEAD)
    validate_error(response, ApiErrorId.ERR_INVALID_PLAN_STATE.value)
    assert response.status_code == 409

    after = read_plan(plan["id"])
    assert after["criteria_status"] == "LOCKED"
    assert after["version"] == 2, "a rejected lock must not advance the version"


def test_submit_for_review_needs_at_least_one_selected_selection(api):
    """PRD 3.5: "Submitting a plan for review (`DRAFT → IN_LEGAL_REVIEW`) is the
    lead's act and requires that the plan's `criteria_status` is `LOCKED` and
    that its `selected_count` is at least 1; it records the calling `X-User-ID`
    as `submitted_by_user_id` and increments the plan's `version` by 1."
    PRD 2.6: "Declared transition availability — the target resource must
    currently sit in a state from which the requested transition is declared,
    otherwise `ERR_INVALID_PLAN_STATE`, `ERR_INVALID_SELECTION_STATE`,
    `ERR_INVALID_ANALYSIS_STATE`, `ERR_INVALID_NOTICE_STATE`,
    `ERR_INVALID_OFFER_STATE` or `ERR_INVALID_RESTRICTION_STATE` (409). Applies
    to every state-changing endpoint."

    Design: Corner/state_machines/submit_legal_review_without_any_selected_selection_is_rejected
    """
    scn = setup_selected_scenario(select_indexes=(), propose_only_indexes=(0,))

    response = api.submit_legal_review(scn["plan"]["id"], LEAD)
    validate_error(response, ApiErrorId.ERR_INVALID_PLAN_STATE.value)
    assert response.status_code == 409

    plan = read_plan(scn["plan"]["id"])
    assert plan["approval_status"] == "DRAFT"
    assert plan["submitted_by_user_id"] is None
    assert plan["selected_count"] == 0
    assert plan["pool_count"] == 1


def test_returning_a_plan_counts_the_loop_and_frees_the_submitter_slot(api):
    """PRD 3.5: "Returning the plan (`IN_LEGAL_REVIEW → DRAFT`) increments
    `legal_return_count` by 1, clears `submitted_by_user_id` back to null, and
    increments the plan's `version` by 1; a plan may be returned and re-submitted
    any number of times."
    PRD 3.5: "Re-submission after a return is the same transition and overwrites
    `submitted_by_user_id` with the new submitter."

    Design: Corner/state_machines/legal_decision_return_reverts_plan_to_draft_and_counts_the_loop
    """
    scn = setup_selected_scenario(people=(ALICE, BEN_CLASS_B), propose_only_indexes=(1,))
    run_and_clear_analysis(scn["plan"]["id"])
    submit_for_review(scn["plan"]["id"], USER_IDS["LEAD"])

    returned = validate_success(
        api.legal_decision(
            scn["plan"]["id"],
            {
                "decision": "RETURN",
                "comment": "Document the retention rationale for the comparator group.",
            },
            COUNSEL,
        )
    )
    assert returned["approval_status"] == "DRAFT"
    assert returned["legal_return_count"] == 1
    assert returned["submitted_by_user_id"] is None

    resubmitted = validate_success(
        api.submit_legal_review(scn["plan"]["id"], make_lead_headers(USER_IDS["LEAD_2"]))
    )
    assert resubmitted["approval_status"] == "IN_LEGAL_REVIEW"
    assert resubmitted["submitted_by_user_id"] == USER_IDS["LEAD_2"]
    assert resubmitted["approved_by_user_id"] is None


def test_executing_a_draft_plan_is_refused(api):
    """PRD 3.10: "It is admissible only from `APPROVED`, and it demands two
    things of the programme's state."
    PRD 2.6: "Declared transition availability — the target resource must
    currently sit in a state from which the requested transition is declared,
    otherwise `ERR_INVALID_PLAN_STATE`, `ERR_INVALID_SELECTION_STATE`,
    `ERR_INVALID_ANALYSIS_STATE`, `ERR_INVALID_NOTICE_STATE`,
    `ERR_INVALID_OFFER_STATE` or `ERR_INVALID_RESTRICTION_STATE` (409). Applies
    to every state-changing endpoint."

    Design: Corner/state_machines/execute_a_draft_plan_returns_invalid_plan_state
    """
    plan = create_locked_plan()

    response = api.execute_plan(plan["id"], LEAD)
    validate_error(response, ApiErrorId.ERR_INVALID_PLAN_STATE.value)
    assert response.status_code == 409

    assert read_plan(plan["id"])["approval_status"] == "DRAFT"
    restrictions = validate_success(api.list_position_restrictions(COUNSEL))
    assert restrictions == [], "a refused execution mints no rehire restriction"


def test_criteria_weights_must_sum_to_exactly_one_hundred(api):
    """PRD 3.1: "No `criterion_code` may repeat within the array, and the
    `weight_pct` values must sum to exactly 100: a total of 99 or 101 is as
    invalid as a total of 50. A payload whose weights sum to any other number, or
    that repeats a code, is refused with `ERR_CRITERIA_WEIGHT_INVALID`."

    Design: Corner/validations/plan_criteria_weights_not_summing_to_one_hundred_are_rejected
    """
    criteria = [dict(c) for c in STANDARD_CRITERIA]
    criteria[2]["weight_pct"] = 10  # 50 + 30 + 10 = 90

    response = api.create_reduction_plan(
        create_reduction_plan_payload(selection_criteria=criteria), LEAD
    )
    validate_error(response, ApiErrorId.ERR_CRITERIA_WEIGHT_INVALID.value)
    assert response.status_code == 422
