"""Assignment lifecycle: on-duty, tie-up cascades, lay-off, completion (PRD §3.4)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_call_with_fresh_version,
    api_client,
    get_employee,
    get_job,
    get_success_data,
    make_employee_headers,
    rest_periods_for,
    set_clock,
    setup_accepted_assignment,
    setup_offered_call,
    setup_tied_up_assignment,
    validate_error,
    validate_success,
)

MANAGER = TEST_USERS["crew_manager_headers"]
CALLER = TEST_USERS["crew_caller_headers"]


def test_assignment_marked_up_cannot_tieup(api):
    """PRD §3.4: "The assignment lifecycle continues `MARKED_UP` to `ON_DUTY` to
    `TIE_UP_PENDING` to `COMPLETED`, with `LAID_OFF` and `RECREWED` as the two
    early terminal exits."
    PRD §2.9: "Sixth, state validity: the target entity must sit in a from-state
    listed for the requested transition — a call must be `OFFERED` to accept,
    decline, rescind, or record no-answer; an assignment must be `MARKED_UP` to
    go on duty or lay off; a job must be `BULLETINED` or `CALLING` to issue a
    call — rejected with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/assignment_marked_up_cannot_tieup
    """
    set_clock()
    ctx = setup_accepted_assignment()
    assert ctx["assignment"]["assignment_status"] == "MARKED_UP"
    resp = api_client.assignment_tie_up(
        ctx["assignment"]["id"], make_employee_headers(ctx["employee"]["id"])
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_assignment_layoff_reopens_seat_and_frees_employee(api):
    """PRD §3.4: "Laying off decrements `filled_count` by one — and if the job
    had been `FILLED`, falling below `crew_required` transitions it back from
    `FILLED` to `CALLING` — and returns the employee from `ON_ASSIGNMENT` to
    `AVAILABLE` through the mark-up path, with no rest period opening because
    duty never began."

    Design: Corner/state_machines/assignment_layoff_reopens_seat_and_frees_employee
    """
    set_clock()
    ctx = setup_accepted_assignment(report_time="2026-08-03T08:00:00Z")
    emp_id = ctx["employee"]["id"]
    job_id = ctx["job"]["id"]
    assert get_job(job_id)["job_status"] == "FILLED"

    resp = api_client.assignment_lay_off(
        ctx["assignment"]["id"], make_employee_headers(emp_id)
    )
    data = validate_success(resp)
    assert data["assignment_status"] == "LAID_OFF"

    job = get_job(job_id)
    assert job["job_status"] == "CALLING", "job must reopen to CALLING"
    assert job["filled_count"] == 0

    emp = get_employee(emp_id)
    assert emp["availability_status"] == "AVAILABLE"

    rests = rest_periods_for(emp_id)
    assert rests == [], f"no rest period may open when duty never started, got {rests}"


def test_assignment_layoff_at_report_time_rejected(api):
    """PRD §3.4: "An employee may also lay off a marked-up assignment, but only
    strictly before the job's `report_time`; at or after report time the attempt
    fails with `ERR_TEMPORAL_WINDOW`."

    Design: Corner/state_machines/assignment_layoff_at_report_time_rejected
    """
    set_clock()
    ctx = setup_accepted_assignment(report_time="2026-08-03T08:00:00Z")
    set_clock("2026-08-03T08:00:00Z")
    resp = api_client.assignment_lay_off(
        ctx["assignment"]["id"], make_employee_headers(ctx["employee"]["id"])
    )
    validate_error(resp, ApiErrorId.ERR_TEMPORAL_WINDOW)


def test_on_duty_too_early_rejected(api):
    """PRD §3.4: "Going on duty is allowed no earlier than 60 minutes before the
    job's `report_time`; an earlier attempt fails with `ERR_TEMPORAL_WINDOW`
    (HTTP 422)."
    PRD §2.6: "**Early report window.** An employee may go on duty no earlier
    than 60 minutes before the job's `report_time`."

    Design: Corner/endpoints/on_duty_too_early_rejected
    """
    set_clock()
    ctx = setup_accepted_assignment(report_time="2026-08-03T08:00:00Z")
    emp_id = ctx["employee"]["id"]
    asg_id = ctx["assignment"]["id"]

    set_clock("2026-08-03T06:59:00Z")  # 61 minutes early
    resp = api_client.assignment_on_duty(asg_id, make_employee_headers(emp_id))
    validate_error(resp, ApiErrorId.ERR_TEMPORAL_WINDOW)

    set_clock("2026-08-03T07:00:00Z")  # exactly 60 minutes early: allowed
    resp = api_client.assignment_on_duty(asg_id, make_employee_headers(emp_id))
    data = validate_success(resp)
    assert data["assignment_status"] == "ON_DUTY"


def test_tieup_opens_rest_and_moves_employee_on_rest(api):
    """PRD §3.4: "Tying up ends the tour: `off_duty_at` is stamped, the
    chronological ledger finalizes the tour's elapsed minutes into
    `cumulative_duty_minutes_month`, the employee moves from `ON_ASSIGNMENT` to
    `ON_REST` with a fresh rest period opening, and a pay record is auto-created
    in `DRAFT` for the employee and assignment with `claimed_minutes` preset to
    the elapsed tour minutes and `claimed_deadhead_minutes` preset from the
    assignment's `deadhead_minutes`."

    Design: Difficulty/transitive_cascade/tieup_cascades_rest_and_draft_payrecord
    """
    set_clock()
    ctx = setup_tied_up_assignment(tour_minutes=300,
                                   report_time="2026-08-02T06:00:00Z")
    emp_id = ctx["employee"]["id"]
    assert ctx["assignment"]["assignment_status"] == "TIE_UP_PENDING"

    emp = get_employee(emp_id)
    assert emp["availability_status"] == "ON_REST", (
        "link 1: tie-up must move the employee to ON_REST"
    )

    rests = rest_periods_for(emp_id)
    assert len(rests) == 1
    assert rests[0]["rest_status"] == "OPEN", (
        "link 2: a fresh OPEN rest period must open as a consequence"
    )


def test_tieup_autocreates_draft_payrecord_with_elapsed_minutes(api):
    """PRD §3.4: "Tying up ends the tour: `off_duty_at` is stamped, the
    chronological ledger finalizes the tour's elapsed minutes into
    `cumulative_duty_minutes_month`, the employee moves from `ON_ASSIGNMENT` to
    `ON_REST` with a fresh rest period opening, and a pay record is auto-created
    in `DRAFT` for the employee and assignment with `claimed_minutes` preset to
    the elapsed tour minutes and `claimed_deadhead_minutes` preset from the
    assignment's `deadhead_minutes`."

    Design: Difficulty/transitive_cascade/tieup_cascades_rest_and_draft_payrecord
    """
    set_clock()
    ctx = setup_tied_up_assignment(tour_minutes=300,
                                   report_time="2026-08-02T06:00:00Z")
    pay = ctx["pay_record"]
    assert pay["record_status"] == "DRAFT"
    assert pay["claimed_minutes"] == 300, (
        f"auto-claim must preset elapsed tour minutes 300, got {pay['claimed_minutes']}"
    )
    assert pay["employee_id"] == ctx["employee"]["id"]
    assert pay["assignment_id"] == ctx["assignment"]["id"]


def test_complete_blocked_while_pay_record_draft(api):
    """PRD §3.4: "Completion is the caller's closing act, permitted only when
    the assignment's auto-created pay record has been submitted or finalized;
    completing against a still-`DRAFT` pay record fails with
    `ERR_PAY_INCOMPLETE` (HTTP 422), and a successful completion decrements the
    job's `filled_count` by one."

    Design: Difficulty/cross_entity_state_dependency/assignment_complete_depends_on_payrecord_state
    """
    set_clock()
    ctx = setup_tied_up_assignment(tour_minutes=240,
                                   report_time="2026-08-02T06:00:00Z")
    assert ctx["pay_record"]["record_status"] == "DRAFT"
    resp = api_client.assignment_complete(ctx["assignment"]["id"], CALLER)
    validate_error(resp, ApiErrorId.ERR_PAY_INCOMPLETE)


def test_complete_allowed_after_pay_record_submitted(api):
    """PRD §3.4: "Completion is the caller's closing act, permitted only when
    the assignment's auto-created pay record has been submitted or finalized;
    completing against a still-`DRAFT` pay record fails with
    `ERR_PAY_INCOMPLETE` (HTTP 422), and a successful completion decrements the
    job's `filled_count` by one."

    Design: Difficulty/cross_entity_state_dependency/assignment_complete_depends_on_payrecord_state
    """
    set_clock()
    ctx = setup_tied_up_assignment(tour_minutes=240,
                                   report_time="2026-08-02T06:00:00Z")
    emp_id = ctx["employee"]["id"]
    job_id = ctx["job"]["id"]
    filled_before = get_job(job_id)["filled_count"]

    resp = api_client.submit_pay_record(
        ctx["pay_record"]["id"], make_employee_headers(emp_id)
    )
    validate_success(resp)

    resp = api_client.assignment_complete(ctx["assignment"]["id"], CALLER)
    data = validate_success(resp)
    assert data["assignment_status"] == "COMPLETED"
    assert get_job(job_id)["filled_count"] == filled_before - 1


def test_laid_off_assignment_contributes_zero_duty_minutes(api):
    """PRD §3.4: "Duty accumulation is a chronological ledger: it replays the
    employee's assignments in `ON_DUTY`, `TIE_UP_PENDING`, `COMPLETED`, or
    `RECREWED` status whose `on_duty_at` falls in the current calendar month —
    `LAID_OFF` rows contribute nothing — ordered by `on_duty_at` ascending with
    `created_at` ascending as the tie-break, summing each row's elapsed minutes
    (to `off_duty_at`, or to the current time for a tour still `ON_DUTY`)."

    Design: Corner/calculations/hos_input_set_excludes_laid_off_assignments
    """
    set_clock()
    ctx = setup_accepted_assignment(report_time="2026-08-03T08:00:00Z")
    emp_id = ctx["employee"]["id"]
    resp = api_client.assignment_lay_off(
        ctx["assignment"]["id"], make_employee_headers(emp_id)
    )
    validate_success(resp)

    emp = get_employee(emp_id)
    assert emp["cumulative_duty_minutes_month"] == 0, (
        f"LAID_OFF rows must contribute zero, got {emp['cumulative_duty_minutes_month']}"
    )
