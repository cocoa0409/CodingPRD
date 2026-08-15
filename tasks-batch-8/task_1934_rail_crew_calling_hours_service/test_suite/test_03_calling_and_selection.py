"""Callee selection, call expiry, response windows, and job fill state (PRD §3.3, §3.4)."""
from datetime import timedelta

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_call_with_fresh_version,
    api_client,
    create_job,
    get_employee,
    get_job,
    issue_call,
    make_employee_headers,
    set_clock,
    setup_board_with_employees,
    setup_offered_call,
    slot_for_employee,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import _parse

MANAGER = TEST_USERS["crew_manager_headers"]
CALLER = TEST_USERS["crew_caller_headers"]


def test_clock_default_is_fixed_startup_time(api):
    """PRD §2.5: "At server startup the logical clock reads exactly
    2026-08-01T00:00:00Z."
    PRD §3.3: "The created call links the job and the selected employee through
    `job_id` and `employee_id`, enters `OFFERED` status with `offered_at`
    stamped by the server, and computes `expires_at` as exactly 120 minutes
    after `offered_at`."

    Design: Corner/endpoints/clock_default_is_fixed_startup_time
    """
    # Deliberately no set_clock call: the startup default must hold.
    ctx = setup_offered_call()
    call = ctx["call"]
    offered = _parse(call["offered_at"])
    expires = _parse(call["expires_at"])
    assert offered == _parse("2026-08-01T00:00:00Z"), (
        f"offered_at must equal the fixed startup instant, got {call['offered_at']}"
    )
    assert expires - offered == timedelta(minutes=120), (
        "expires_at must be exactly 120 minutes after offered_at"
    )


def test_selector_skips_marked_off_and_empty_pool_opens_shortage(api):
    """PRD §3.3: "Callee selection filters the extra boards to find slots whose
    board's craft equals the job's `craft` and whose board's terminal equals the
    job's `origin_terminal`, where the slot is `ACTIVE`, the occupying employee
    is `AVAILABLE`, and the employee's `fatigue_score` is below the 80.0 block
    threshold — fatigue gating lives entirely here at selection time, never at
    acceptance."
    PRD §3.3: "when matching boards exist but the eligible pool is empty — every
    slot frozen or vacated, every occupant unavailable or fatigue-blocked — no
    call is created, the issue is rejected with `ERR_CALL_POOL_EXHAUSTED`
    (HTTP 422), and a crew shortage row is opened automatically with
    `shortage_status` `OPEN` and its `craft` taken from the job."

    Design: Corner/calculations/calling_selector_skips_unavailable_and_fatigue_blocked
    """
    set_clock()
    ctx = setup_board_with_employees(2)
    board_id = ctx["board"]["id"]
    e1, e2 = (e["id"] for e in ctx["employees"])
    # E1 marks off; its slot freezes, so it must be skipped.
    api_client.lay_off_employee(e1, make_employee_headers(e1))

    job = create_job()
    call = issue_call(job["id"])
    assert call["employee_id"] == e2, (
        f"first-out AVAILABLE employee E2 must be called, got {call['employee_id']}"
    )

    # E2 also marks off: both slots FROZEN, pool exhausted.
    api_client.lay_off_employee(e2, make_employee_headers(e2))
    job2 = create_job()
    resp = api_client.issue_call(job2["id"], CALLER)
    validate_error(resp, ApiErrorId.ERR_CALL_POOL_EXHAUSTED)

    resp = api_client.list_crew_shortages(MANAGER, params={"job_id": job2["id"]})
    shortages = validate_success(resp)
    assert shortages[0]["shortage_status"] == "OPEN"
    assert shortages[0]["craft"] == "CONDUCTOR"


def test_call_expiry_sweep_on_clock_advance(api):
    """PRD §2.5: "Advancing the clock fires the call-expiry sweep: every call
    still in `OFFERED` whose `expires_at` is at or before the new time
    transitions from `OFFERED` to `EXPIRED`."
    PRD §3.3: "Expiry fires from the clock sweep and penalizes identically."

    Design: Corner/state_machines/call_expiry_sweep_on_clock_advance
    """
    set_clock()
    ctx = setup_board_with_employees(2)
    board_id = ctx["board"]["id"]
    e1, e2 = (e["id"] for e in ctx["employees"])
    job = create_job(report_time="2026-08-04T08:00:00Z")
    call = issue_call(job["id"])
    assert call["employee_id"] == e1, "first-out position 1 must be called first"

    resp = api_client.set_clock({"to_iso8601": "2026-08-01T02:00:01Z"}, MANAGER)
    sweep = validate_success(resp)
    assert call["id"] in sweep["expired_call_ids"]

    resp = api_client.list_calls(CALLER, params={"job_id": job["id"]})
    calls = validate_success(resp)
    assert calls[0]["call_status"] == "EXPIRED"

    assert slot_for_employee(board_id, e1)["standing_position"] == 2, (
        "expiry penalty rotation must move the employee to the board tail"
    )
    assert slot_for_employee(board_id, e2)["standing_position"] == 1


