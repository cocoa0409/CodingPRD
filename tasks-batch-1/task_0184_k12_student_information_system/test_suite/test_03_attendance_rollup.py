"""Period attendance, the daily rollup, attendance windows, and present-day counts.

Covers difficulty instances under combinatorial_formula and
resource_temporal_overlap (attendance window), plus corner instances under
state_machines/validations/consistency_model.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    fixtures as fx,
)

REG = TEST_USERS["registrar_headers"]
TEACH = TEST_USERS["teacher_headers"]


def _daily_row(api, enrollment_id, day_index):
    resp = api.list_daily_attendance(enrollment_id, REG, params={"day_index": day_index})
    data, _ = validate_paginated(resp)
    assert data, f"expected a daily-attendance row for day {day_index}"
    return data[0]


# ---------------------------------------------------------------------------
# combinatorial_formula / daily_rollup_present_partial_absent_branching
# ---------------------------------------------------------------------------
def test_daily_rollup_partial_when_present_below_expected(api):
    """PRD §3.5: "if present_minutes_total is at least the expected minutes and the
    expected minutes are greater than 0 the day is PRESENT; in every remaining case
    the day is PARTIAL."

    Design: Difficulty/combinatorial_formula/daily_rollup_present_partial_absent_branching
    """
    ctx = fx.setup_seated_student(
        ada_method="AGGREGATE_MEMBERSHIP", minimum_daily_minutes=240, clock_days=1,
        meeting_minutes=50, period=1)
    sa1 = ctx["assignment"]["id"]
    # second 50-min section in period 2 for the same enrollment
    sec2 = fx.create_section(ctx["course"]["id"], period=2, meeting_minutes=50)
    sa2 = fx.seat(ctx["enrollment"]["id"], sec2["id"])
    fx.post_attendance(sa1, 1, "PRESENT")
    fx.post_attendance(sa2["id"], 1, "ABSENT_UNEXCUSED")
    row = _daily_row(api, ctx["enrollment"]["id"], 1)
    assert row["present_minutes_total"] == 50, f"present_minutes_total expected 50, got {row['present_minutes_total']}"
    assert row["daily_code"] == "PARTIAL", f"daily_code expected PARTIAL, got {row['daily_code']}"


def test_daily_rollup_partial_is_ada_eligible_under_aggregate_membership(api):
    """PRD §3.6: "Under a school whose ada_method is AGGREGATE_MEMBERSHIP, a day is
    eligible whenever its daily_code is anything other than ABSENT — any partial
    presence counts, and the minute floor is ignored."

    Design: Difficulty/combinatorial_formula/daily_rollup_present_partial_absent_branching
    """
    ctx = fx.setup_seated_student(
        ada_method="AGGREGATE_MEMBERSHIP", minimum_daily_minutes=240, clock_days=1,
        meeting_minutes=50, period=1)
    sa1 = ctx["assignment"]["id"]
    sec2 = fx.create_section(ctx["course"]["id"], period=2, meeting_minutes=50)
    sa2 = fx.seat(ctx["enrollment"]["id"], sec2["id"])
    fx.post_attendance(sa1, 1, "PRESENT")
    fx.post_attendance(sa2["id"], 1, "ABSENT_UNEXCUSED")
    row = _daily_row(api, ctx["enrollment"]["id"], 1)
    assert row["daily_code"] == "PARTIAL"
    assert row["ada_eligible"] is True, "PARTIAL day is ADA-eligible under AGGREGATE_MEMBERSHIP"


# ---------------------------------------------------------------------------
# boundary_precision_check / days_present_minute_floor_boundary
# ---------------------------------------------------------------------------
def test_days_present_floor_at_240_is_eligible(api):
    """PRD §3.6: "The boundary is inclusive on the floor: with a minimum_daily_minutes
    of 240, a present_minutes_total of exactly 240 is eligible while 239 is not."

    Design: Difficulty/boundary_precision_check/days_present_minute_floor_boundary
    """
    ctx = fx.setup_seated_student(
        ada_method="DAYS_PRESENT", minimum_daily_minutes=240, session_total_days=180,
        clock_days=1, meeting_minutes=240, period=2)
    fx.post_attendance(ctx["assignment"]["id"], 1, "PRESENT")
    row = _daily_row(api, ctx["enrollment"]["id"], 1)
    assert row["ada_eligible"] is True, "240 >= 240 is ADA-eligible under DAYS_PRESENT"
    enr = validate_success(api.get_enrollment(ctx["enrollment"]["id"], REG))
    assert enr["present_days"] == 1, f"present_days expected 1, got {enr['present_days']}"


def test_days_present_floor_below_240_not_eligible(api):
    """PRD §3.6: "Under DAYS_PRESENT, a day is eligible only when its
    present_minutes_total is at least the school's minimum_daily_minutes; a PARTIAL
    day that falls below that floor is not eligible."

    Design: Difficulty/boundary_precision_check/days_present_minute_floor_boundary
    """
    ctx = fx.setup_seated_student(
        ada_method="DAYS_PRESENT", minimum_daily_minutes=240, session_total_days=180,
        clock_days=1, meeting_minutes=230, period=1)
    fx.post_attendance(ctx["assignment"]["id"], 1, "PRESENT")
    row = _daily_row(api, ctx["enrollment"]["id"], 1)
    assert row["ada_eligible"] is False, "230 < 240 is NOT ADA-eligible under DAYS_PRESENT"
    enr = validate_success(api.get_enrollment(ctx["enrollment"]["id"], REG))
    assert enr["present_days"] == 0, f"present_days expected 0, got {enr['present_days']}"


# ---------------------------------------------------------------------------
# resource_temporal_overlap / attendance_half_open_membership_window_overlap
# ---------------------------------------------------------------------------
def test_attendance_on_exclusive_exit_day_rejected(api):
    """PRD §3.5: "The posted day_index must fall inside the enrollment's active
    window — at least the entry_day_index, at most the school's
    current_school_day_index, and strictly below exit_day_index when the enrollment
    is WITHDRAWN — or the post is rejected with ERR_ATTENDANCE_OUTSIDE_WINDOW."

    Design: Difficulty/resource_temporal_overlap/attendance_half_open_membership_window_overlap
    """
    ctx = fx.setup_seated_student(clock_days=3, meeting_minutes=50, entry_day_index=1)
    sa = ctx["assignment"]["id"]
    fx.post_attendance(sa, 1, "ABSENT_EXCUSED")
    validate_success(api.withdraw_enrollment(ctx["enrollment"]["id"], {"exit_day_index": 3}, REG))
    # window is [1,3); day 3 hits the exclusive upper edge.
    resp = api.create_attendance_record(
        {"schedule_assignment_id": sa, "day_index": 3, "code": "PRESENT"}, REG)
    validate_error(resp, ApiErrorId.ERR_ATTENDANCE_OUTSIDE_WINDOW.value, expected_status=422)


def test_correction_inside_half_open_window_succeeds(api):
    """PRD §3.5: "the same active-window rule applies, again surfacing
    ERR_ATTENDANCE_OUTSIDE_WINDOW when the underlying day falls outside the
    enrollment's window."
    PRD §3.5: "The posted day_index must fall inside the enrollment's active window —
    at least the entry_day_index, at most the school's current_school_day_index, and
    strictly below exit_day_index when the enrollment is WITHDRAWN".

    The lower boundary point of the half-open window [1,3): day 2 is strictly below
    the exclusive exit edge 3, so correcting a day-2 record after withdrawal is
    inside the window and is accepted — the complement of the day-3 rejection.

    Design: Difficulty/resource_temporal_overlap/attendance_half_open_membership_window_overlap
    """
    ctx = fx.setup_seated_student(clock_days=3, meeting_minutes=50, entry_day_index=1)
    sa = ctx["assignment"]["id"]
    rec = fx.post_attendance(sa, 2, "ABSENT_UNEXCUSED")
    validate_success(api.withdraw_enrollment(ctx["enrollment"]["id"], {"exit_day_index": 3}, REG))
    corrected = validate_success(
        api.correct_attendance_record(rec["id"], {"code": "TARDY"}, REG),
        expected_status=201)
    assert corrected["code"] == "TARDY"
    assert corrected["day_index"] == 2, "correction lands on day 2, inside [1,3)"


def test_attendance_before_entry_day_rejected(api):
    """PRD §3.5: "The posted day_index must fall inside the enrollment's active
    window — at least the entry_day_index, at most the school's
    current_school_day_index, and strictly below exit_day_index when the enrollment
    is WITHDRAWN — or the post is rejected with ERR_ATTENDANCE_OUTSIDE_WINDOW."

    Design: Corner/validations/attendance_before_entry_day_rejected
    """
    ctx = fx.setup_seated_student(clock_days=3, meeting_minutes=50, entry_day_index=2)
    resp = api.create_attendance_record(
        {"schedule_assignment_id": ctx["assignment"]["id"], "day_index": 1, "code": "PRESENT"}, TEACH)
    validate_error(resp, ApiErrorId.ERR_ATTENDANCE_OUTSIDE_WINDOW.value, expected_status=422)


# ---------------------------------------------------------------------------
# corner: attendance_correction_supersedes_prior
# ---------------------------------------------------------------------------
def test_attendance_correction_supersedes_prior_and_raises_present_days(api):
    """PRD §3.5: "A teacher or registrar may correct an existing record by supplying
    a replacement code. The prior record's status becomes SUPERSEDED, a fresh
    RECORDED record is created with the new code".

    Design: Corner/state_machines/attendance_correction_supersedes_prior
    """
    ctx = fx.setup_seated_student(
        ada_method="AGGREGATE_MEMBERSHIP", minimum_daily_minutes=240, clock_days=1,
        meeting_minutes=240)
    rec = fx.post_attendance(ctx["assignment"]["id"], 1, "ABSENT_UNEXCUSED")
    new_rec = validate_success(
        api.correct_attendance_record(rec["id"], {"code": "PRESENT"}, TEACH),
        expected_status=201,
    )
    assert new_rec["status"] == "RECORDED" and new_rec["code"] == "PRESENT"
    prior = validate_success(api.get_attendance_record(rec["id"], REG))
    assert prior["status"] == "SUPERSEDED", "corrected record is superseded"
    enr = validate_success(api.get_enrollment(ctx["enrollment"]["id"], REG))
    assert enr["present_days"] == 1, f"present_days rises to 1 after correction, got {enr['present_days']}"


# ---------------------------------------------------------------------------
# corner: immediate_present_days_visible_after_attendance_post
# ---------------------------------------------------------------------------
def test_present_days_visible_immediately_after_post(api):
    """PRD §2.7: "the server recomputes the affected derived fields immediately and
    in the same transaction". PRD §3.6: "From these eligible days the enrollment's
    present_days is recomputed on every rollup".

    Design: Corner/consistency_model/immediate_present_days_visible_after_attendance_post
    """
    ctx = fx.setup_seated_student(
        ada_method="AGGREGATE_MEMBERSHIP", minimum_daily_minutes=240, clock_days=1,
        meeting_minutes=240)
    fx.post_attendance(ctx["assignment"]["id"], 1, "PRESENT")
    enr = validate_success(api.get_enrollment(ctx["enrollment"]["id"], REG))
    assert enr["present_days"] == 1, f"present_days immediately 1, got {enr['present_days']}"
