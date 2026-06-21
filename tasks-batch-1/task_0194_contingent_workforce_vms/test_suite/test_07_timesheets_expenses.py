"""Timesheets and expenses: submit preconditions, empty/duplicate-week guards,
auto-approval, the rework loop, and the offboard open-approvals block
(§3.8, §3.9, §3.6).
"""
import pytest
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    get_success_data, make_supplier_headers, TEST_USERS,
    create_program, create_supplier, create_worker, create_requisition,
    distribute, create_submittal, set_clock, advance_clock,
    setup_active_assignment, setup_active_assignment_with_draft_timesheet,
    setup_submitted_timesheet,
)
from test_helpers import factories as F

PM = TEST_USERS["program_manager_headers"]
HM = TEST_USERS["hiring_manager_headers"]


# ===========================================================================
# Queue A: cross_entity_state_dependency / timesheet_submit_requires_assignment_active
# ===========================================================================

def test_timesheet_submit_fails_when_assignment_on_hold(api):
    """PRD §3.8: "Submitting a timesheet moves it from `DRAFT` to `SUBMITTED`,
    and is allowed only while the parent assignment's `engagement_status` is
    `ACTIVE`; submitting against a non-active assignment is rejected with
    `ERR_ASSIGNMENT_NOT_ACTIVE`."
    PRD §3.6: "Placing an assignment on hold moves `engagement_status` from
    `ACTIVE` to `ON_HOLD`"

    Design: Difficulty/cross_entity_state_dependency/timesheet_submit_requires_assignment_active
    """
    base = setup_active_assignment_with_draft_timesheet(
        program_overrides={"coemployment_tenure_limit_days": 3650,
                           "tenure_warning_threshold_days": 3000})
    get_success_data(api.hold_assignment(base["assignment"]["id"], PM))
    validate_error(api.submit_timesheet(base["timesheet"]["id"], base["supplier_headers"]),
                   ApiErrorId.ERR_ASSIGNMENT_NOT_ACTIVE.value)


def test_timesheet_submit_succeeds_while_assignment_active(api):
    """PRD §3.8: "Submitting a timesheet moves it from `DRAFT` to `SUBMITTED`,
    and is allowed only while the parent assignment's `engagement_status` is
    `ACTIVE`"
    PRD §3.8: "On submit the system stamps `submitted_at` with the current
    program clock time."

    Design: Difficulty/cross_entity_state_dependency/timesheet_submit_requires_assignment_active
    """
    base = setup_active_assignment_with_draft_timesheet(
        program_overrides={"coemployment_tenure_limit_days": 3650,
                           "tenure_warning_threshold_days": 3000})
    data = validate_success(api.submit_timesheet(base["timesheet"]["id"], base["supplier_headers"]))
    assert data["status"] == "SUBMITTED", f"got {data['status']}"


# ===========================================================================
# Queue A: boundary_precision_check / empty_timesheet_zero_hours_rejected_on_submit
# ===========================================================================

def test_empty_timesheet_zero_hours_rejected_on_submit(api):
    """PRD §3.8: "The timesheet must also report some work — the sum of
    `regular_hours` and `overtime_hours` must be greater than 0, or the submit is
    rejected with `ERR_EMPTY_TIMESHEET`."

    regular 0 + overtime 0 == 0 -> ERR_EMPTY_TIMESHEET.

    Design: Difficulty/boundary_precision_check/empty_timesheet_zero_hours_rejected_on_submit
    """
    base = setup_active_assignment_with_draft_timesheet(
        timesheet_overrides={"regular_hours": 0, "overtime_hours": 0},
        program_overrides={"coemployment_tenure_limit_days": 3650,
                           "tenure_warning_threshold_days": 3000})
    validate_error(api.submit_timesheet(base["timesheet"]["id"], base["supplier_headers"]),
                   ApiErrorId.ERR_EMPTY_TIMESHEET.value)


