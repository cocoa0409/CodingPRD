"""Statutory rest minimums, monthly hours-of-service gate, fatigue index (PRD §2.6, §3.2, §3.4)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_call_with_fresh_version,
    api_client,
    assert_rest_period,
    create_employee,
    create_job,
    get_employee,
    issue_call,
    make_employee_headers,
    rest_periods_for,
    set_clock,
    setup_employee_with_monthly_minutes,
    setup_tied_up_assignment,
    validate_error,
    validate_success,
)

MANAGER = TEST_USERS["crew_manager_headers"]
CALLER = TEST_USERS["crew_caller_headers"]


def test_markup_at_599_minutes_of_rest_rejected(api):
    """PRD §3.2: "Marking up from `ON_REST` requires the open period's
    `undisturbed_minutes` to be at least 600; the boundary is inclusive, so a
    mark-up exactly ten hours after `rest_start` succeeds, while anything short
    is rejected with `ERR_REST_NOT_SATISFIED`."

    Design: Difficulty/boundary_precision_check/undisturbed_rest_exactly_600_minutes_passes
    """
    set_clock()
    ctx = setup_tied_up_assignment(tour_minutes=300,
                                   report_time="2026-08-02T06:00:00Z")
    emp_id = ctx["employee"]["id"]
    # Rest opened at tie-up: 2026-08-02T11:00:00Z. 599 minutes later is short.
    set_clock("2026-08-02T20:59:00Z")
    resp = api_client.mark_up_employee(emp_id, make_employee_headers(emp_id))
    validate_error(resp, ApiErrorId.ERR_REST_NOT_SATISFIED)


def test_markup_at_exactly_600_minutes_of_rest_succeeds(api):
    """PRD §2.6: "**Minimum undisturbed rest.** Before marking up from rest, an
    employee's open rest period must show at least 600 minutes — ten hours — of
    undisturbed time. The comparison is inclusive: a mark-up exactly 600 minutes
    after `rest_start` satisfies the requirement."

    Design: Difficulty/boundary_precision_check/undisturbed_rest_exactly_600_minutes_passes
    """
    set_clock()
    ctx = setup_tied_up_assignment(tour_minutes=300,
                                   report_time="2026-08-02T06:00:00Z")
    emp_id = ctx["employee"]["id"]
    # Exactly 600 minutes after the 2026-08-02T11:00:00Z rest_start.
    set_clock("2026-08-02T21:00:00Z")
    resp = api_client.mark_up_employee(emp_id, make_employee_headers(emp_id))
    data = validate_success(resp)
    assert data["availability_status"] == "AVAILABLE"

    rests = rest_periods_for(emp_id)
    assert rests[0]["rest_status"] == "SATISFIED", (
        "a mark-up at exactly 600 minutes must close the period SATISFIED"
    )


def test_rest_period_open_row_shape_after_tieup(api):
    """PRD §3.2: "Rest itself is entered from duty: when an assignment ties up
    or an on-duty employee is relieved by recrew, the employee transitions from
    `ON_ASSIGNMENT` to `ON_REST` and a new rest period opens with `rest_start`
    stamped at that moment, `rest_status` set to `OPEN`, and `rest_end` unset
    for as long as the period remains open."
    PRD §2.4: "The RestPeriod is the sole exception to this pattern — it carries
    only `id` and `created_at`; both `updated_at` and `version` are absent,
    because a rest period is stamped once when it opens and once when it closes,
    with no concurrent writers."

    Design: Corner/entities/rest_period_open_row_shape_after_tieup
    """
    set_clock()
    ctx = setup_tied_up_assignment(tour_minutes=300,
                                   report_time="2026-08-02T06:00:00Z")
    rests = rest_periods_for(ctx["employee"]["id"])
    assert len(rests) == 1
    rest = rests[0]
    assert_rest_period(rest)
    assert rest["rest_status"] == "OPEN"
    assert rest["rest_end"] is None, "rest_end must be unset while the period is OPEN"


def test_chronological_ledger_reads_16080_before_new_tour(api):
    """PRD §3.4: "Duty accumulation is a chronological ledger: it replays the
    employee's assignments in `ON_DUTY`, `TIE_UP_PENDING`, `COMPLETED`, or
    `RECREWED` status whose `on_duty_at` falls in the current calendar month —
    `LAID_OFF` rows contribute nothing — ordered by `on_duty_at` ascending with
    `created_at` ascending as the tie-break, summing each row's elapsed minutes
    (to `off_duty_at`, or to the current time for a tour still `ON_DUTY`)."
    PRD §3.4: "The resulting total is the persisted
    `cumulative_duty_minutes_month`."

    Design: Difficulty/dual_variant_calc/hos_chronological_vs_forward_looking_gate
    """
    ctx = setup_employee_with_monthly_minutes(tour_minutes=16080)
    emp = ctx["employee"]
    assert emp["cumulative_duty_minutes_month"] == 16080, (
        f"chronological ledger must persist 16080, got {emp['cumulative_duty_minutes_month']}"
    )
    assert emp["availability_status"] == "AVAILABLE"


def test_forward_looking_gate_passes_at_exact_projection(api):
    """PRD §3.4: "Then the forward-looking hours-of-service gate runs: the
    employee's month-to-date `cumulative_duty_minutes_month` plus the job's
    projected tour minutes (700 for a `-L` symbol, 100 for `-S`, otherwise 480)
    must not exceed the 16,560-minute monthly cap, with equality passing;
    otherwise the acceptance is rejected with `ERR_HOS_LIMIT_EXCEEDED`
    (HTTP 422)."
    PRD §2.6: "**Monthly duty ceiling.** An employee's cumulative duty within
    one calendar month may not exceed 16,560 minutes — 276 hours. This ceiling
    gates call acceptance (see §3.4) with an inclusive boundary: a projection
    landing exactly on the cap passes."

    Design: Difficulty/dual_variant_calc/hos_chronological_vs_forward_looking_gate
    """
    ctx = setup_employee_with_monthly_minutes(tour_minutes=16080)
    emp_id = ctx["employee"]["id"]
    # Default-tour job: forward projection 16080 + 480 == 16560 == cap.
    job2 = create_job(craft="ENGINEER", origin_terminal="CHI",
                      report_time="2026-08-12T20:00:00Z", crew_required=1)
    call2 = issue_call(job2["id"])
    assert call2["employee_id"] == emp_id
    resp = accept_call_with_fresh_version(call2["id"], emp_id)
    assignment = validate_success(resp, expected_status=201)
    assert assignment["assignment_status"] == "MARKED_UP"


def test_accept_at_exactly_monthly_cap_passes(api):
    """PRD §2.6: "**Monthly duty ceiling.** An employee's cumulative duty within
    one calendar month may not exceed 16,560 minutes — 276 hours. This ceiling
    gates call acceptance (see §3.4) with an inclusive boundary: a projection
    landing exactly on the cap passes."

    Design: Difficulty/boundary_precision_check/monthly_hos_cap_equality_passes_plus_one_fails
    """
    ctx = setup_employee_with_monthly_minutes(tour_minutes=16080)
    emp_id = ctx["employee"]["id"]
    job2 = create_job(craft="ENGINEER", origin_terminal="CHI",
                      report_time="2026-08-12T20:00:00Z", crew_required=1)
    call2 = issue_call(job2["id"])
    resp = accept_call_with_fresh_version(call2["id"], emp_id)
    validate_success(resp, expected_status=201)


def test_accept_one_minute_over_monthly_cap_rejected(api):
    """PRD §3.4: "Then the forward-looking hours-of-service gate runs: the
    employee's month-to-date `cumulative_duty_minutes_month` plus the job's
    projected tour minutes (700 for a `-L` symbol, 100 for `-S`, otherwise 480)
    must not exceed the 16,560-minute monthly cap, with equality passing;
    otherwise the acceptance is rejected with `ERR_HOS_LIMIT_EXCEEDED`
    (HTTP 422)."

    Design: Difficulty/boundary_precision_check/monthly_hos_cap_equality_passes_plus_one_fails
    """
    # cumulative == 16081: default-tour projection 16081 + 480 == 16561 > cap.
    ctx = setup_employee_with_monthly_minutes(tour_minutes=16080,
                                              add_one_minute_tour=True)
    emp_id = ctx["employee"]["id"]
    assert ctx["employee"]["cumulative_duty_minutes_month"] == 16081
    job3 = create_job(craft="ENGINEER", origin_terminal="CHI",
                      report_time="2026-08-13T12:00:00Z", crew_required=1)
    call3 = issue_call(job3["id"])
    assert call3["employee_id"] == emp_id
    resp = accept_call_with_fresh_version(call3["id"], emp_id)
    validate_error(resp, ApiErrorId.ERR_HOS_LIMIT_EXCEEDED)


def test_fatigue_score_zero_at_hire(api):
    """PRD §3.1: "A freshly hired employee starts with `availability_status` set
    to `AVAILABLE`, `cumulative_duty_minutes_month` at 0, and `fatigue_score`
    at 0."

    Design: Difficulty/combinatorial_formula/fatigue_weighted_scoring_multifactor
    """
    emp = create_employee(craft="ENGINEER")
    assert emp["fatigue_score"] == 0


def test_fatigue_score_weighted_sum_after_long_tour(api):
    """PRD §2.6: "The `fatigue_score` itself is a weighted index combining three
    signals: one-half times the employee's month-to-date
    `cumulative_duty_minutes_month` expressed as a percentage of the 16,560-minute
    monthly cap; three-tenths times ten points per consecutive duty day; and
    one-fifth times fifteen points per disturbed rest in the trailing window."
    PRD §2.6: "The weighted sum is clamped to the range 0 through 100 and
    rounded to one decimal place, round-half-up."
    PRD §2.6: "The consecutive-duty-day streak counts the run of consecutive UTC
    calendar days ending today on each of which the employee has at least one
    assignment whose `on_duty_at` falls on that day; the streak is zero whenever
    today itself has no such assignment."

    Design: Difficulty/combinatorial_formula/fatigue_weighted_scoring_multifactor
    """
    # One 16080-minute tour whose on-duty day is 2026-08-01; the streak on
    # 2026-08-12 is 0 (today has no on_duty_at) and there are no disturbed
    # rests, so the score is rhu1(0.5 * 16080/16560 * 100) = 48.6.
    ctx = setup_employee_with_monthly_minutes(tour_minutes=16080)
    emp = ctx["employee"]
    assert emp["cumulative_duty_minutes_month"] == 16080
    assert abs(emp["fatigue_score"] - 48.6) < 1e-9, (
        f"weighted fatigue index must read 48.6, got {emp['fatigue_score']}"
    )


def test_accept_on_declined_call_rejected_invalid_state(api):
    """PRD §3.4: "The call must still be `OFFERED` — accepting a `DECLINED` or
    `EXPIRED` call is `ERR_INVALID_STATE` — and the logical clock must be
    strictly before `expires_at`."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_safety_on_call_accept
    """
    ctx = setup_employee_with_monthly_minutes(tour_minutes=16080,
                                              add_one_minute_tour=True)
    emp_id = ctx["employee"]["id"]
    job3 = create_job(craft="ENGINEER", origin_terminal="CHI",
                      report_time="2026-08-13T12:00:00Z", crew_required=1)
    call3 = issue_call(job3["id"])
    resp = api_client.decline_call(call3["id"], make_employee_headers(emp_id))
    validate_success(resp)

    resp = accept_call_with_fresh_version(call3["id"], emp_id)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_state_check_precedes_hos_gate_on_call_accept(api):
    """PRD §2.9: "Every request passes through a fixed validation pipeline, and
    a failure at any stage short-circuits the stages after it."
    PRD §2.9: "Sixth, state validity: the target entity must sit in a from-state
    listed for the requested transition — a call must be `OFFERED` to accept,
    decline, rescind, or record no-answer; an assignment must be `MARKED_UP` to
    go on duty or lay off; a job must be `BULLETINED` or `CALLING` to issue a
    call — rejected with `ERR_INVALID_STATE` (HTTP 409)."
    PRD §2.9: "Only after all six generic stages pass do the business rules run,
    and they too have a fixed relative order: calling-pool exhaustion
    (`ERR_CALL_POOL_EXHAUSTED`, HTTP 422) first, then the monthly
    hours-of-service gate (`ERR_HOS_LIMIT_EXCEEDED`, HTTP 422), then rest
    satisfaction (`ERR_REST_NOT_SATISFIED`, HTTP 422), then temporal windows
    (`ERR_TEMPORAL_WINDOW`, HTTP 422), then leave conflicts
    (`ERR_LEAVE_CONFLICT`, HTTP 422), then job capacity
    (`ERR_JOB_ALREADY_FILLED`, HTTP 422), then referential consistency
    (`ERR_REFERENTIAL_MISMATCH`, HTTP 422), then uniqueness (`ERR_DUPLICATE`,
    HTTP 409), then stale-version rejection (`ERR_STALE_VERSION`, HTTP 412), and
    finally pay completeness (`ERR_PAY_INCOMPLETE`, HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/state_vs_safety_on_call_accept
    """
    # cumulative == 16081: the month projection would breach the cap, but the
    # call is DECLINED, so the state stage (sixth) must fire first.
    ctx = setup_employee_with_monthly_minutes(tour_minutes=16080,
                                              add_one_minute_tour=True)
    emp_id = ctx["employee"]["id"]
    assert ctx["employee"]["cumulative_duty_minutes_month"] == 16081
    job3 = create_job(craft="ENGINEER", origin_terminal="CHI",
                      report_time="2026-08-13T12:00:00Z", crew_required=1)
    call3 = issue_call(job3["id"])
    api_client.decline_call(call3["id"], make_employee_headers(emp_id))

    # Even with a deliberately stale expected version, state wins over all
    # business checks (HOS, stale-version).
    resp = api_client.accept_call(
        call3["id"], {"expected_job_version": 0}, make_employee_headers(emp_id)
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
