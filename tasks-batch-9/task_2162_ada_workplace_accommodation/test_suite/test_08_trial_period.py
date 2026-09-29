"""Scheduling the trial, scoring its check-ins and resolving it."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_calendar_date,
    assert_effectiveness_review,
    assert_trial_period,
    create_absence,
    create_trial_period_payload,
    decide_case,
    link_absence_to_case,
    move_absence,
    read_case,
    read_employee,
    read_option,
    read_profile,
    read_trial,
    record_review,
    resolve_trial,
    run_sweep,
    schedule_trial,
    set_clock,
    setup_active_trial,
    setup_case_at_decision_pending,
    setup_case_at_trial_setup,
    validate_error,
    validate_paginated,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]

REVIEW_SPECS = ((4, 4, 40), (6, 6, 60), (9, 9, 90))
REVIEW_CLOCKS = ("2026-09-15T08:00:00Z", "2026-10-15T08:00:00Z", "2026-11-15T08:00:00Z")


def _twin_scored_trials():
    """Two trials, identical three-review sequence, divergent scoring_mode."""
    set_clock("2026-08-03T09:00:00Z")
    weighted = setup_case_at_trial_setup(department_code="CS1")
    schedule_trial(
        weighted,
        start_date="2026-09-01",
        end_date="2026-11-30",
        scoring_mode="LATEST_WEIGHTED",
    )
    mean = setup_case_at_trial_setup(department_code="CS2")
    schedule_trial(
        mean,
        start_date="2026-09-01",
        end_date="2026-11-30",
        scoring_mode="CUMULATIVE_MEAN",
    )

    set_clock("2026-09-01T08:00:00Z")
    run_sweep()

    for at, spec in zip(REVIEW_CLOCKS, REVIEW_SPECS):
        set_clock(at)
        record_review(weighted, *spec)
        record_review(mean, *spec)

    weighted["trial"] = read_trial(weighted["trial"]["id"])
    mean["trial"] = read_trial(mean["trial"]["id"])
    return weighted, mean


def test_the_two_scoring_modes_diverge_on_one_review_sequence(api):
    """PRD §3.7: "Each check-in immediately computes its own `review_composite`,
    a blended score on a 0-to-10 scale: average `employee_rating` and
    `manager_rating`, multiply that average by **0.6**, then add
    `objective_metric_pct` divided by 10 and multiplied by **0.4**, and round the
    total half up to four decimal places."
    PRD §3.7: "Under **`CUMULATIVE_MEAN`**, the score is the unweighted mean of
    `review_composite` across every check-in on the trial — their sum divided by
    their count — rounded half up to two decimal places."
    PRD §3.7: "Under **`LATEST_WEIGHTED`**, only the three most recent check-ins
    count. Take the last three in the ordering above (or all of them if fewer
    than three exist) and re-index them so that position one is the latest
    check-in, position two the next-latest and position three the third-latest.
    The nominal recency weights are **0.5, 0.3 and 0.2** in that order."
    PRD §3.7: "A trial reaches `UNDER_REVIEW` in one of two ways: recording the
    **third** check-in moves it `ACTIVE → UNDER_REVIEW`, and so does the daily
    sweep once the logical date reaches its `end_date`."

    Design: Difficulty/dual_variant_calc/trial_scoring_mode_variant_flips_effectiveness_outcome
    """
    weighted, mean = _twin_scored_trials()

    for review, expected in zip(weighted["reviews"], (4.0, 6.0, 9.0)):
        assert_effectiveness_review(review)
        assert review["review_composite"] == expected
    for review, expected in zip(mean["reviews"], (4.0, 6.0, 9.0)):
        assert review["review_composite"] == expected

    assert weighted["trial"]["review_count"] == 3
    assert mean["trial"]["review_count"] == 3
    assert weighted["trial"]["effectiveness_score"] == 7.10, (
        "0.5x9.0 + 0.3x6.0 + 0.2x4.0 is 7.10"
    )
    assert mean["trial"]["effectiveness_score"] == 6.33, "(4.0 + 6.0 + 9.0) / 3 is 6.33"
    assert weighted["trial"]["status"] == "UNDER_REVIEW"
    assert mean["trial"]["status"] == "UNDER_REVIEW"
    assert_trial_period(weighted["trial"])


def test_the_scoring_mode_decides_which_terminal_outcome_is_permitted(api):
    """PRD §3.7: "Three shared guards then apply to the two terminal judgements:
    the trial must be in `UNDER_REVIEW`; `review_count` must be at least **3**,
    and fewer is refused with `ERR_INSUFFICIENT_TRIAL_REVIEWS`; and the requested
    outcome must agree with the computed score against a bar of **7.00** —
    `EFFECTIVE` requires `effectiveness_score` at or above 7.00, `INEFFECTIVE`
    requires it strictly below 7.00 — with disagreement refused as
    `ERR_TRIAL_OUTCOME_MISMATCH`."
    PRD §3.7: "An `EFFECTIVE` resolution sets the trial to `CONCLUDED_EFFECTIVE`
    with `outcome` `EFFECTIVE`, moves the trialed option `SELECTED → IMPLEMENTED`
    while **leaving its `committed_cost_cents` untouched** — the money was
    already committed at selection and stays committed — moves the case
    `TRIAL_ACTIVE → GRANTED_PERMANENT`, and recomputes `review_cadence_days` and
    `review_due_date` under the cadence rule above."

    Design: Difficulty/dual_variant_calc/trial_scoring_mode_variant_flips_effectiveness_outcome
    """
    weighted, mean = _twin_scored_trials()

    mismatch = api.resolve_trial_period(
        mean["trial"]["id"], {"outcome": "EFFECTIVE"}, COORD
    )
    validate_error(mismatch, ApiErrorId.ERR_TRIAL_OUTCOME_MISMATCH)
    assert read_trial(mean["trial"]["id"])["status"] == "UNDER_REVIEW"

    concluded = validate_success(
        api.resolve_trial_period(
            weighted["trial"]["id"], {"outcome": "EFFECTIVE"}, COORD
        ),
        200,
    )
    assert concluded["status"] == "CONCLUDED_EFFECTIVE"
    assert concluded["outcome"] == "EFFECTIVE"

    option = read_option(weighted["case"]["selected_option_id"])
    assert option["status"] == "IMPLEMENTED"
    assert option["committed_cost_cents"] == 29_600, "the money stays committed"
    assert read_case(weighted["case"]["id"])["stage"] == "GRANTED_PERMANENT"


def _aborted_trial_case(department_code):
    set_clock("2026-08-03T09:00:00Z")
    ctx = setup_case_at_trial_setup(department_code=department_code)
    schedule_trial(ctx, start_date="2026-09-01", end_date="2026-11-30")
    resolve_trial(ctx, "ABORT")
    assert ctx["trial"]["status"] == "ABORTED"
    assert read_case(ctx["case"]["id"])["stage"] == "TRIAL_SETUP"
    return ctx


def test_a_start_exactly_seven_days_after_a_prior_end_still_collides(api):
    """PRD §3.7: "First, **trial windows are closed intervals with a mandatory
    washout gap of 7 days**."
    PRD §3.7: "Because both comparisons are inclusive, a candidate starting
    exactly seven days after a prior trial's `end_date` still collides; the
    earliest legal start is eight days after the prior end. A collision is
    refused with `ERR_TRIAL_WINDOW_CONFLICT`."
    PRD §3.7: "Note that an aborted trial still occupies its calendar interval
    for washout purposes, so the replacement trial must clear the seven-day gap
    around it."

    Design: Difficulty/resource_temporal_overlap/trial_washout_closed_interval_rejects_seven_day_gap
    """
    ctx = _aborted_trial_case("CLN")

    response = api.create_trial_period(
        create_trial_period_payload(
            ctx["case"]["id"],
            ctx["case"]["selected_option_id"],
            start_date="2026-12-07",
            end_date="2027-02-28",
        ),
        COORD,
    )
    validate_error(response, ApiErrorId.ERR_TRIAL_WINDOW_CONFLICT)

    _rows, meta = validate_paginated(
        api.list_trial_periods(COORD, {"employee_id": ctx["employee"]["id"]})
    )
    assert meta["total_count"] == 1, "the rejected candidate was never persisted"


def test_a_start_eight_days_after_the_prior_end_clears_the_washout(api):
    """PRD §3.7: "Because both comparisons are inclusive, a candidate starting
    exactly seven days after a prior trial's `end_date` still collides; the
    earliest legal start is eight days after the prior end. A collision is
    refused with `ERR_TRIAL_WINDOW_CONFLICT`."
    PRD §3.7: "The trial copies `employee_id` from the case — that employee, not
    the case, is the resource against which trial windows are deconflicted — and
    is created in `status` `SCHEDULED` with `review_count` at zero,
    `extension_count` at zero, `outcome` `PENDING` and `effectiveness_score`
    null. The case moves `TRIAL_SETUP → TRIAL_ACTIVE`."

    Design: Difficulty/resource_temporal_overlap/trial_washout_closed_interval_rejects_seven_day_gap
    """
    ctx = _aborted_trial_case("CL2")
    aborted = ctx["trial"]

    collides = api.create_trial_period(
        create_trial_period_payload(
            ctx["case"]["id"],
            ctx["case"]["selected_option_id"],
            start_date="2026-12-07",
            end_date="2027-02-28",
        ),
        COORD,
    )
    validate_error(collides, ApiErrorId.ERR_TRIAL_WINDOW_CONFLICT)

    response = api.create_trial_period(
        create_trial_period_payload(
            ctx["case"]["id"],
            ctx["case"]["selected_option_id"],
            start_date="2026-12-08",
            end_date="2027-02-28",
        ),
        COORD,
    )
    replacement = validate_success(response, 201)

    assert replacement["status"] == "SCHEDULED"
    assert replacement["employee_id"] == ctx["employee"]["id"]
    assert replacement["review_count"] == 0
    assert replacement["extension_count"] == 0
    assert replacement["outcome"] == "PENDING"
    assert replacement["effectiveness_score"] is None
    assert read_trial(aborted["id"])["status"] == "ABORTED"
    assert read_case(ctx["case"]["id"])["stage"] == "TRIAL_ACTIVE"

    _rows, meta = validate_paginated(
        api.list_trial_periods(COORD, {"employee_id": ctx["employee"]["id"]})
    )
    assert meta["total_count"] == 2


def _case_with_continuous_leave(department_code):
    set_clock("2026-08-03T09:00:00Z")
    ctx = setup_case_at_trial_setup(department_code=department_code)
    create_absence(
        ctx,
        record_type="FMLA_CONTINUOUS",
        start_date="2026-08-25",
        end_date="2026-10-31",
    )
    return ctx


def test_active_continuous_leave_blocks_the_trial_outright(api):
    """PRD §3.7: "Second, **continuous leave blocks a trial outright**: if any
    absence record for that employee whose `record_type` is `FMLA_CONTINUOUS` or
    `STATE_LEAVE` is in `status` `ACTIVE` and overlaps the candidate interval,
    the schedule is refused with `ERR_TRIAL_BLOCKED_BY_ABSENCE`."
    PRD §3.2: "Activation drives the employee's `employment_status`: to
    `RESTRICTED_DUTY` when the record is a `WC_RESTRICTION`, and to `ON_LEAVE`
    for every other type."

    Design: Difficulty/cross_entity_state_dependency/trial_start_blocked_by_active_continuous_leave
    """
    ctx = _case_with_continuous_leave("HSP")
    activated = move_absence(ctx["absence"], "ACTIVE")
    assert activated["status"] == "ACTIVE"
    assert read_employee(ctx["employee"]["id"])["employment_status"] == "ON_LEAVE"

    response = api.create_trial_period(
        create_trial_period_payload(
            ctx["case"]["id"],
            ctx["case"]["selected_option_id"],
            start_date="2026-09-01",
            end_date="2026-11-30",
        ),
        COORD,
    )
    validate_error(response, ApiErrorId.ERR_TRIAL_BLOCKED_BY_ABSENCE)

    assert read_case(ctx["case"]["id"])["stage"] == "TRIAL_SETUP"
    _rows, meta = validate_paginated(
        api.list_trial_periods(COORD, {"request_id": ctx["case"]["id"]})
    )
    assert meta["total_count"] == 0


def test_the_same_leave_record_still_scheduled_does_not_block_the_trial(api):
    """PRD §3.7: "Second, **continuous leave blocks a trial outright**: if any
    absence record for that employee whose `record_type` is `FMLA_CONTINUOUS` or
    `STATE_LEAVE` is in `status` `ACTIVE` and overlaps the candidate interval,
    the schedule is refused with `ERR_TRIAL_BLOCKED_BY_ABSENCE`."
    PRD §3.2: "Every new record starts in `status` `SCHEDULED`."

    Design: Difficulty/cross_entity_state_dependency/trial_start_blocked_by_active_continuous_leave
    """
    ctx = _case_with_continuous_leave("HS2")
    assert ctx["absence"]["status"] == "SCHEDULED"

    response = api.create_trial_period(
        create_trial_period_payload(
            ctx["case"]["id"],
            ctx["case"]["selected_option_id"],
            start_date="2026-09-01",
            end_date="2026-11-30",
        ),
        COORD,
    )
    trial = validate_success(response, 201)

    assert trial["status"] == "SCHEDULED"
    assert read_case(ctx["case"]["id"])["stage"] == "TRIAL_ACTIVE"


def _ineffective_ready_trial(department_code):
    """A CUMULATIVE_MEAN trial sitting at 6.33, one resolve away from failing."""
    set_clock("2026-08-03T09:00:00Z")
    ctx = setup_case_at_trial_setup(department_code=department_code)
    schedule_trial(
        ctx,
        start_date="2026-09-01",
        end_date="2026-11-30",
        scoring_mode="CUMULATIVE_MEAN",
    )
    set_clock("2026-09-01T08:00:00Z")
    run_sweep()
    for at, spec in zip(REVIEW_CLOCKS, REVIEW_SPECS):
        set_clock(at)
        record_review(ctx, *spec)
    ctx["trial"] = read_trial(ctx["trial"]["id"])
    return ctx


def test_an_ineffective_trial_releases_the_option_and_the_ledger(api):
    """PRD §3.7: "Hop one sets the trial to `CONCLUDED_INEFFECTIVE` with
    `outcome` `INEFFECTIVE`. Hop two, caused by hop one, moves the trialed option
    `SELECTED → TRIAL_FAILED` and releases its `committed_cost_cents` to zero.
    Hop three, caused by hop two, subtracts that released amount from the pinned
    profile's `committed_accommodation_cost_cents`."
    PRD §2.11: "The compensating action fires when an option leaves that set —
    through a failed trial or through a case closing out of renewal review: the
    option's currently held `committed_cost_cents` is subtracted from the
    profile's ledger, and the option's `committed_cost_cents` is then set to
    zero."

    Design: Difficulty/transitive_cascade/ineffective_trial_cascades_five_hops_to_documentation_budget
    """
    ctx = _ineffective_ready_trial("PKG")
    option_id = ctx["case"]["selected_option_id"]
    assert read_option(option_id)["committed_cost_cents"] == 29_600
    assert read_profile(ctx["profile"]["id"])["committed_accommodation_cost_cents"] == 29_600

    trial = resolve_trial(ctx, "INEFFECTIVE")

    assert trial["status"] == "CONCLUDED_INEFFECTIVE"
    assert trial["outcome"] == "INEFFECTIVE"
    assert trial["effectiveness_score"] == 6.33

    option = read_option(option_id)
    assert option["status"] == "TRIAL_FAILED"
    assert option["committed_cost_cents"] == 0

    profile = read_profile(ctx["profile"]["id"])
    assert profile["committed_accommodation_cost_cents"] == 0


def test_an_ineffective_trial_reopens_exploration_and_widens_the_doc_budget(api):
    """PRD §3.7: "Hop four, also caused by hop two, moves the case
    `TRIAL_ACTIVE → OPTION_EXPLORATION`, increments `interactive_round_count` by
    one, and raises the case's `medical_doc_request_limit` by the
    ineffective-trial bonus of one round — still subject to the absolute ceiling
    of four. Hop five, caused by hop four, recomputes
    `documentation_budget_remaining` from the raised limit."
    PRD §3.3: "Add **one** further round if any trial period on this case has
    concluded ineffective — an accommodation that failed in practice legitimately
    reopens the medical question."

    Design: Difficulty/transitive_cascade/ineffective_trial_cascades_five_hops_to_documentation_budget
    """
    ctx = _ineffective_ready_trial("PK2")
    before = read_case(ctx["case"]["id"])
    assert before["medical_doc_request_limit"] == 2
    assert before["documentation_budget_remaining"] == 2

    resolve_trial(ctx, "INEFFECTIVE")

    case = read_case(ctx["case"]["id"])
    assert case["stage"] == "OPTION_EXPLORATION"
    assert case["interactive_round_count"] == 1
    assert case["medical_doc_request_limit"] == 3
    assert case["medical_doc_request_count"] == 0
    assert case["documentation_budget_remaining"] == 3


def test_two_check_ins_renormalise_the_recency_weights(api):
    """PRD §3.7: "Take as many of those weights as there are check-ins in the
    tail and renormalise them by dividing each by their own sum, so that with two
    check-ins the weights become 0.5 and 0.3 each divided by 0.8, and with a
    single check-in the weight is 1."
    PRD §3.7: "A trial reaches `UNDER_REVIEW` in one of two ways: recording the
    **third** check-in moves it `ACTIVE → UNDER_REVIEW`, and so does the daily
    sweep once the logical date reaches its `end_date`."
    PRD §3.7: "The check-in stamps `trial_period_id` from the trial being
    addressed, `reviewer_user_id` from the acting `X-User-ID`, `review_date` as
    the calendar date read from the logical clock, and `review_index`, a 1-based
    ordinal assigned in recording order within the trial."

    Design: Corner/calculations/corner_latest_weighted_renormalises_with_two_reviews
    """
    ctx = setup_active_trial(scoring_mode="LATEST_WEIGHTED", department_code="CNY")

    set_clock("2026-09-15T08:00:00Z")
    first = record_review(ctx, 4, 4, 40)
    set_clock("2026-10-15T08:00:00Z")
    second = record_review(ctx, 6, 6, 60)

    assert first["review_composite"] == 4.0 and first["review_index"] == 1
    assert second["review_composite"] == 6.0 and second["review_index"] == 2

    trial = read_trial(ctx["trial"]["id"])
    assert trial["review_count"] == 2
    assert trial["effectiveness_score"] == 5.25, "6.0 x 0.625 plus 4.0 x 0.375"
    assert trial["status"] == "ACTIVE", "three check-ins are needed to reach review"


def test_the_trial_resolution_guards_fire_in_their_own_turn(api):
    """PRD §3.7: "Any outcome requested from a status that does not admit it is
    refused with `ERR_TRIAL_NOT_RESOLVABLE`."
    PRD §3.7: "Three shared guards then apply to the two terminal judgements:
    the trial must be in `UNDER_REVIEW`; `review_count` must be at least **3**,
    and fewer is refused with `ERR_INSUFFICIENT_TRIAL_REVIEWS`; and the requested
    outcome must agree with the computed score against a bar of **7.00** —
    `EFFECTIVE` requires `effectiveness_score` at or above 7.00, `INEFFECTIVE`
    requires it strictly below 7.00 — with disagreement refused as
    `ERR_TRIAL_OUTCOME_MISMATCH`."
    PRD §3.7: "An `EXTEND` resolution is available only from `UNDER_REVIEW` and
    only while `extension_count` can absorb one more; a trial may be extended at
    most **once**, and a second attempt is refused with
    `ERR_TRIAL_EXTENSION_LIMIT`. Extension increments `extension_count`, pushes
    `end_date` out by **30 days**, and returns the trial `UNDER_REVIEW → ACTIVE`
    so that further check-ins can be recorded."

    Design: Corner/errors/corner_trial_resolution_guard_rails
    """
    set_clock("2026-08-03T09:00:00Z")
    ctx = setup_case_at_trial_setup(department_code="CNX")
    schedule_trial(
        ctx,
        start_date="2026-09-01",
        end_date="2026-11-30",
        scoring_mode="LATEST_WEIGHTED",
    )

    too_early = api.resolve_trial_period(
        ctx["trial"]["id"], {"outcome": "EFFECTIVE"}, COORD
    )
    validate_error(too_early, ApiErrorId.ERR_TRIAL_NOT_RESOLVABLE)

    set_clock("2026-09-01T08:00:00Z")
    run_sweep()
    set_clock("2026-09-15T08:00:00Z")
    record_review(ctx, 4, 4, 40)
    set_clock("2026-11-30T08:00:00Z")
    run_sweep()
    assert read_trial(ctx["trial"]["id"])["status"] == "UNDER_REVIEW"

    too_few = api.resolve_trial_period(
        ctx["trial"]["id"], {"outcome": "EFFECTIVE"}, COORD
    )
    validate_error(too_few, ApiErrorId.ERR_INSUFFICIENT_TRIAL_REVIEWS)

    record_review(ctx, 6, 6, 60)
    record_review(ctx, 9, 9, 90)
    assert read_trial(ctx["trial"]["id"])["effectiveness_score"] == 7.10

    mismatch = api.resolve_trial_period(
        ctx["trial"]["id"], {"outcome": "INEFFECTIVE"}, COORD
    )
    validate_error(mismatch, ApiErrorId.ERR_TRIAL_OUTCOME_MISMATCH)

    extended = validate_success(
        api.resolve_trial_period(ctx["trial"]["id"], {"outcome": "EXTEND"}, COORD), 200
    )
    assert extended["extension_count"] == 1
    assert extended["status"] == "ACTIVE"
    assert_calendar_date(extended["end_date"], "2026-12-30", "end_date")

    set_clock("2026-12-30T08:00:00Z")
    run_sweep()
    assert read_trial(ctx["trial"]["id"])["status"] == "UNDER_REVIEW"

    second_extension = api.resolve_trial_period(
        ctx["trial"]["id"], {"outcome": "EXTEND"}, COORD
    )
    validate_error(second_extension, ApiErrorId.ERR_TRIAL_EXTENSION_LIMIT)
    assert read_trial(ctx["trial"]["id"])["extension_count"] == 1


def test_a_workers_compensation_case_needs_modified_duty_before_any_trial(api):
    """PRD §3.7: "Third, **a workers'-compensation cross-reference must be on
    modified duty**: if the case's `absence_record_id` names a `WC_RESTRICTION`
    record, that record's `status` must be `MODIFIED_DUTY` before any trial may
    begin, and otherwise the schedule is refused with
    `ERR_WC_MODIFIED_DUTY_REQUIRED`."
    PRD §3.7: "If the case's `absence_record_id` is non-null and that absence
    record's `status` is anything other than `CLOSED`, a **90-day** interval also
    applies."
    PRD §3.2: "From `ACTIVE`, a workers'-compensation restriction whose
    `modified_duty_available` is true may move to `MODIFIED_DUTY`, which again
    sets the employee's `employment_status` to `RESTRICTED_DUTY`; requesting
    that move on a record that is not a workers'-compensation restriction, or on
    one where modified duty is not available, is refused with
    `ERR_ABSENCE_TRANSITION_INVALID`, as is any `to_status` that is not reachable
    from the record's current status."

    Design: Corner/errors/corner_wc_restriction_requires_modified_duty_before_trial
    """
    set_clock("2026-08-03T09:00:00Z")
    ctx = setup_case_at_decision_pending(department_code="CN0")
    absence = create_absence(
        ctx,
        record_type="WC_RESTRICTION",
        start_date="2026-08-01",
        end_date="2026-12-31",
        restriction_severity=3,
        modified_duty_available=True,
    )
    move_absence(absence, "ACTIVE")
    link_absence_to_case(ctx, absence)

    case = decide_case(
        ctx,
        decision="GRANT_WITH_TRIAL",
        selected_option_id=ctx["options"][0]["id"],
    )
    assert case["review_cadence_days"] == 90
    assert_calendar_date(case["review_due_date"], "2026-11-01", "review_due_date")

    blocked = api.create_trial_period(
        create_trial_period_payload(
            case["id"], case["selected_option_id"], start_date="2026-09-01",
            end_date="2026-11-30",
        ),
        COORD,
    )
    validate_error(blocked, ApiErrorId.ERR_WC_MODIFIED_DUTY_REQUIRED)

    move_absence(absence, "MODIFIED_DUTY")

    allowed = validate_success(
        api.create_trial_period(
            create_trial_period_payload(
                case["id"], case["selected_option_id"], start_date="2026-09-01",
                end_date="2026-11-30",
            ),
            COORD,
        ),
        201,
    )
    assert allowed["status"] == "SCHEDULED"
    assert allowed["employee_id"] == ctx["employee"]["id"]
    assert read_case(case["id"])["stage"] == "TRIAL_ACTIVE"


def test_a_sweep_phase_never_re_runs_within_one_pass(api):
    """PRD §2.5: "**Phases never re-run within one sweep.** A trial promoted from
    `SCHEDULED` to `ACTIVE` in phase 4 is not eligible for phase 5 in the same
    sweep — it needs a second sweep to reach `UNDER_REVIEW`."
    PRD §2.5: "Every `TrialPeriod` in status `SCHEDULED` whose `start_date` is at
    or before the current logical date moves to `ACTIVE`."
    PRD §2.5: "Every `TrialPeriod` in status `ACTIVE` whose `end_date` is at or
    before the current logical date moves to `UNDER_REVIEW`."

    Design: Corner/calculations/corner_daily_sweep_phases_never_rerun_within_one_pass
    """
    set_clock("2026-08-03T09:00:00Z")
    ctx = setup_case_at_trial_setup(department_code="CNN")
    schedule_trial(ctx, start_date="2026-09-01", end_date="2026-09-05")

    set_clock("2026-09-20T00:00:00Z")
    first = run_sweep()
    assert first["trials_activated"] == 1
    assert first["trials_moved_to_review"] == 0
    assert read_trial(ctx["trial"]["id"])["status"] == "ACTIVE"

    second = run_sweep()
    assert second["trials_activated"] == 0
    assert second["trials_moved_to_review"] == 1

    trial = read_trial(ctx["trial"]["id"])
    assert trial["status"] == "UNDER_REVIEW"
    assert trial["effectiveness_score"] is None, "no check-ins were ever recorded"
