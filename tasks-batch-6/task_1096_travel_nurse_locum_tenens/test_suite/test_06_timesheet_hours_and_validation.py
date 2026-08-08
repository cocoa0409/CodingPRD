"""Weekly hour classification, timesheet-creation guards, dispute/resubmit, and the
state-over-temporal validation-priority conflict."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS, make_clinician_headers, make_facility_manager_headers,
    create_timesheet_payload,
)
from test_helpers.fixtures import (
    setup_active_assignment, provision, submit_timesheet, approve_timesheet,
    statement_for_timesheet, get_assignment_data,
)

RECRUITER = TEST_USERS["recruiter_headers"]


def test_hour_classification_daily_overtime_beats_weekly(api):
    """PRD §3.6: "Daily overtime is the sum, across the seven days, of each day's hours
    above twelve ... Weekly overtime is the amount by which total_raw_hours exceeds forty
    ... The overtime_hours is the larger of the daily-overtime total and the
    weekly-overtime figure — not their sum; the rule that yields more wins. The
    regular_hours is total_raw_hours minus overtime_hours. The days_worked is the count
    of daily_hours entries strictly greater than 0."

    Design: Difficulty/combinatorial_formula/weekly_pay_cost_rounds_per_line_before_summation_mode_b
    """
    ctx = setup_active_assignment(api, clock="2026-06-14", assignment_overrides={"base_pay_rate_cents_per_hour": 3333})
    ts = submit_timesheet(api, ctx.asg_id, "2026-06-07", [0, 13, 12, 12, 0.5, 0, 0], ctx.clin_id)
    assert ts["total_raw_hours"] == 37.5
    assert ts["overtime_hours"] == 1.0
    assert ts["regular_hours"] == 36.5
    assert ts["days_worked"] == 4


def test_overtime_takes_larger_of_daily_and_weekly_rules(api):
    """PRD §3.6: "The overtime_hours is the larger of the daily-overtime total and the
    weekly-overtime figure — not their sum; the rule that yields more wins."
    PRD §3.6: "guaranteed_hours_consumed increases by the smaller of the week's worked
    hours (regular_hours plus overtime_hours) or the contract's weekly_guaranteed_hours"

    Design: Corner/calculations/corner_overtime_takes_the_larger_of_daily_and_weekly_rules
    """
    ctx = setup_active_assignment(api, clock="2026-06-14")
    ts = submit_timesheet(api, ctx.asg_id, "2026-06-07", [0, 13, 11, 11, 9, 0, 0], ctx.clin_id)
    assert ts["total_raw_hours"] == 44.0 and ts["overtime_hours"] == 4.0
    assert ts["regular_hours"] == 40.0 and ts["days_worked"] == 4
    approve_timesheet(api, ts["id"], ctx.fac_id)
    st = statement_for_timesheet(api, ts["id"])
    assert st["taxable_wages_cents"] == 239200
    assert st["burden_cents"] == 44252 and st["total_pay_cost_cents"] == 443752
    assert st["gross_bill_cents"] == 644000 and st["gross_margin_cents"] == 200248
    assert st["margin_pct"] == 0.3109 and st["margin_uplift_applied"] is False
    asg = get_assignment_data(api, ctx.asg_id)
    assert asg["guaranteed_hours_consumed"] == 36 and asg["guaranteed_hours_remaining"] == 432


def test_timesheet_create_rejected_on_duplicate_week_hours_cap_and_term_window(api):
    """PRD §3.6: "No other timesheet of the same assignment whose status is SUBMITTED,
    APPROVED, or DISPUTED may already cover that half-open week window — equivalently,
    none may share the identical week_start_date — else ERR_DUPLICATE_TIMESHEET_WEEK.
    Finally, every entry of daily_hours must be at most 24 and their sum at most 84, else
    ERR_HOURS_LIMIT_EXCEEDED."
    PRD §3.6: "week_start_date must be on or after the assignment's start_date, the week's
    last day ... must be on or before the assignment's end_date, and week_start_date must
    be on or before the logical clock's calendar date; a violation yields ERR_WEEK_OUTSIDE_TERM."

    Design: Corner/validations/corner_timesheet_create_rejections_duplicate_week_hours_cap_and_term_window
    """
    ctx = setup_active_assignment(api, clock="2026-06-21")
    clin = make_clinician_headers(ctx.clin_id)
    ok = validate_success(api.create_timesheet(
        create_timesheet_payload(ctx.asg_id, "2026-06-07", [0, 12, 12, 12, 0, 0, 0]), clin), 201)
    assert ok["status"] == "SUBMITTED" and ok["total_raw_hours"] == 36.0
    validate_error(api.create_timesheet(
        create_timesheet_payload(ctx.asg_id, "2026-06-07", [0, 8, 8, 8, 0, 0, 0]), clin),
        ApiErrorId.ERR_DUPLICATE_TIMESHEET_WEEK.value)
    validate_error(api.create_timesheet(
        create_timesheet_payload(ctx.asg_id, "2026-06-14", [0, 24, 24, 24, 18, 0, 0]), clin),
        ApiErrorId.ERR_HOURS_LIMIT_EXCEEDED.value)
    validate_error(api.create_timesheet(
        create_timesheet_payload(ctx.asg_id, "2026-05-31", [0, 12, 12, 12, 0, 0, 0]), clin),
        ApiErrorId.ERR_WEEK_OUTSIDE_TERM.value)
    data, meta = validate_paginated(api.list_assignment_timesheets(ctx.asg_id, RECRUITER))
    assert len(data) == 1 and meta["total_count"] == 1


def test_timesheet_dispute_then_resubmit_recomputes_hours(api):
    """PRD §3.6: "A FacilityManager may instead dispute a SUBMITTED week, moving it to
    DISPUTED and recording the dispute_reason. The owning Clinician then resubmits it back
    to SUBMITTED, optionally supplying replacement daily_hours and callback_hours; on
    resubmission the hour classification is recomputed from the replacement hours, the same
    hour limits are re-checked (else ERR_HOURS_LIMIT_EXCEEDED), and the dispute_reason is
    cleared."

    Design: Corner/state_machines/corner_timesheet_dispute_then_resubmit_recomputes_classified_hours
    """
    ctx = setup_active_assignment(api, clock="2026-06-14")
    ts = submit_timesheet(api, ctx.asg_id, "2026-06-07", [0, 12, 12, 12, 0, 0, 0], ctx.clin_id)
    fm = make_facility_manager_headers(ctx.fac_id)
    disputed = validate_success(api.transition_timesheet(
        ts["id"], {"to": "DISPUTED", "dispute_reason": "Thursday shift was 10 hours, not 12"}, fm), 200)
    assert disputed["status"] == "DISPUTED" and disputed["dispute_reason"] == "Thursday shift was 10 hours, not 12"
    resub = validate_success(api.transition_timesheet(
        ts["id"], {"to": "SUBMITTED", "daily_hours": [0, 10, 10, 10, 0, 0, 0], "callback_hours": 0},
        make_clinician_headers(ctx.clin_id)), 200)
    assert resub["status"] == "SUBMITTED"
    assert resub["total_raw_hours"] == 30.0 and resub["regular_hours"] == 30.0
    assert resub["overtime_hours"] == 0 and resub["days_worked"] == 3
    assert resub["dispute_reason"] is None
    approve_timesheet(api, ts["id"], ctx.fac_id)
    st = statement_for_timesheet(api, ts["id"])
    assert st["stipend_variant"] == "DAILY_PRORATED" and st["non_taxable_stipend_cents"] == 68700
    assert st["taxable_wages_cents"] == 156000 and st["burden_cents"] == 28860
    assert st["total_pay_cost_cents"] == 253560 and st["gross_bill_cents"] == 420000
    assert st["gross_margin_cents"] == 166440 and st["margin_pct"] == 0.3963
    asg = get_assignment_data(api, ctx.asg_id)
    assert asg["guaranteed_hours_consumed"] == 30 and asg["guaranteed_hours_remaining"] == 438


# --- Difficulty: state priority (7) beats temporal priority (14) on timesheet create ---
def test_state_error_beats_temporal_error_on_timesheet_create(api):
    """PRD §2.8: "7. State admissibility ... else ERR_INVALID_TRANSITION,
    ERR_ASSIGNMENT_NOT_ACTIVE, or ERR_STATEMENT_ALREADY_POSTED." precedes
    "14. Timesheet week-window (temporal), else ERR_WEEK_OUTSIDE_TERM."
    PRD §3.6: "A timesheet may only be filed while the parent assignment's staffing_status
    is ACTIVE (else ERR_ASSIGNMENT_NOT_ACTIVE)"

    Design: Difficulty/priority_pair_validation_conflict/state_priority_beats_temporal_priority_on_timesheet_create
    """
    ctx = provision(api, contract_stage="executed")  # PENDING_START (never activated); clock at default 2026-05-01
    resp = api.create_timesheet(
        create_timesheet_payload(ctx.asg_id, "2026-05-31", [0, 12, 12, 12, 0, 0, 0]),
        make_clinician_headers(ctx.clin_id))
    validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_NOT_ACTIVE.value)


def test_no_timesheet_created_when_assignment_not_active(api):
    """PRD §3.6: "A timesheet may only be filed while the parent assignment's
    staffing_status is ACTIVE (else ERR_ASSIGNMENT_NOT_ACTIVE)" — the rejected filing
    persists no Timesheet row.

    Design: Difficulty/priority_pair_validation_conflict/state_priority_beats_temporal_priority_on_timesheet_create
    """
    ctx = provision(api, contract_stage="executed")
    api.create_timesheet(
        create_timesheet_payload(ctx.asg_id, "2026-05-31", [0, 12, 12, 12, 0, 0, 0]),
        make_clinician_headers(ctx.clin_id))
    data, meta = validate_paginated(api.list_assignment_timesheets(ctx.asg_id, RECRUITER))
    assert data == [] and meta["total_count"] == 0