def test_nonzero_hours_timesheet_submits(api):
    """PRD §3.8: "The timesheet must also report some work — the sum of
    `regular_hours` and `overtime_hours` must be greater than 0, or the submit is
    rejected with `ERR_EMPTY_TIMESHEET`."

    A positive total (regular 1) passes the empty-timesheet guard.

    Design: Difficulty/boundary_precision_check/empty_timesheet_zero_hours_rejected_on_submit
    """
    base = setup_active_assignment_with_draft_timesheet(
        timesheet_overrides={"regular_hours": 1, "overtime_hours": 0},
        program_overrides={"coemployment_tenure_limit_days": 3650,
                           "tenure_warning_threshold_days": 3000})
    data = validate_success(api.submit_timesheet(base["timesheet"]["id"], base["supplier_headers"]))
    assert data["status"] == "SUBMITTED"


# ===========================================================================
# Queue A: resource_temporal_overlap / timesheet_week_bucket_exact_match_collision
# ===========================================================================

def test_duplicate_week_start_date_rejected(api):
    """PRD §3.8: "Each assignment may hold only one timesheet per weekly bucket:
    if another timesheet on the same assignment already occupies the exact same
    `week_start_date`, the new one is rejected with `ERR_DUPLICATE_WEEK`."

    A second timesheet on the same week_start_date 2026-01-05 collides.

    Design: Difficulty/resource_temporal_overlap/timesheet_week_bucket_exact_match_collision
    """
    base = setup_active_assignment(
        program_overrides={"coemployment_tenure_limit_days": 3650,
                           "tenure_warning_threshold_days": 3000},
        planned_end_date="2026-12-01T00:00:00.000Z")
    sh = base["supplier_headers"]
    asg_id = base["assignment"]["id"]
    get_success_data(api.create_timesheet(
        F.create_timesheet_payload(asg_id, "2026-01-05T00:00:00.000Z", regular_hours=40), sh))
    validate_error(api.create_timesheet(
        F.create_timesheet_payload(asg_id, "2026-01-05T00:00:00.000Z", regular_hours=10), sh),
        ApiErrorId.ERR_DUPLICATE_WEEK.value)


def test_adjacent_week_does_not_collide(api):
    """PRD §3.8: "The collision is an exact match on the week bucket — adjacent
    weeks do not collide, only an identical `week_start_date` does."

    The adjacent week 2026-01-12 (start + 7 days) is accepted alongside 2026-01-05.

    Design: Difficulty/resource_temporal_overlap/timesheet_week_bucket_exact_match_collision
    """
    base = setup_active_assignment(
        program_overrides={"coemployment_tenure_limit_days": 3650,
                           "tenure_warning_threshold_days": 3000},
        planned_end_date="2026-12-01T00:00:00.000Z")
    sh = base["supplier_headers"]
    asg_id = base["assignment"]["id"]
    get_success_data(api.create_timesheet(
        F.create_timesheet_payload(asg_id, "2026-01-05T00:00:00.000Z", regular_hours=40), sh))
    data = validate_success(api.create_timesheet(
        F.create_timesheet_payload(asg_id, "2026-01-12T00:00:00.000Z", regular_hours=40), sh),
        expected_status=201)
    assert data["status"] == "DRAFT"


# ===========================================================================
# Queue B: validations / offboard_with_pending_approval_rejected
# ===========================================================================

def test_offboard_blocked_by_pending_timesheet_approval(api):
    """PRD §3.6: "Offboarding ends the engagement ... it is blocked while any
    timesheet or expense on the assignment is still in `SUBMITTED` (awaiting
    approval), in which case it is rejected with `ERR_OPEN_APPROVALS_PENDING`."

    Design: Corner/validations/offboard_with_pending_approval_rejected
    """
    base = setup_submitted_timesheet(
        program_overrides={"coemployment_tenure_limit_days": 3650,
                           "tenure_warning_threshold_days": 3000})
    validate_error(api.offboard_assignment(base["assignment"]["id"], PM),
                   ApiErrorId.ERR_OPEN_APPROVALS_PENDING.value)