def test_fk_reverse_reachability_job_calls(api):
    """PRD §3.3: "Calls can be listed per job or globally, filtered by
    `call_status` and, on the global listing, additionally by `job_id` and
    `employee_id`."

    Design: Corner/entities/fk_reverse_reachability_job_calls
    """
    set_clock()
    ctx = setup_offered_call()
    resp = api_client.list_job_calls(ctx["job"]["id"], CALLER)
    calls = validate_success(resp)
    assert len(calls) == 1
    assert calls[0]["id"] == ctx["call"]["id"]


def test_call_terminal_declined_cannot_be_rescinded(api):
    """PRD §2.9: "Sixth, state validity: the target entity must sit in a
    from-state listed for the requested transition — a call must be `OFFERED` to
    accept, decline, rescind, or record no-answer; an assignment must be
    `MARKED_UP` to go on duty or lay off; a job must be `BULLETINED` or
    `CALLING` to issue a call — rejected with `ERR_INVALID_STATE` (HTTP 409)."
    PRD §3.3: "A call's terminal states are `DECLINED`, `NO_ANSWER`, `EXPIRED`,
    and `RESCINDED`; `ACCEPTED` is the successful non-terminal outcome and the
    accepted call is retained as immutable history."

    Design: Corner/state_machines/call_terminal_declined_cannot_be_rescinded
    """
    set_clock()
    ctx = setup_offered_call()
    emp_id = ctx["employee"]["id"]
    resp = api_client.decline_call(ctx["call"]["id"], make_employee_headers(emp_id))
    declined = validate_success(resp)
    assert declined["call_status"] == "DECLINED"

    resp = api_client.rescind_call(ctx["call"]["id"], CALLER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_accept_side_effects_visible_immediately(api):
    """PRD §3.4: "A successful acceptance creates an assignment in `MARKED_UP`
    status carrying the `job_id`, the `employee_id`, and the `call_id` of the
    accepted call that produced it"
    PRD §3.4: "The job's `filled_count` increments by one — a mutation that also
    advances the job's `version` and refreshes `updated_at` — and when
    `filled_count` reaches `crew_required` the job transitions from `CALLING` to
    `FILLED`."
    PRD §3.4: "The employee moves from `AVAILABLE` to `ON_ASSIGNMENT`, the
    call's `responded_at` is stamped, and the employee's duty accumulation and
    fatigue score are recomputed."

    Design: Corner/consistency_model/accept_side_effects_visible_immediately
    """
    set_clock()
    ctx = setup_offered_call()
    emp_id = ctx["employee"]["id"]
    resp = accept_call_with_fresh_version(ctx["call"]["id"], emp_id)
    assignment = validate_success(resp, expected_status=201)
    assert assignment["assignment_status"] == "MARKED_UP"
    assert assignment["job_id"] == ctx["job"]["id"]
    assert assignment["employee_id"] == emp_id
    assert assignment["call_id"] == ctx["call"]["id"]

    job = get_job(ctx["job"]["id"])
    assert job["filled_count"] == 1
    assert job["job_status"] == "FILLED"

    emp = get_employee(emp_id)
    assert emp["availability_status"] == "ON_ASSIGNMENT"


def test_no_answer_rotation_drives_next_call_to_survivor(api):
    """PRD §3.3: "Among the eligible set the callee is chosen by
    `standing_position` ascending, first-out first; positions are unique per
    board, so no tie-break is ever needed."
    PRD §3.3: "A no-answer, recorded by the caller, applies the same penalty
    rotation to the unresponsive employee's slot."

    Design: Difficulty/cross_entity_state_dependency/call_accept_depends_on_job_fill_state
    """
    set_clock()
    ctx = setup_board_with_employees(2)
    e1, e2 = (e["id"] for e in ctx["employees"])
    job = create_job(report_time="2026-08-03T08:00:00Z", crew_required=1)
    call1 = issue_call(job["id"])
    assert call1["employee_id"] == e1

    resp = api_client.no_answer_call(call1["id"], CALLER)
    validate_success(resp)
    call2 = issue_call(job["id"])
    assert call2["employee_id"] == e2, (
        "after the no-answer penalty rotation the next call must go to E2"
    )

    resp = accept_call_with_fresh_version(call2["id"], e2)
    assignment = validate_success(resp, expected_status=201)
    assert assignment["assignment_status"] == "MARKED_UP"
    job_after = get_job(job["id"])
    assert job_after["job_status"] == "FILLED", (
        "E2's accept against the single-seat job must drive it to FILLED"
    )
    assert job_after["filled_count"] == 1


def test_selector_skips_on_assignment_employee_for_next_job(api):
    """PRD §3.3: "Callee selection filters the extra boards to find slots whose
    board's craft equals the job's `craft` and whose board's terminal equals the
    job's `origin_terminal`, where the slot is `ACTIVE`, the occupying employee
    is `AVAILABLE`, and the employee's `fatigue_score` is below the 80.0 block
    threshold — fatigue gating lives entirely here at selection time, never at
    acceptance."

    Design: Difficulty/cross_entity_state_dependency/call_accept_depends_on_job_fill_state
    """
    set_clock()
    ctx = setup_board_with_employees(2)
    e1, e2 = (e["id"] for e in ctx["employees"])
    job = create_job(report_time="2026-08-03T08:00:00Z", crew_required=1)
    call1 = issue_call(job["id"])
    api_client.no_answer_call(call1["id"], CALLER)
    call2 = issue_call(job["id"])
    resp = accept_call_with_fresh_version(call2["id"], e2)
    validate_success(resp, expected_status=201)

    # E2 is now ON_ASSIGNMENT (not AVAILABLE); E1 sits at the tail but is the
    # only AVAILABLE ACTIVE slot and must be selected for a fresh job.
    job2 = create_job(report_time="2026-08-04T08:00:00Z", crew_required=1)
    call3 = issue_call(job2["id"])
    assert call3["employee_id"] == e1, (
        f"E2 is ON_ASSIGNMENT and ineligible; E1 must be called, got {call3['employee_id']}"
    )


def test_two_accepts_fill_two_seat_job(api):
    """PRD §3.4: "The job's `filled_count` increments by one — a mutation that
    also advances the job's `version` and refreshes `updated_at` — and when
    `filled_count` reaches `crew_required` the job transitions from `CALLING` to
    `FILLED`."

    Design: Difficulty/resource_temporal_overlap/job_seat_capacity_aggregate_not_interval
    """
    set_clock()
    ctx = setup_board_with_employees(3)
    e1, e2, _ = (e["id"] for e in ctx["employees"])
    job = create_job(report_time="2026-08-03T08:00:00Z", crew_required=2)

    call1 = issue_call(job["id"])
    assert call1["employee_id"] == e1
    resp = accept_call_with_fresh_version(call1["id"], e1)
    validate_success(resp, expected_status=201)
    assert get_job(job["id"])["filled_count"] == 1
    assert get_job(job["id"])["job_status"] == "CALLING"

    call2 = issue_call(job["id"])
    assert call2["employee_id"] == e2
    resp = accept_call_with_fresh_version(call2["id"], e2)
    validate_success(resp, expected_status=201)
    job_after = get_job(job["id"])
    assert job_after["filled_count"] == 2
    assert job_after["job_status"] == "FILLED", "aggregate capacity reached"


def test_issue_call_on_filled_job_rejected_invalid_state(api):
    """PRD §2.9: "Sixth, state validity: the target entity must sit in a
    from-state listed for the requested transition — a call must be `OFFERED` to
    accept, decline, rescind, or record no-answer; an assignment must be
    `MARKED_UP` to go on duty or lay off; a job must be `BULLETINED` or
    `CALLING` to issue a call — rejected with `ERR_INVALID_STATE` (HTTP 409)."
    PRD §3.3: "The job must be `BULLETINED` or `CALLING`; issuing moves it to
    `CALLING`."

    Design: Difficulty/resource_temporal_overlap/job_seat_capacity_aggregate_not_interval
    """
    set_clock()
    ctx = setup_board_with_employees(3)
    e1, e2, _ = (e["id"] for e in ctx["employees"])
    job = create_job(report_time="2026-08-03T08:00:00Z", crew_required=2)
    for emp_id in (e1, e2):
        call = issue_call(job["id"])
        resp = accept_call_with_fresh_version(call["id"], emp_id)
        validate_success(resp, expected_status=201)
    assert get_job(job["id"])["job_status"] == "FILLED"

    resp = api_client.issue_call(job["id"], CALLER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
