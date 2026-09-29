"""Denial, the thirty-day appeal window, the supplement loop and remand."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    advance_case,
    api_client,
    assert_appeal,
    assert_calendar_date,
    assert_denial_record,
    assess_option,
    decide_case,
    file_appeal,
    propose_option,
    read_appeal,
    read_case,
    read_denial,
    read_employee,
    read_option,
    read_profile,
    run_sweep,
    seal_case,
    set_clock,
    setup_appeal_under_review,
    setup_case_at_option_exploration,
    setup_case_denied_out_of_doc_pending,
    setup_denied_case,
    start_appeal_review,
    unseal_case,
    validate_error,
    validate_paginated,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
APPEAL = TEST_USERS["appeal_officer_headers"]

TWO_DUTIES = ({"criticality_weight": 5}, {"criticality_weight": 5})
HOIST = {
    "one_time_cost_cents": 100_003,
    "recurring_monthly_cost_cents": 4_315,
    "implementation_days": 30,
}


def test_an_already_appealed_denial_reports_its_state_not_the_lapsed_window(api):
    """PRD §3.8: "Three conditions gate the filing: the denial record's `status`
    must still be `ISSUED`, otherwise `ERR_DENIAL_NOT_APPEALABLE`; the current
    logical-clock date must be on or before `appeal_deadline_date`, otherwise
    `ERR_APPEAL_WINDOW_CLOSED`; and the case must not be sealed."
    PRD §2.6: "When a request violates more than one rule, exactly one error is
    returned, and which one is fully determined."
    PRD §3.7: "`appeal_deadline_date` is set to the issuance date plus **30
    days**; appeals must be filed on or before that date."

    Design: Difficulty/priority_pair_validation_conflict/denial_state_outranks_appeal_window_expiry
    """
    set_clock("2026-08-03T09:00:00Z")
    ctx = setup_denied_case(
        denial_basis="DIRECT_THREAT",
        rationale_text="A stool obstructs the fire egress lane at this register.",
        department_code="RET",
    )
    assert_calendar_date(
        ctx["denial"]["appeal_deadline_date"], "2026-09-02", "appeal_deadline_date"
    )

    set_clock("2026-08-05T09:00:00Z")
    file_appeal(ctx, "The egress lane concern can be resolved by relocating the stool.")
    assert read_denial(ctx["denial"]["id"])["status"] == "APPEALED"

    set_clock("2026-10-01T09:00:00Z")
    response = api.create_appeal(
        ctx["denial"]["id"],
        {"grounds_text": "Filing a second appeal on the same denial."},
        ctx["employee_headers"],
    )
    error = validate_error(response, ApiErrorId.ERR_DENIAL_NOT_APPEALABLE)
    assert error["error_id"] != "ERR_APPEAL_WINDOW_CLOSED", (
        "the state gate is evaluated before the window gate"
    )
    assert response.status_code == 409


def test_the_rejected_second_appeal_leaves_the_denial_and_case_alone(api):
    """PRD §3.8: "Three conditions gate the filing: the denial record's `status`
    must still be `ISSUED`, otherwise `ERR_DENIAL_NOT_APPEALABLE`; the current
    logical-clock date must be on or before `appeal_deadline_date`, otherwise
    `ERR_APPEAL_WINDOW_CLOSED`; and the case must not be sealed."
    PRD §3.8: "The denial record moves `ISSUED → APPEALED` with `appeal_count`
    incremented by one, and the case moves `DENIED → UNDER_APPEAL`."

    Design: Difficulty/priority_pair_validation_conflict/denial_state_outranks_appeal_window_expiry
    """
    set_clock("2026-08-03T09:00:00Z")
    ctx = setup_denied_case(
        denial_basis="DIRECT_THREAT",
        rationale_text="A stool obstructs the fire egress lane at this register.",
        department_code="RE2",
    )
    set_clock("2026-08-05T09:00:00Z")
    file_appeal(ctx, "The egress lane concern can be resolved by relocating the stool.")

    set_clock("2026-10-01T09:00:00Z")
    response = api.create_appeal(
        ctx["denial"]["id"],
        {"grounds_text": "Filing a second appeal on the same denial."},
        ctx["employee_headers"],
    )
    validate_error(response, ApiErrorId.ERR_DENIAL_NOT_APPEALABLE)

    denial = read_denial(ctx["denial"]["id"])
    assert denial["appeal_count"] == 1
    assert denial["status"] == "APPEALED"
    assert read_case(ctx["case"]["id"])["stage"] == "UNDER_APPEAL"

    _rows, meta = validate_paginated(api.list_denial_appeals(ctx["denial"]["id"], COORD))
    assert meta["total_count"] == 1


def test_the_appeal_returns_to_under_review_after_a_supplement_round(api):
    """PRD §3.8: "From `UNDER_REVIEW` the same officer may ask for more material
    with `REQUEST_SUPPLEMENT`, moving the appeal
    `UNDER_REVIEW → SUPPLEMENT_REQUESTED`; this is allowed only while
    `supplement_count` is still below the ceiling of **two**."
    PRD §3.8: "The case's own `Employee` then answers with `SUBMIT_SUPPLEMENT`,
    which requires that `X-User-ID` equals the case's `employee_id` and that
    `supplement_count` can absorb one more round; it increments
    `supplement_count` by one and returns the appeal
    `SUPPLEMENT_REQUESTED → UNDER_REVIEW`."

    Design: Difficulty/non_linear_state_machine/appeal_cycles_under_review_through_supplement_requested
    """
    set_clock("2026-08-03T09:00:00Z")
    ctx = setup_appeal_under_review(
        denial_basis="NOT_QUALIFIED",
        rationale_text="Perimeter patrol cannot be restructured at this post.",
        department_code="SEC",
    )
    assert ctx["appeal"]["status"] == "UNDER_REVIEW"

    requested = validate_success(
        api.transition_appeal(
            ctx["appeal"]["id"], {"action": "REQUEST_SUPPLEMENT"}, APPEAL
        ),
        200,
    )
    assert requested["status"] == "SUPPLEMENT_REQUESTED"

    submitted = validate_success(
        api.transition_appeal(
            ctx["appeal"]["id"],
            {"action": "SUBMIT_SUPPLEMENT"},
            ctx["employee_headers"],
        ),
        200,
    )
    assert_appeal(submitted)
    assert submitted["status"] == "UNDER_REVIEW", (
        "the appeal holds the same status it held before REQUEST_SUPPLEMENT"
    )
    assert submitted["supplement_count"] == 1


def test_the_supplement_loop_leaves_the_stay_counter_and_the_case_alone(api):
    """PRD §3.8: "An `AppealOfficer` takes an appeal in `FILED` under review with
    `START_REVIEW`, which requires that the case's `confidentiality_posture` is
    not `SEALED` and that the officer is not the coordinator who issued the
    denial; the appeal moves `FILED → UNDER_REVIEW` and `appeal_officer_user_id`
    is stamped from the acting `X-User-ID`."
    PRD §3.8: "The denial record moves `ISSUED → APPEALED` with `appeal_count`
    incremented by one, and the case moves `DENIED → UNDER_APPEAL`."
    PRD §3.7: "`appeal_deadline_date` is set to the issuance date plus **30
    days**; appeals must be filed on or before that date."

    Design: Difficulty/non_linear_state_machine/appeal_cycles_under_review_through_supplement_requested
    """
    set_clock("2026-08-03T09:00:00Z")
    ctx = setup_appeal_under_review(
        denial_basis="NOT_QUALIFIED",
        rationale_text="Perimeter patrol cannot be restructured at this post.",
        department_code="SE2",
    )
    assert read_case(ctx["case"]["id"])["stage"] == "UNDER_APPEAL"

    validate_success(
        api.transition_appeal(
            ctx["appeal"]["id"], {"action": "REQUEST_SUPPLEMENT"}, APPEAL
        ),
        200,
    )
    validate_success(
        api.transition_appeal(
            ctx["appeal"]["id"],
            {"action": "SUBMIT_SUPPLEMENT"},
            ctx["employee_headers"],
        ),
        200,
    )

    appeal = read_appeal(ctx["appeal"]["id"])
    assert appeal["stay_count"] == 0, "no unauthorized disclosure stayed this appeal"
    assert appeal["appeal_officer_user_id"] == "APPEAL-1"
    assert read_case(ctx["case"]["id"])["stage"] == "UNDER_APPEAL"

    denial = read_denial(ctx["denial"]["id"])
    assert_denial_record(denial)
    assert denial["status"] == "APPEALED"
    assert_calendar_date(
        denial["appeal_deadline_date"], "2026-09-02", "appeal_deadline_date"
    )


def _remand_ready_case(department_code):
    """A denial with a cleared alternative and a hardship-blocked sibling."""
    set_clock("2026-08-03T09:00:00Z")
    ctx = setup_case_at_option_exploration(
        functions=TWO_DUTIES,
        department_code=department_code,
        department_annual_budget_cents=1_500_000,
        employer_annual_budget_cents=800_000_000,
    )
    propose_option(
        ctx, covers=[ctx["functions"][1]["id"]], option_code="OPT-VAN-LIFT", **HOIST
    )
    propose_option(
        ctx,
        covers="all",
        option_code="OPT-ROUTE-SWAP",
        category="JOB_RESTRUCTURING",
        one_time_cost_cents=40_000,
        implementation_days=10,
    )
    advance_case(ctx, "HARDSHIP_REVIEW")
    assess_option(ctx, ctx["options"][0], "SITE_LOCAL")
    assess_option(ctx, ctx["options"][1], "SITE_LOCAL")
    advance_case(ctx, "DECISION_PENDING")
    decide_case(
        ctx,
        decision="DENY",
        denial_basis="UNDUE_HARDSHIP",
        rationale_text="The tail-lift exceeds the department accommodation budget.",
        alternative_option_id=ctx["options"][1]["id"],
    )
    rows, _meta = validate_paginated(
        api_client.list_denial_records(COORD, {"request_id": ctx["case"]["id"]})
    )
    ctx["denial"] = rows[-1]
    file_appeal(ctx, "The employer-wide budget was never considered.")
    start_appeal_review(ctx)
    return ctx


def test_a_remand_vacates_the_denial_and_restores_the_denial_count(api):
    """PRD §3.8: "Hop one sets the appeal to `REMANDED` with `outcome`
    `REMANDED`. Hop two, caused by hop one, moves the denial record
    `APPEALED → VACATED`. Hop three, caused by hop two, decrements the
    employee's `lifetime_denial_count` by one and moves the case
    `UNDER_APPEAL → OPTION_EXPLORATION` with `interactive_round_count`
    incremented by one."
    PRD §3.2: "`lifetime_denial_count` is the number of denial records on this
    employee's cases whose `status` is `ISSUED`, `APPEALED` or `FINAL`; a denial
    that has been `VACATED` is excluded, which is why vacating a denial
    decrements the count."

    Design: Difficulty/transitive_cascade/appeal_remand_cascades_five_hops_to_superseded_assessments
    """
    ctx = _remand_ready_case("DLV")
    assert read_employee(ctx["employee"]["id"])["lifetime_denial_count"] == 1

    decided = validate_success(
        api.decide_appeal(ctx["appeal"]["id"], {"outcome": "REMAND"}, APPEAL), 200
    )
    assert decided["status"] == "REMANDED"
    assert decided["outcome"] == "REMANDED"

    assert read_denial(ctx["denial"]["id"])["status"] == "VACATED"
    assert read_employee(ctx["employee"]["id"])["lifetime_denial_count"] == 0

    case = read_case(ctx["case"]["id"])
    assert case["stage"] == "OPTION_EXPLORATION"
    assert case["interactive_round_count"] == 1


def test_a_remand_resets_the_blocked_options_and_wipes_their_verdicts(api):
    """PRD §3.8: "Hop four, caused by hop three, resets every option on the case
    currently in `HARDSHIP_BLOCKED` back to `PROPOSED` and sets the case's
    `blocked_option_count` to zero. Hop five, caused by hop four, moves every
    undue-hardship assessment belonging to one of those reset options and
    currently in `status` `CURRENT` to `SUPERSEDED` — the case returns to
    exploration with its financial verdicts wiped, so the options must be
    assessed afresh."

    Design: Difficulty/transitive_cascade/appeal_remand_cascades_five_hops_to_superseded_assessments
    """
    ctx = _remand_ready_case("DL4")
    blocked, cleared = ctx["options"]
    blocked_assessment = ctx["assessments"][0]
    assert read_option(blocked["id"])["status"] == "HARDSHIP_BLOCKED"

    validate_success(
        api.decide_appeal(ctx["appeal"]["id"], {"outcome": "REMAND"}, APPEAL), 200
    )

    assert read_option(blocked["id"])["status"] == "PROPOSED"
    assert read_case(ctx["case"]["id"])["blocked_option_count"] == 0

    rows, _meta = validate_paginated(
        api.list_hardship_assessments(blocked["id"], COORD)
    )
    superseded = [r for r in rows if r["id"] == blocked_assessment["id"]][0]
    assert superseded["status"] == "SUPERSEDED"

    assert read_option(cleared["id"])["status"] == "CLEARED", (
        "the cleared branch is untouched by the remand"
    )
    assert read_case(ctx["case"]["id"])["cleared_option_count"] == 1
    assert read_profile(ctx["profile"]["id"])["committed_accommodation_cost_cents"] == 0


def test_the_sweep_finalises_a_denial_nobody_appealed(api):
    """PRD §3.8: "The daily sweep finalises any denial record still in `ISSUED`
    whose `appeal_count` is zero once the logical date has passed strictly beyond
    `appeal_deadline_date`: the record moves `ISSUED → FINAL`, the case moves
    `DENIED → DENIED_FINAL`, and the employee's `open_case_count` is decremented
    by one."
    PRD §2.5: "The sweep response carries `swept_at` plus seven counters:
    `doc_requests_expired`, `absence_records_activated`,
    `absence_records_exhausted`, `trials_activated`, `trials_moved_to_review`,
    `requests_moved_to_renewal_due` and `denials_finalized`."
    PRD §3.7: "The case moves to stage `DENIED` with `decision` `DENY`, and the
    employee's `lifetime_denial_count` is incremented by one."

    Design: Corner/state_machines/corner_sweep_finalizes_unappealed_denial_after_window
    """
    set_clock("2026-08-03T09:00:00Z")
    ctx = setup_denied_case(
        denial_basis="NOT_QUALIFIED",
        rationale_text="No role at this site accommodates the restriction.",
        department_code="CNI",
    )
    assert_calendar_date(
        ctx["denial"]["appeal_deadline_date"], "2026-09-02", "appeal_deadline_date"
    )

    set_clock("2026-09-03T00:00:00Z")
    counters = run_sweep()
    assert counters["denials_finalized"] == 1

    assert read_denial(ctx["denial"]["id"])["status"] == "FINAL"
    assert read_case(ctx["case"]["id"])["stage"] == "DENIED_FINAL"

    employee = read_employee(ctx["employee"]["id"])
    assert employee["open_case_count"] == 0
    assert employee["lifetime_denial_count"] == 1


def test_the_appeal_action_guards_and_the_supplement_ceiling(api):
    """PRD §3.8: "An appeal progresses through an `action` of `START_REVIEW`,
    `REQUEST_SUPPLEMENT` or `SUBMIT_SUPPLEMENT`, and any action not reachable
    from the appeal's current status is refused with
    `ERR_APPEAL_NOT_ACTIONABLE`."
    PRD §3.8: "The first three are reachable only from `UNDER_REVIEW` and only by
    the officer whose `X-User-ID` matches the appeal's own
    `appeal_officer_user_id`; `DISMISS` is additionally reachable from `FILED`."
    PRD §3.8: "That loop is the negotiation inside the appeal, and it may run at
    most twice; a third supplement round in either direction is refused with
    `ERR_APPEAL_SUPPLEMENT_LIMIT`."

    Design: Corner/errors/corner_appeal_action_and_supplement_guard_rails
    """
    ctx = setup_case_denied_out_of_doc_pending(department_code="CNJ")
    assert_calendar_date(
        ctx["denial"]["appeal_deadline_date"], "2026-09-16", "appeal_deadline_date"
    )
    file_appeal(ctx, "The provider letter was sent inside the window.")

    premature = api.decide_appeal(ctx["appeal"]["id"], {"outcome": "UPHOLD"}, APPEAL)
    validate_error(premature, ApiErrorId.ERR_APPEAL_NOT_ACTIONABLE)
    assert read_appeal(ctx["appeal"]["id"])["status"] == "FILED"

    start_appeal_review(ctx)
    for _ in range(2):
        validate_success(
            api.transition_appeal(
                ctx["appeal"]["id"], {"action": "REQUEST_SUPPLEMENT"}, APPEAL
            ),
            200,
        )
        validate_success(
            api.transition_appeal(
                ctx["appeal"]["id"],
                {"action": "SUBMIT_SUPPLEMENT"},
                ctx["employee_headers"],
            ),
            200,
        )

    appeal = read_appeal(ctx["appeal"]["id"])
    assert appeal["supplement_count"] == 2
    assert appeal["status"] == "UNDER_REVIEW"

    third = api.transition_appeal(
        ctx["appeal"]["id"], {"action": "REQUEST_SUPPLEMENT"}, APPEAL
    )
    validate_error(third, ApiErrorId.ERR_APPEAL_SUPPLEMENT_LIMIT)
    assert read_appeal(ctx["appeal"]["id"])["status"] == "UNDER_REVIEW"
    assert read_case(ctx["case"]["id"])["interactive_process_integrity_score"] == 100


def test_a_filing_one_day_past_the_deadline_is_out_of_time(api):
    """PRD §3.8: "Three conditions gate the filing: the denial record's `status`
    must still be `ISSUED`, otherwise `ERR_DENIAL_NOT_APPEALABLE`; the current
    logical-clock date must be on or before `appeal_deadline_date`, otherwise
    `ERR_APPEAL_WINDOW_CLOSED`; and the case must not be sealed."
    PRD §3.7: "`appeal_deadline_date` is set to the issuance date plus **30
    days**; appeals must be filed on or before that date."

    Design: Corner/errors/corner_appeal_window_closed_after_deadline
    """
    ctx = setup_case_denied_out_of_doc_pending(department_code="CNK")
    assert_calendar_date(
        ctx["denial"]["appeal_deadline_date"], "2026-09-16", "appeal_deadline_date"
    )

    set_clock("2026-09-17T00:00:00Z")
    response = api.create_appeal(
        ctx["denial"]["id"],
        {"grounds_text": "Filed one day after the window closed."},
        ctx["employee_headers"],
    )
    validate_error(response, ApiErrorId.ERR_APPEAL_WINDOW_CLOSED)

    denial = read_denial(ctx["denial"]["id"])
    assert denial["status"] == "ISSUED"
    assert denial["appeal_count"] == 0
    assert read_case(ctx["case"]["id"])["stage"] == "DENIED", (
        "no sweep has run, so the case is not yet DENIED_FINAL"
    )


def test_a_degraded_process_score_forces_a_remand_instead_of_an_uphold(api):
    """PRD §3.8: "`UPHOLD` is the outcome the integrity score can veto. It
    requires that the case's `interactive_process_integrity_score` is at least
    **60**; when the score has fallen below that threshold, the employer's own
    process failed and the appeal must be remanded rather than upheld, so the
    request is refused with `ERR_APPEAL_MUST_REMAND`."
    PRD §3.9: "**Unauthorized disclosure.** Count the disclosure rows on the case
    whose `authorized` is false. Each one costs **30 points**."
    PRD §3.9: "A `ComplianceAuditor`, exclusively, may override the posture by
    supplying a `to_posture` of `RESTRICTED`, which is permitted only while the
    case is currently `SEALED` and moves it `SEALED → RESTRICTED`."

    Design: Corner/errors/corner_appeal_must_remand_when_integrity_below_threshold
    """
    ctx = setup_case_denied_out_of_doc_pending(department_code="CN9")
    file_appeal(ctx, "The employer never engaged with the interactive process.")

    seal_case(ctx, count=2)
    assert read_case(ctx["case"]["id"])["confidentiality_posture"] == "SEALED"
    unsealed = unseal_case(ctx)
    assert unsealed["confidentiality_posture"] == "RESTRICTED"
    assert unsealed["interactive_process_integrity_score"] == 40

    start_appeal_review(ctx)

    vetoed = api.decide_appeal(ctx["appeal"]["id"], {"outcome": "UPHOLD"}, APPEAL)
    validate_error(vetoed, ApiErrorId.ERR_APPEAL_MUST_REMAND)
    assert read_appeal(ctx["appeal"]["id"])["status"] == "UNDER_REVIEW"

    remanded = validate_success(
        api.decide_appeal(ctx["appeal"]["id"], {"outcome": "REMAND"}, APPEAL), 200
    )
    assert remanded["status"] == "REMANDED"
    assert read_denial(ctx["denial"]["id"])["status"] == "VACATED"
    assert read_employee(ctx["employee"]["id"])["lifetime_denial_count"] == 0

    case = read_case(ctx["case"]["id"])
    assert case["stage"] == "OPTION_EXPLORATION"
    assert case["interactive_round_count"] == 1