# ===========================================================================
# Queue B: calculations / timesheet_auto_approve_at_clock_advance
# ===========================================================================

def test_timesheet_auto_approves_after_window_elapses(api):
    """PRD §3.8: "the system auto-approves it on a clock advance once the
    approval window has elapsed — that is, once the clock reaches at or beyond
    `submitted_at` plus the program's `timesheet_approval_window_days`."
    PRD §3.8: "the regular pay component is `regular_hours` times the
    assignment's `pay_rate_cents`, rounded half-up to whole cents ... and
    `pay_amount_cents` is the sum of those two rounded components."

    Submitted at clock 2026-01-10 with window 7; advance to 2026-01-17 auto-
    approves; pay = 40*8000 = 320000, bill = 40*11600 = 464000.

    Design: Corner/calculations/timesheet_auto_approve_at_clock_advance
    """
    program = create_program(coemployment_tenure_limit_days=3650,
                             tenure_warning_threshold_days=3000,
                             timesheet_approval_window_days=7)
    set_clock(program["id"], "2026-01-10T00:00:00.000Z")
    supplier = create_supplier(program["id"])
    worker = create_worker(program["id"])
    sh = make_supplier_headers(supplier["id"])
    req = create_requisition(program["id"])
    distribute(req["id"], [supplier["id"]])
    sub = create_submittal(req["id"], supplier["id"], worker["id"], pay_rate_cents=8000)
    get_success_data(api.shortlist_submittal(sub["id"], HM))
    get_success_data(api.start_interview(sub["id"], HM))
    get_success_data(api.propose_rate(sub["id"], {"pay_rate_cents": 8000}, sh))
    get_success_data(api.offer_submittal(sub["id"], HM))
    req_now = get_success_data(api.get_requisition(req["id"], PM))
    get_success_data(api.hire_submittal(sub["id"], F.hire_payload(
        req_now["version"], "2026-01-01T00:00:00.000Z", "2026-12-01T00:00:00.000Z"), PM))
    asg = get_success_data(api.list_assignments(PM, params={"worker_profile_id": worker["id"]}))[0]
    ts = get_success_data(api.create_timesheet(
        F.create_timesheet_payload(asg["id"], "2026-01-05T00:00:00.000Z", regular_hours=40), sh))
    get_success_data(api.submit_timesheet(ts["id"], sh))
    advance_clock(program["id"], "2026-01-17T00:00:00.000Z")
    data = get_success_data(api.get_timesheet(ts["id"], PM))
    assert data["status"] == "APPROVED", f"got {data['status']}"
    assert data["pay_amount_cents"] == 320000, f"got {data['pay_amount_cents']}"
    assert data["bill_amount_cents"] == 464000, f"got {data['bill_amount_cents']}"


# ===========================================================================
# Queue B: state_machines / timesheet_reject_then_reopen_returns_to_draft
# ===========================================================================

def test_timesheet_reject_then_reopen_returns_to_draft_clears_submitted_at(api):
    """PRD §3.8: "A `HiringManager` may instead reject a `SUBMITTED` timesheet,
    moving it to `REJECTED`. From `REJECTED`, the `Supplier` may reopen it, which
    returns it to `DRAFT` for correction and clears `submitted_at`."

    Design: Corner/state_machines/timesheet_reject_then_reopen_returns_to_draft
    """
    base = setup_submitted_timesheet(
        program_overrides={"coemployment_tenure_limit_days": 3650,
                           "tenure_warning_threshold_days": 3000})
    sh = base["supplier_headers"]
    get_success_data(api.reject_timesheet(base["timesheet"]["id"], HM))
    data = validate_success(api.reopen_timesheet(base["timesheet"]["id"], sh))
    assert data["status"] == "DRAFT", f"got {data['status']}"
    assert data["submitted_at"] is None, f"got {data['submitted_at']!r}"
